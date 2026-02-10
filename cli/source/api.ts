/**
 * Opey API client — handles session creation and SSE streaming.
 */

type Headers = Record<string, string>;

export type SseEvent = {
	type: string;
	[key: string]: unknown;
};

export class OpeyApiClient {
	private baseUrl: string;
	private consentId: string | undefined;
	private bearerToken: string | undefined;
	private sessionCookie: string | undefined;

	constructor(opts: {
		baseUrl?: string;
		consentId?: string;
		bearerToken?: string;
	}) {
		this.baseUrl = (opts.baseUrl ?? 'http://localhost:5000').replace(/\/$/, '');
		this.consentId = opts.consentId;
		this.bearerToken = opts.bearerToken;
	}

	private headers(extra: Headers = {}): Headers {
		const h: Headers = {'Content-Type': 'application/json', ...extra};
		if (this.consentId) h['Consent-Id'] = this.consentId;
		if (this.bearerToken) h['Authorization'] = `Bearer ${this.bearerToken}`;
		if (this.sessionCookie) h['Cookie'] = this.sessionCookie;
		return h;
	}

	private captureSessionCookie(res: Response): void {
		const raw = res.headers.get('set-cookie');
		if (!raw) return;
		const match = raw.match(/session=([^;]+)/);
		if (match) {
			this.sessionCookie = `session=${match[1]}`;
		}
	}

	async createSession(): Promise<{session_type?: string; message?: string}> {
		const res = await fetch(`${this.baseUrl}/create-session`, {
			method: 'POST',
			headers: this.headers(),
		});

		if (!res.ok) {
			const body = await res.text();
			throw new Error(`Failed to create session (${res.status}): ${body}`);
		}

		this.captureSessionCookie(res);
		return (await res.json()) as {session_type?: string; message?: string};
	}

	async *streamMessage(payload: Record<string, unknown>): AsyncGenerator<SseEvent> {
		yield* this.sseStream('/stream', payload);
	}

	async *sendApproval(
		threadId: string,
		payload: Record<string, unknown>,
	): AsyncGenerator<SseEvent> {
		yield* this.sseStream(`/approval/${threadId}`, payload);
	}

	private async *sseStream(
		path: string,
		payload: Record<string, unknown>,
	): AsyncGenerator<SseEvent> {
		const res = await fetch(`${this.baseUrl}${path}`, {
			method: 'POST',
			headers: this.headers(),
			body: JSON.stringify(payload),
		});

		if (!res.ok) {
			const body = await res.text();
			throw new Error(`${path} failed (${res.status}): ${body}`);
		}

		this.captureSessionCookie(res);

		if (!res.body) throw new Error('Response body is null');

		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buffer = '';

		while (true) {
			const {done, value} = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, {stream: true});

			// SSE events are separated by double newlines
			while (buffer.includes('\n\n')) {
				const idx = buffer.indexOf('\n\n');
				const block = buffer.slice(0, idx);
				buffer = buffer.slice(idx + 2);

				for (const line of block.split('\n')) {
					const trimmed = line.trim();
					if (!trimmed.startsWith('data: ')) continue;
					const data = trimmed.slice(6);
					if (data === '[DONE]') {
						yield {type: 'stream_end'};
						continue;
					}
					try {
						yield JSON.parse(data) as SseEvent;
					} catch {
						// skip malformed JSON
					}
				}
			}
		}

		// flush remaining
		if (buffer.trim()) {
			for (const line of buffer.split('\n')) {
				const trimmed = line.trim();
				if (!trimmed.startsWith('data: ')) continue;
				const data = trimmed.slice(6);
				if (data === '[DONE]') {
					yield {type: 'stream_end'};
					continue;
				}
				try {
					yield JSON.parse(data) as SseEvent;
				} catch {
					// skip
				}
			}
		}
	}
}
