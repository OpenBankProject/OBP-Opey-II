/**
 * OAuth 2.1 flow with PKCE, metadata discovery, and optional Dynamic Client Registration.
 *
 * Discovery order:
 *   1. Explicit --oauth-issuer URL
 *   2. OBP well-known endpoint (GET /obp/v5.1.0/well-known → provider OIDC config URLs)
 *   3. Standard .well-known paths on the base URL
 *
 * If no clientId is provided, attempts DCR via the discovered registration_endpoint.
 */
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {Issuer, generators, type TokenSet, type Client} from 'openid-client';
import open from 'open';

const WELL_KNOWN_PATHS = [
	'/.well-known/oauth-authorization-server',
	'/.well-known/openid-configuration',
];

export type OAuthOptions = {
	/** Full issuer discovery URL (e.g. https://idp.example.com/.well-known/openid-configuration) */
	issuerUrl?: string;
	/** OBP API base URL — OIDC config discovered via /obp/v5.1.0/well-known */
	obpBaseUrl?: string;
	/** Explicit OAuth base URL — metadata discovered via standard .well-known paths */
	issuerBaseUrl?: string;
	/** Pre-registered client ID. If omitted, Dynamic Client Registration is attempted. */
	clientId?: string;
	scope?: string;
	redirectPort?: number;
	/** Timeout for waiting for callback in ms */
	timeoutMs?: number;
};

type CachedRegistration = {
	issuer: string;
	client_id: string;
	client_secret?: string;
	registered_at: string;
};

const CONFIG_DIR = path.join(os.homedir(), '.config', 'opey');
const DCR_CACHE_FILE = path.join(CONFIG_DIR, 'dcr-registration.json');

function loadCachedRegistration(issuerUrl: string): CachedRegistration | null {
	try {
		const data = JSON.parse(fs.readFileSync(DCR_CACHE_FILE, 'utf-8')) as CachedRegistration;
		if (data.issuer === issuerUrl && data.client_id) {
			return data;
		}
	} catch {
		// No cache or invalid
	}

	return null;
}

export function clearCachedRegistration(): boolean {
	try {
		if (fs.existsSync(DCR_CACHE_FILE)) {
			fs.unlinkSync(DCR_CACHE_FILE);
			return true;
		}
	} catch {
		// ignore
	}

	return false;
}

function saveCachedRegistration(reg: CachedRegistration): void {
	try {
		fs.mkdirSync(CONFIG_DIR, {recursive: true});
		fs.writeFileSync(DCR_CACHE_FILE, JSON.stringify(reg, null, 2));
	} catch {
		// Non-fatal — registration still works, just won't be cached
	}
}

/**
 * Discover OIDC config URL from OBP's well-known endpoint.
 * Returns the URL of the first available provider's OIDC configuration.
 */
async function discoverFromObpWellKnown(obpBaseUrl: string): Promise<string | null> {
	const base = obpBaseUrl.replace(/\/$/, '');
	try {
		const res = await fetch(`${base}/obp/v5.1.0/well-known`);
		if (!res.ok) return null;
		const data = (await res.json()) as {well_known_uris?: Array<{provider: string; url: string}>};
		const uris = data.well_known_uris ?? [];
		if (uris.length === 0) return null;
		// Prefer obp-oidc, fall back to first available
		const obpOidc = uris.find((u) => u.provider === 'obp-oidc');
		const chosen = obpOidc ?? uris[0]!;
		console.log(`  Discovered OAuth provider: ${chosen.provider}`);
		return chosen.url;
	} catch {
		return null;
	}
}

async function discoverIssuer(opts: OAuthOptions): Promise<InstanceType<typeof Issuer>> {
	// 1. Explicit issuer URL
	if (opts.issuerUrl) {
		return Issuer.discover(opts.issuerUrl);
	}

	// 2. OBP well-known endpoint (auto-discovers OIDC provider)
	if (opts.obpBaseUrl) {
		const oidcConfigUrl = await discoverFromObpWellKnown(opts.obpBaseUrl);
		if (oidcConfigUrl) {
			return Issuer.discover(oidcConfigUrl);
		}
	}

	// 3. Standard .well-known paths on explicit base URL
	const base = (opts.issuerBaseUrl ?? '').replace(/\/$/, '');
	if (base) {
		for (const wkPath of WELL_KNOWN_PATHS) {
			try {
				return await Issuer.discover(`${base}${wkPath}`);
			} catch {
				// try next
			}
		}
	}

	throw new Error(
		'Could not discover OAuth metadata. Provide --obp-url, --oauth-base, or --oauth-issuer.',
	);
}

/**
 * Register a client dynamically via the issuer's registration_endpoint (RFC 7591).
 * Returns a Client instance ready for the auth flow.
 */
async function registerClient(
	issuer: InstanceType<typeof Issuer>,
	redirectUri: string,
): Promise<Client> {
	const issuerUrl = issuer.metadata.issuer;

	// Check cache first
	const cached = loadCachedRegistration(issuerUrl);
	if (cached) {
		console.log(`  Using cached client registration (${cached.client_id})`);
		return new issuer.Client({
			client_id: cached.client_id,
			client_secret: cached.client_secret,
			redirect_uris: [redirectUri],
			response_types: ['code'],
			token_endpoint_auth_method: cached.client_secret ? 'client_secret_post' : 'none',
		});
	}

	// Use advertised registration_endpoint, or fall back to OBP-OIDC's known DCR path.
	// OBP-OIDC supports DCR at {issuer}/connect/register but may not advertise it in
	// metadata when ENABLE_DYNAMIC_CLIENT_REGISTRATION is not set in the well-known response.
	let registrationEndpoint = issuer.metadata.registration_endpoint as string | undefined;
	if (!registrationEndpoint || registrationEndpoint === 'null') {
		registrationEndpoint = `${issuerUrl.replace(/\/$/, '')}/connect/register`;
	}

	console.log('  Registering client dynamically…');

	const res = await fetch(registrationEndpoint, {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({
			client_name: 'Opey CLI',
			redirect_uris: [redirectUri],
			response_types: ['code'],
			grant_types: ['authorization_code'],
			token_endpoint_auth_method: 'none',
		}),
	});

	if (!res.ok) {
		const body = await res.text();
		throw new Error(`Dynamic Client Registration failed (${res.status}): ${body}`);
	}

	const clientInfo = (await res.json()) as {
		client_id: string;
		client_secret?: string;
		[key: string]: unknown;
	};

	console.log(`  DCR response: client_id=${clientInfo.client_id}`);

	// Cache for future runs
	saveCachedRegistration({
		issuer: issuerUrl,
		client_id: clientInfo.client_id,
		client_secret: clientInfo.client_secret,
		registered_at: new Date().toISOString(),
	});

	console.log(`  Registered as ${clientInfo.client_id}`);

	return new issuer.Client({
		client_id: clientInfo.client_id,
		client_secret: clientInfo.client_secret,
		redirect_uris: [redirectUri],
		response_types: ['code'],
		token_endpoint_auth_method: clientInfo.client_secret ? 'client_secret_post' : 'none',
	});
}

export async function runOAuthFlow(opts: OAuthOptions): Promise<TokenSet> {
	const issuer = await discoverIssuer(opts);
	const port = opts.redirectPort ?? 48763;
	const redirectUri = `http://127.0.0.1:${port}/callback`;
	const codeVerifier = generators.codeVerifier();
	const codeChallenge = generators.codeChallenge(codeVerifier);

	let client: Client;
	if (opts.clientId) {
		client = new issuer.Client({
			client_id: opts.clientId,
			redirect_uris: [redirectUri],
			response_types: ['code'],
			token_endpoint_auth_method: 'none',
		});
	} else {
		client = await registerClient(issuer, redirectUri);
	}

	const authUrl = client.authorizationUrl({
		scope: opts.scope ?? 'openid email profile',
		code_challenge: codeChallenge,
		code_challenge_method: 'S256',
		redirect_uri: redirectUri,
	});

	const params = await waitForCallback(authUrl, port, opts.timeoutMs ?? 180_000);

	// Do the token exchange manually instead of client.callback() to skip
	// OIDC ID token audience validation — OBP-OIDC sets aud to the OBP API URL
	// rather than the client_id, which openid-client rejects.
	const code = params['code'];
	if (!code) {
		const error = params['error'] ?? 'unknown';
		const desc = params['error_description'] ?? '';
		throw new Error(`${error}${desc ? ` (${desc})` : ''}`);
	}

	const tokenEndpoint = issuer.metadata.token_endpoint as string;
	if (!tokenEndpoint) throw new Error('Issuer has no token_endpoint');

	const body = new URLSearchParams({
		grant_type: 'authorization_code',
		code,
		redirect_uri: redirectUri,
		client_id: client.metadata.client_id,
		code_verifier: codeVerifier,
	});

	const tokenRes = await fetch(tokenEndpoint, {
		method: 'POST',
		headers: {'Content-Type': 'application/x-www-form-urlencoded'},
		body: body.toString(),
	});

	if (!tokenRes.ok) {
		const errBody = await tokenRes.text();
		throw new Error(`Token exchange failed (${tokenRes.status}): ${errBody}`);
	}

	const tokens = (await tokenRes.json()) as {access_token?: string; [k: string]: unknown};
	return tokens as TokenSet;
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
