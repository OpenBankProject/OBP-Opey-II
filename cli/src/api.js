import {createParser} from 'eventsource-parser';
import setCookie from 'set-cookie-parser';

const decoder = new TextDecoder();

export class OpeyApiClient {
  constructor({baseUrl, consentId, bearerToken} = {}) {
    this.baseUrl = baseUrl?.replace(/\/$/, '') || 'http://localhost:5000';
    this.consentId = consentId || null;
    this.bearerToken = bearerToken || null;
    this.sessionCookie = null;
  }

  _buildHeaders(extra = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...extra,
    };

    if (this.consentId) headers['Consent-Id'] = this.consentId;
    if (this.bearerToken) headers['Authorization'] = `Bearer ${this.bearerToken}`;
    if (this.sessionCookie) headers['Cookie'] = this.sessionCookie;
    return headers;
  }

  _captureSessionCookie(res) {
    const raw = res.headers.get('set-cookie');
    if (!raw) return;
    const parsed = setCookie.parse(raw, {map: true});
    if (parsed.session) {
      this.sessionCookie = `session=${parsed.session.value}`;
    }
  }

  async createSession() {
    const res = await fetch(`${this.baseUrl}/create-session`, {
      method: 'POST',
      headers: this._buildHeaders(),
    });

    if (res.status !== 200) {
      const body = await res.text();
      throw new Error(`Failed to create session (${res.status}): ${body}`);
    }

    this._captureSessionCookie(res);
    return res.json();
  }

  async *streamMessage(payload) {
    yield* this._stream('/stream', payload);
  }

  async *sendApproval(threadId, payload) {
    yield* this._stream(`/approval/${threadId}`, payload);
  }

  async *_stream(path, payload) {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: this._buildHeaders(),
      body: JSON.stringify(payload),
    });

    if (res.status !== 200) {
      const body = await res.text();
      throw new Error(`Request to ${path} failed (${res.status}): ${body}`);
    }

    this._captureSessionCookie(res);

    const parser = createParser(event => {
      if (event.type !== 'event' || !event.data) return;
      let parsed;
      try {
        parsed = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      this._pending?.push(parsed);
    });

    this._pending = [];
    const reader = res.body.getReader();
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        parser.feed(decoder.decode(value, {stream: true}));
        while (this._pending.length) {
          yield this._pending.shift();
        }
      }
      while (this._pending.length) {
        yield this._pending.shift();
      }
    } finally {
      this._pending = null;
    }
  }
}
