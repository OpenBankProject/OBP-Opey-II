import React, {useState, useCallback, useEffect, useRef} from 'react';
import {Box, Text, useInput, useApp, Static, Newline} from 'ink';
import {type SseEvent, OpeyApiClient} from './api.js';

// ─── Types ──────────────────────────────────────────────────────────────────

type Role = 'user' | 'assistant' | 'system';

type ChatMessage = {
	id: string;
	role: Role;
	text: string;
};

type ToolStatus = {
	id: string;
	name: string;
	status: 'running' | 'done' | 'error';
	result?: string;
};

type ApprovalPrompt =
	| {kind: 'single'; toolName: string; toolCallId: string; toolInput: unknown; levels: string[]}
	| {kind: 'batch'; toolCalls: Array<{tool_call_id: string; tool_name: string; tool_args: unknown}>}
	| {kind: 'consent'; toolName: string; operationId: string; requiredRoles: string[]};

type AppProps = {
	client: OpeyApiClient;
};

// ─── Helpers ────────────────────────────────────────────────────────────────

let nextId = 0;
const uid = () => String(++nextId);

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

function useSpinner(active: boolean): string {
	const [frame, setFrame] = useState(0);

	useEffect(() => {
		if (!active) return;
		const timer = setInterval(() => {
			setFrame((f) => (f + 1) % SPINNER_FRAMES.length);
		}, 80);
		return () => {
			clearInterval(timer);
		};
	}, [active]);

	return active ? SPINNER_FRAMES[frame]! : '';
}

// ─── Sub-components ─────────────────────────────────────────────────────────

function Prompt({value, active}: {value: string; active: boolean}) {
	return (
		<Box>
			<Text bold color="green">{'❯ '}</Text>
			<Text>{value}</Text>
			{active && <Text color="gray">█</Text>}
		</Box>
	);
}

function Message({msg}: {msg: ChatMessage}) {
	const color = msg.role === 'user' ? 'cyan' : msg.role === 'system' ? 'yellow' : undefined;
	const label = msg.role === 'user' ? 'You' : msg.role === 'system' ? 'System' : 'Opey';
	return (
		<Box flexDirection="column" marginBottom={0}>
			<Text bold color={color}>{label}:</Text>
			<Text>{msg.text}</Text>
		</Box>
	);
}

function ToolIndicator({tool}: {tool: ToolStatus}) {
	const icon = tool.status === 'running' ? '⟳' : tool.status === 'done' ? '✓' : '✗';
	const color = tool.status === 'running' ? 'yellow' : tool.status === 'done' ? 'green' : 'red';
	return (
		<Text>
			<Text color={color}> {icon} </Text>
			<Text dimColor>{tool.name}</Text>
			{tool.status !== 'running' && tool.result ? <Text dimColor>{` → ${tool.result}`}</Text> : null}
		</Text>
	);
}

function ApprovalBox({prompt, inputValue}: {
	prompt: ApprovalPrompt;
	inputValue: string;
}) {
	if (prompt.kind === 'single') {
		return (
			<Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
				<Text bold color="yellow">⚠ Approval Required</Text>
				<Text>Tool: <Text bold>{prompt.toolName}</Text></Text>
				<Text dimColor>Input: {JSON.stringify(prompt.toolInput, null, 2)}</Text>
				<Text dimColor>Levels: {prompt.levels.join(', ')}</Text>
				<Newline />
				<Text>Approve? <Text bold>[y]es / [n]o</Text></Text>
			</Box>
		);
	}

	if (prompt.kind === 'batch') {
		return (
			<Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
				<Text bold color="yellow">⚠ Batch Approval ({prompt.toolCalls.length} tools)</Text>
				{prompt.toolCalls.map((tc, i) => (
					<Text key={tc.tool_call_id}>
						<Text dimColor> {i + 1}. </Text>
						<Text bold>{tc.tool_name}</Text>
						<Text dimColor> {JSON.stringify(tc.tool_args)}</Text>
					</Text>
				))}
				<Newline />
				<Text>Approve all? <Text bold>[y]es / [n]o</Text></Text>
			</Box>
		);
	}

	// consent
	return (
		<Box flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1}>
			<Text bold color="magenta">🔐 Consent Required</Text>
			<Text>Tool: <Text bold>{prompt.toolName}</Text></Text>
			<Text>Operation: {prompt.operationId}</Text>
			<Text dimColor>Roles: {prompt.requiredRoles.join(', ')}</Text>
			<Newline />
			<Text>Paste Consent-JWT (or Enter to deny):</Text>
			<Box>
				<Text color="gray">{'> '}</Text>
				<Text>{inputValue}</Text>
				<Text color="gray">█</Text>
			</Box>
		</Box>
	);
}

// ─── Main App ───────────────────────────────────────────────────────────────

export default function App({client}: AppProps) {
	const {exit} = useApp();

	const [history, setHistory] = useState<ChatMessage[]>([]);
	const [streamingText, setStreamingText] = useState('');
	const [tools, setTools] = useState<ToolStatus[]>([]);
	const [approval, setApproval] = useState<ApprovalPrompt | null>(null);
	const [input, setInput] = useState('');
	const [busy, setBusy] = useState(false);
	const [approvalInput, setApprovalInput] = useState('');
	const threadIdRef = useRef<string | undefined>(undefined);
	const [selectingLevel, setSelectingLevel] = useState(false);

	const spinner = useSpinner(busy);

	const processStream = useCallback(
		async (stream: AsyncGenerator<SseEvent>) => {
			let accum = '';
			for await (const evt of stream) {
				switch (evt.type) {
					case 'thread_sync':
						threadIdRef.current = evt['thread_id'] as string;
						break;

					case 'assistant_start':
						accum = '';
						setStreamingText('');
						break;

					case 'assistant_token':
						accum += (evt['content'] as string) ?? '';
						setStreamingText(accum);
						break;

					case 'assistant_complete': {
						const text = accum || (evt['content'] as string) || '';
						if (text) {
							setHistory((h) => [...h, {id: uid(), role: 'assistant', text}]);
						}

						setStreamingText('');
						accum = '';
						break;
					}

					case 'tool_start': {
						const name = (evt['tool_name'] as string) ?? '?';
						const tcId = (evt['tool_call_id'] as string) ?? uid();
						setTools((t) => [...t, {id: tcId, name, status: 'running'}]);
						break;
					}

					case 'tool_complete': {
						const tcId = (evt['tool_call_id'] as string) ?? '';
						const status = (evt['status'] as string) === 'error' ? 'error' : 'done';
						const result = (evt['result'] as string) ?? (evt['status'] as string) ?? '';
						setTools((t) =>
							t.map((tool) => (tool.id === tcId ? {...tool, status, result} : tool)),
						);
						break;
					}

					case 'approval_request':
						setApproval({
							kind: 'single',
							toolName: (evt['tool_name'] as string) ?? '?',
							toolCallId: (evt['tool_call_id'] as string) ?? '',
							toolInput: evt['tool_input'] ?? {},
							levels: (evt['available_approval_levels'] as string[]) ?? ['once'],
						});
						setBusy(false);
						return;

					case 'batch_approval_request': {
						const calls = (evt['tool_calls'] ?? []) as Array<{tool_call_id: string; tool_name: string; tool_args: unknown}>;
						setApproval({kind: 'batch', toolCalls: calls});
						setBusy(false);
						return;
					}

					case 'consent_request':
						setApproval({
							kind: 'consent',
							toolName: (evt['tool_name'] as string) ?? '?',
							operationId: (evt['operation_id'] as string) ?? '?',
							requiredRoles: (evt['required_roles'] as string[]) ?? [],
						});
						setBusy(false);
						return;

					case 'error':
						setHistory((h) => [
							...h,
							{id: uid(), role: 'system', text: `Error: ${(evt['error_message'] as string) ?? 'Unknown error'}`},
						]);
						break;

					case 'stream_end':
					case 'user_message_confirmed':
					case 'keep_alive':
						break;

					default:
						break;
				}
			}

			setBusy(false);
			setTools([]);
		},
		[],
	);

	const sendMessage = useCallback(
		async (text: string) => {
			setHistory((h) => [...h, {id: uid(), role: 'user', text}]);
			setBusy(true);
			setTools([]);
			setStreamingText('');

			try {
				const stream = client.streamMessage({
					message: text,
					thread_id: threadIdRef.current,
					stream_tokens: true,
				});
				await processStream(stream);
			} catch (error: unknown) {
				const msg = error instanceof Error ? error.message : String(error);
				setHistory((h) => [...h, {id: uid(), role: 'system', text: `Error: ${msg}`}]);
				setBusy(false);
			}
		},
		[client, processStream],
	);

	const sendApproval = useCallback(
		async (data: Record<string, unknown>) => {
			setApproval(null);
			setBusy(true);
			setTools([]);

			try {
				const stream = client.sendApproval(threadIdRef.current ?? '', data);
				await processStream(stream);
			} catch (error: unknown) {
				const msg = error instanceof Error ? error.message : String(error);
				setHistory((h) => [...h, {id: uid(), role: 'system', text: `Error: ${msg}`}]);
				setBusy(false);
			}
		},
		[client, processStream],
	);

	useInput((ch, key) => {
		// Approval prompts
		if (approval) {
			if (approval.kind === 'consent') {
				if (key.return) {
					const jwt = approvalInput.trim();
					setApprovalInput('');
					void sendApproval(jwt ? {consent_jwt: jwt} : {consent_jwt: null});
				} else if (key.backspace || key.delete) {
					setApprovalInput((v) => v.slice(0, -1));
				} else if (ch && !key.ctrl && !key.meta) {
					setApprovalInput((v) => v + ch);
				}

				return;
			}

			if (selectingLevel && approval.kind === 'single') {
				const idx = Number(ch) - 1;
				if (idx >= 0 && idx < approval.levels.length) {
					setSelectingLevel(false);
					void sendApproval({
						approval: 'approve',
						level: approval.levels[idx],
						tool_call_id: approval.toolCallId,
					});
				}

				return;
			}

			if (ch === 'y' || ch === 'Y') {
				if (approval.kind === 'single') {
					if (approval.levels.length > 1) {
						setSelectingLevel(true);
						return;
					}

					void sendApproval({
						approval: 'approve',
						level: approval.levels[0] ?? 'once',
						tool_call_id: approval.toolCallId,
					});
				} else if (approval.kind === 'batch') {
					const decisions: Record<string, {approved: boolean; level: string}> = {};
					for (const tc of approval.toolCalls) {
						decisions[tc.tool_call_id] = {approved: true, level: 'once'};
					}

					void sendApproval({batch_decisions: decisions});
				}
			} else if (ch === 'n' || ch === 'N') {
				if (approval.kind === 'single') {
					void sendApproval({
						approval: 'deny',
						level: 'once',
						tool_call_id: approval.toolCallId,
					});
				} else if (approval.kind === 'batch') {
					const decisions: Record<string, {approved: boolean; level: string}> = {};
					for (const tc of approval.toolCalls) {
						decisions[tc.tool_call_id] = {approved: false, level: 'once'};
					}

					void sendApproval({batch_decisions: decisions});
				}
			}

			return;
		}

		// Normal chat input
		if (busy) return;

		if (key.return && input.trim()) {
			const text = input.trim();
			if (text.toLowerCase() === 'quit' || text.toLowerCase() === 'exit') {
				exit();
				return;
			}

			setInput('');
			void sendMessage(text);
		} else if (key.backspace || key.delete) {
			setInput((v) => v.slice(0, -1));
		} else if (key.ctrl && ch === 'c') {
			exit();
		} else if (ch && !key.ctrl && !key.meta && !key.escape) {
			setInput((v) => v + ch);
		}
	});

	return (
		<Box flexDirection="column" paddingX={1}>
			<Box marginBottom={1}>
				<Text bold color="blueBright">🤖 Opey Chat</Text>
				<Text dimColor>{' — type a message, "quit" to exit'}</Text>
			</Box>

			<Static items={history}>
				{(msg) => (
					<Box key={msg.id} flexDirection="column">
						<Message msg={msg} />
					</Box>
				)}
			</Static>

			{tools.length > 0 && (
				<Box flexDirection="column">
					{tools.map((t) => (
						<ToolIndicator key={t.id} tool={t} />
					))}
				</Box>
			)}

			{streamingText ? (
				<Box flexDirection="column">
					<Text bold>Opey:</Text>
					<Text>{streamingText}</Text>
				</Box>
			) : null}

			{busy && !streamingText && (
				<Text color="yellow">{spinner} thinking…</Text>
			)}

			{approval && (
				<Box marginY={1} flexDirection="column">
					<ApprovalBox prompt={approval} inputValue={approvalInput} />
					{selectingLevel && approval.kind === 'single' && (
						<Box flexDirection="column" marginLeft={2}>
							<Text bold>Select level:</Text>
							{approval.levels.map((l, i) => (
								<Text key={l}> [{i + 1}] {l}</Text>
							))}
						</Box>
					)}
				</Box>
			)}

			{!busy && !approval && <Prompt value={input} active />}
		</Box>
	);
}
