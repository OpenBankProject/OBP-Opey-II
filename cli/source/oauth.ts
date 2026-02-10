/**
 * OAuth 2.1 flow with PKCE and metadata discovery from a base URL.
 *
 * Tries /.well-known/oauth-authorization-server then /.well-known/openid-configuration.
 */
import http from 'node:http';
import {Issuer, generators, type TokenSet} from 'openid-client';
import open from 'open';

const WELL_KNOWN_PATHS = [
	'/.well-known/oauth-authorization-server',
	'/.well-known/openid-configuration',
];

export type OAuthOptions = {
	/** Full issuer discovery URL (e.g. https://idp.example.com/.well-known/openid-configuration) */
	issuerUrl?: string;
	/** Base URL — metadata will be discovered automatically */
	issuerBaseUrl?: string;
	clientId: string;
	scope?: string;
	redirectPort?: number;
	/** Timeout for waiting for callback in ms */
	timeoutMs?: number;
};

async function discoverIssuer(opts: OAuthOptions): Promise<InstanceType<typeof Issuer>> {
	if (opts.issuerUrl) {
		return Issuer.discover(opts.issuerUrl);
	}

	const base = (opts.issuerBaseUrl ?? '').replace(/\/$/, '');
	if (!base) throw new Error('Either issuerUrl or issuerBaseUrl is required');

	for (const path of WELL_KNOWN_PATHS) {
		try {
			return await Issuer.discover(`${base}${path}`);
		} catch {
			// try next
		}
	}

	throw new Error(`Could not discover OAuth metadata from ${base}`);
}

export async function runOAuthFlow(opts: OAuthOptions): Promise<TokenSet> {
	if (!opts.clientId) throw new Error('clientId is required');

	const issuer = await discoverIssuer(opts);
	const port = opts.redirectPort ?? 48763;
	const redirectUri = `http://127.0.0.1:${port}/callback`;
	const codeVerifier = generators.codeVerifier();
	const codeChallenge = generators.codeChallenge(codeVerifier);

	const client = new issuer.Client({
		client_id: opts.clientId,
		redirect_uris: [redirectUri],
		response_types: ['code'],
		token_endpoint_auth_method: 'none',
	});

	const authUrl = client.authorizationUrl({
		scope: opts.scope ?? 'openid email profile',
		code_challenge: codeChallenge,
		code_challenge_method: 'S256',
		redirect_uri: redirectUri,
	});

	const params = await waitForCallback(authUrl, port, opts.timeoutMs ?? 180_000);
	return client.callback(redirectUri, params, {code_verifier: codeVerifier});
}

function waitForCallback(
	authUrl: string,
	port: number,
	timeoutMs: number,
): Promise<Record<string, string>> {
	return new Promise((resolve, reject) => {
		const server = http.createServer((req, res) => {
			if (!req.url?.startsWith('/callback')) return;
			const parsed = new URL(req.url, `http://127.0.0.1:${port}`);
			res.writeHead(200, {'Content-Type': 'text/plain'});
			res.end('Authentication complete — you can return to the terminal.');
			const params: Record<string, string> = {};
			for (const [k, v] of parsed.searchParams) {
				params[k] = v;
			}

			resolve(params);
			server.close();
		});

		const timer = setTimeout(() => {
			server.close();
			reject(new Error('Timed out waiting for OAuth callback'));
		}, timeoutMs);

		server.on('error', (err) => {
			clearTimeout(timer);
			reject(err);
		});

		server.listen(port, '127.0.0.1', () => {
			void open(authUrl, {wait: false});
		});
	});
}
