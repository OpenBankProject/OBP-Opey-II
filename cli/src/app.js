import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, Newline} from 'ink';
import TextInput from 'ink-text-input';

import {OpeyApiClient} from './api.js';

const timestamp = () => new Date().toLocaleTimeString();

export function App({baseUrl, consentId, bearerToken}) {
  const [client] = useState(() => new OpeyApiClient({baseUrl, consentId, bearerToken}));
  const [sessionType, setSessionType] = useState(null);
  const [threadId, setThreadId] = useState(null);
  const [status, setStatus] = useState({phase: 'init', message: 'Creating session...'});
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState([]);
  const [toolEvents, setToolEvents] = useState([]);
  const [pendingApproval, setPendingApproval] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const run = async () => {
      try {
        const res = await client.createSession();
        setSessionType(res.session_type || res.message || 'unknown');
        setStatus({phase: 'ready', message: 'Session ready'});
      } catch (err) {
        setStatus({phase: 'error', message: err.message});
        setError(err);
      }
    };
    run();
  }, [client]);

  const addMessage = entry => {
    setMessages(prev => [...prev, {...entry, id: `${prev.length}-${entry.role}`}]);
  };

  const updateAssistant = (content, finalize = false) => {
    setMessages(prev => {
      const next = [...prev];
      const idx = [...next].reverse().findIndex(m => m.role === 'assistant');
      const realIdx = idx === -1 ? -1 : next.length - 1 - idx;
      if (realIdx === -1) {
        next.push({id: `${next.length}-assistant`, role: 'assistant', content});
      } else {
        const existing = next[realIdx];
        const merged = finalize
          ? (content ?? existing.content ?? '')
          : `${existing.content || ''}${content}`;
        next[realIdx] = {...existing, content: merged};
      }
      return next;
    });
  };

  const recordToolEvent = evt => {
    setToolEvents(prev => [
      {id: `${prev.length}-${evt.type}`, ts: timestamp(), ...evt},
      ...prev,
    ].slice(0, 10));
  };

  const handleEvent = evt => {
    switch (evt?.type) {
      case 'thread_sync':
        setThreadId(evt.thread_id);
        break;
      case 'assistant_start':
        updateAssistant('', false);
        break;
      case 'assistant_token':
        updateAssistant(evt.content || '', false);
        break;
      case 'assistant_complete':
        updateAssistant(evt.content || '', true);
        break;
      case 'tool_start':
        recordToolEvent({type: 'tool', label: `${evt.tool_name} started`});
        break;
      case 'tool_complete':
        recordToolEvent({type: 'tool', label: `${evt.tool_name} → ${evt.status || 'done'}`});
        break;
      case 'approval_request':
        setPendingApproval({kind: 'single', data: evt});
        break;
      case 'batch_approval_request':
        setPendingApproval({kind: 'batch', data: evt});
        break;
      case 'consent_request':
        setPendingApproval({kind: 'consent', data: evt});
        break;
      case 'error':
        setError(new Error(evt.error_message || 'Unknown error'));
        break;
      default:
        break;
    }
  };

  const runStream = async (generator) => {
    for await (const evt of generator) {
      handleEvent(evt);
      if (evt?.type === 'approval_request' || evt?.type === 'batch_approval_request' || evt?.type === 'consent_request') {
        break;
      }
    }
  };

  const sendChat = async value => {
    if (!value.trim()) return;
    if (status.phase !== 'ready') {
      setError(new Error('Session not ready yet.'));
      return;
    }
    setBusy(true);
    setError(null);
    addMessage({role: 'user', content: value});
    setInputValue('');
    try {
      const payload = {message: value, thread_id: threadId, stream_tokens: true};
      await runStream(client.streamMessage(payload));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const submitApproval = async answer => {
    if (!pendingApproval) return;
    setBusy(true);
    setError(null);

    try {
      const kind = pendingApproval.kind;
      const evt = pendingApproval.data;
      let payload = {};

      if (kind === 'single') {
        const approved = /^y(es)?/i.test(answer.trim() || 'y');
        const level = evt.available_approval_levels?.[0] || 'once';
        payload = {
          approval: approved ? 'approve' : 'deny',
          level,
          tool_call_id: evt.tool_call_id,
        };
      } else if (kind === 'batch') {
        const approved = /^y(es)?/i.test(answer.trim() || 'y');
        const decisions = {};
        for (const tc of evt.tool_calls || []) {
          decisions[tc.tool_call_id] = {approved, level: 'once'};
        }
        payload = {batch_decisions: decisions};
      } else if (kind === 'consent') {
        const token = answer.trim();
        payload = {consent_jwt: token || null};
      }

      setPendingApproval(null);
      await runStream(client.sendApproval(threadId, payload));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const placeholder = useMemo(() => {
    if (pendingApproval?.kind === 'single') return 'Approve? y / n';
    if (pendingApproval?.kind === 'batch') return 'Approve all? y / n';
    if (pendingApproval?.kind === 'consent') return 'Paste Consent JWT or leave blank to deny';
    return 'Ask Opey something...';
  }, [pendingApproval]);

  const onSubmit = value => {
    if (pendingApproval) {
      submitApproval(value);
    } else {
      sendChat(value);
    }
  };

  const StatusLine = () => (
    <Box>
      <Text color="gray">[{status.phase === 'ready' ? 'ok' : status.phase}] </Text>
      <Text>{status.message}</Text>
      {threadId ? <Text color="gray"> • thread {threadId.slice(0, 8)}</Text> : null}
    </Box>
  );

  return (
    <Box flexDirection="column">
      <Header baseUrl={baseUrl} sessionType={sessionType} bearerToken={bearerToken} consentId={consentId} />
      <StatusLine />

      {error ? (
        <Text color="red">{error.message}</Text>
      ) : null}

      <Box marginTop={1} flexDirection="row">
        <Box flexGrow={1} borderStyle="round" borderColor="gray" padding={1} flexDirection="column">
          <Text color="cyan">Conversation</Text>
          <Newline />
          {messages.length === 0 ? <Text color="gray">No messages yet.</Text> : null}
          {messages.map(msg => (
            <Text key={msg.id}>
              <Text color={msg.role === 'user' ? 'green' : 'yellow'}>{msg.role === 'user' ? 'You' : 'Opey'}:</Text>{' '}
              {msg.content}
            </Text>
          ))}
        </Box>

        <Box width={38} marginLeft={1} borderStyle="round" borderColor="gray" padding={1} flexDirection="column">
          <Text color="magenta">Tool calls</Text>
          <Newline />
          {toolEvents.length === 0 ? <Text color="gray">Waiting...</Text> : null}
          {toolEvents.map(evt => (
            <Text key={evt.id}>
              <Text color="gray">{evt.ts} </Text>
              {evt.label}
            </Text>
          ))}
        </Box>
      </Box>

      {pendingApproval ? <ApprovalPanel pending={pendingApproval} /> : null}

      <Box marginTop={1}>
        {busy ? <Text color="cyan">Processing...</Text> : null}
        <TextInput
          value={inputValue}
          onChange={setInputValue}
          onSubmit={onSubmit}
          placeholder={placeholder}
        />
      </Box>
    </Box>
  );
}

function Header({baseUrl, sessionType, bearerToken, consentId}) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color="cyanBright">Opey Ink CLI</Text>
      <Text color="gray">{baseUrl} • session: {sessionType || '...'} • auth: {authLabel({bearerToken, consentId})}</Text>
    </Box>
  );
}

function authLabel({bearerToken, consentId}) {
  const bits = [];
  if (bearerToken) bits.push('bearer');
  if (consentId) bits.push('consent');
  return bits.length ? bits.join(', ') : 'anonymous';
}

function ApprovalPanel({pending}) {
  const {kind, data} = pending;

  if (kind === 'single') {
    return (
      <Box marginTop={1} borderStyle="round" borderColor="yellow" padding={1} flexDirection="column">
        <Text color="yellow">Approval required</Text>
        <Text>Tool: {data.tool_name}</Text>
        <Text>Input: {JSON.stringify(data.tool_input)}</Text>
        <Text>Levels: {(data.available_approval_levels || []).join(', ') || 'once'}</Text>
        <Text color="gray">Type y / n then Enter.</Text>
      </Box>
    );
  }

  if (kind === 'batch') {
    return (
      <Box marginTop={1} borderStyle="round" borderColor="yellow" padding={1} flexDirection="column">
        <Text color="yellow">Batch approval required</Text>
        <Text>{(data.tool_calls || []).length} tool calls pending.</Text>
        <Text color="gray">Type y / n then Enter.</Text>
      </Box>
    );
  }

  if (kind === 'consent') {
    return (
      <Box marginTop={1} borderStyle="round" borderColor="yellow" padding={1} flexDirection="column">
        <Text color="yellow">Consent required</Text>
        <Text>Tool: {data.tool_name}</Text>
        <Text>Operation: {data.operation_id}</Text>
        <Text>Roles: {JSON.stringify(data.required_roles || [])}</Text>
        <Text color="gray">Paste Consent JWT or leave blank to deny.</Text>
      </Box>
    );
  }

  return null;
}
