#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import meow from 'meow';
import * as readline from 'node:readline';
import {OpeyApiClient} from './api.js';
import {runOAuthFlow, clearCachedRegistration} from './oauth.js';
import App from './app.js';

const cli = meow(
	`
	Usage
	  $ opey [options]

	Options
	  --base-url            Opey backend URL (default: http://localhost:5000)
	  --obp-url             OBP API base URL (auto-discovers OAuth via /obp/v5.1.0/well-known)
	  --opey-consumer-id    Opey consumer ID for consent creation (or env OPEY_CONSUMER_ID)
	  --client-id           OAuth client ID (omit for Dynamic Client Registration)
	  --oauth-base          OAuth provider base URL (override auto-discovery)
	  --oauth-issuer        Full OIDC issuer URL (override auto-discovery)
	  --scope               OAuth scopes (default: openid email profile)
	  --redirect-port       Local port for OAuth callback (default: 48763)
	  --consent-id          OBP Consent-Id for manual auth
	  --token               Bearer token for manual auth
	  --clear-cached-client Clear cached DCR client registration
	  --interactive         Interactive setup wizard
	  --help                Show this help

	Examples
	  $ opey --obp-url https://apisandbox.openbankproject.com --opey-consumer-id abc123
	  $ opey --base-url http://localhost:5000 --consent-id <jwt>
	  $ opey --interactive
`,
	{
		importMeta: import.meta,
		flags: {
			baseUrl: {type: 'string', default: 'http://localhost:5000'},
			obpUrl: {type: 'string'},
			opeyConsumerId: {type: 'string'},
			consentId: {type: 'string'},
			token: {type: 'string'},
			oauthBase: {type: 'string'},
			oauthIssuer: {type: 'string'},
			clientId: {type: 'string'},
			scope: {type: 'string'},
			redirectPort: {type: 'number'},
			clearCachedClient: {type: 'boolean', default: false},
			interactive: {type: 'boolean', default: false},
		},
	},
);

// ─── Interactive setup ──────────────────────────────────────────────────────

function ask(rl: readline.Interface, question: string, defaultValue?: string): Promise<string> {
	const suffix = defaultValue ? ` [${defaultValue}]` : '';
	return new Promise((resolve) => {
		rl.question(`${question}${suffix}: `, (answer) => {
			resolve(answer.trim() || defaultValue || '');
		});
	});
}

function hasAuthFlags(flags: typeof cli.flags): boolean {
	return Boolean(
		flags.consentId ?? flags.token ?? flags.clientId ?? flags.oauthBase ?? flags.oauthIssuer ?? flags.obpUrl ?? flags.opeyConsumerId,
	);
}

async function promptAuth(rl: readline.Interface, flags: typeof cli.flags): Promise<typeof cli.flags> {
	console.log('\n🔒 No authentication credentials provided.\n');
	console.log('  1) OBP OAuth   — Browser-based login to OBP (recommended)');
	console.log('  2) Consent-Id  — Paste an OBP Consent-Id JWT (manual)');
	console.log('  3) Anonymous   — Continue without authentication\n');

	const choice = await ask(rl, 'Choose auth method (1/2/3)', '1');

	switch (choice) {
		case '1':
		case 'oauth': {
			if (!flags.obpUrl) {
				flags.obpUrl = await ask(rl, 'OBP API base URL', 'https://apisandbox.openbankproject.com');
			}

			flags.clientId = await ask(rl, 'OAuth client ID (leave blank for auto-registration)');
			flags.scope = await ask(rl, 'OAuth scopes', 'openid email profile');

			if (!flags.opeyConsumerId) {
				flags.opeyConsumerId = process.env['OPEY_CONSUMER_ID'] ?? await ask(rl, 'Opey consumer ID (for consent creation)');
			}

			break;
		}

		case '2':
		case 'consent': {
			flags.consentId = await ask(rl, 'Consent-Id (JWT)');
			const token = await ask(rl, 'Bearer token (optional)');
			if (token) flags.token = token;
			break;
		}

		case '3':
		case 'anonymous':
		case 'none':
			console.log('  Continuing anonymously.\n');
			break;

		default:
			console.log('  Unrecognised choice — continuing anonymously.\n');
			break;
	}

	return flags;
}

async function interactiveSetup(): Promise<typeof cli.flags> {
	const rl = readline.createInterface({input: process.stdin, output: process.stdout});
	const flags = {...cli.flags};

	try {
		console.log('\n🤖 Opey CLI — Interactive Setup\n');

		flags.baseUrl = await ask(rl, 'Opey backend URL', flags.baseUrl);
		flags.obpUrl = await ask(rl, 'OBP API base URL', flags.obpUrl ?? 'https://apisandbox.openbankproject.com');
		await promptAuth(rl, flags);

		console.log('');
	} finally {
		rl.close();
	}

	return flags;
}

// ─── Main ───────────────────────────────────────────────────────────────────

async function main() {
	let flags: typeof cli.flags;

	if (cli.flags.interactive) {
		flags = await interactiveSetup();
	} else if (hasAuthFlags(cli.flags)) {
		flags = cli.flags;
	} else {
		// No auth provided via flags — ask before falling back to anonymous
		const rl = readline.createInterface({input: process.stdin, output: process.stdout});
		try {
			flags = await promptAuth(rl, {...cli.flags});
		} finally {
			rl.close();
		}
	}

	if (flags.clearCachedClient) {
		if (clearCachedRegistration()) {
			console.log('Cleared cached DCR client registration.\n');
		} else {
			console.log('No cached client registration found.\n');
		}
	}

	let bearerToken = flags.token;

	// Resolve Opey consumer ID from flag or env
	const opeyConsumerId = flags.opeyConsumerId ?? process.env['OPEY_CONSUMER_ID'];

	// If opeyConsumerId was provided but no obpUrl, prompt for it
	if (opeyConsumerId && !flags.obpUrl && !flags.oauthBase && !flags.oauthIssuer && !bearerToken && !flags.consentId) {
		const rl = readline.createInterface({input: process.stdin, output: process.stdout});
		try {
			flags.obpUrl = await ask(rl, 'OBP API base URL', 'https://apisandbox.openbankproject.com');
		} finally {
			rl.close();
		}
	}

	// Run OAuth flow if configured (clientId optional — DCR used when absent)
	// Discovery: obpUrl → OBP well-known endpoint; oauthBase → standard .well-known; oauthIssuer → explicit URL
	if (flags.obpUrl || flags.oauthBase || flags.oauthIssuer) {
		const port = flags.redirectPort ?? 48763;
		const redirectUri = `http://127.0.0.1:${port}/callback`;
		console.log('🔑 Starting OAuth flow…');
		console.log(`  Redirect URI: ${redirectUri}`);
		if (flags.clientId) {
			console.log(`  Client ID: ${flags.clientId}`);
		} else {
			console.log('  Client ID: (will register dynamically via DCR)');
		}

		try {
			const tokenSet = await runOAuthFlow({
				obpBaseUrl: flags.obpUrl,
				issuerBaseUrl: flags.oauthBase,
				issuerUrl: flags.oauthIssuer,
				clientId: flags.clientId || undefined,
				scope: flags.scope,
				redirectPort: flags.redirectPort,
			});

			bearerToken = tokenSet.access_token ?? bearerToken;
			console.log('✓ Authenticated successfully.\n');
		} catch (error: unknown) {
			const msg = error instanceof Error ? error.message : String(error);
			console.error(`✗ OAuth failed: ${msg}`);
			if (flags.clientId) {
				console.error(`  Hint: client "${flags.clientId}" may not have redirect_uri "${redirectUri}" registered.`);
				console.error('  Try omitting --client-id to use Dynamic Client Registration instead.');
			}

			process.exit(1);
		}
	}

	const client = new OpeyApiClient({
		baseUrl: flags.baseUrl,
		consentId: flags.consentId,
		bearerToken,
	});

	// Create session before rendering the UI
	try {
		const session = await client.createSession();
		console.log(`Session: ${session.session_type ?? 'created'}\n`);
	} catch (error: unknown) {
		const msg = error instanceof Error ? error.message : String(error);
		console.error(`Failed to create session: ${msg}`);
		console.error(`  (Opey backend URL: ${flags.baseUrl})`);
		if (flags.baseUrl !== 'http://localhost:5000' && !flags.baseUrl.includes(':5000')) {
			console.error('  Hint: --base-url should point to the Opey backend, not the OBP API.');
			console.error('  Use --obp-url for the OBP API base URL.');
		}

		process.exit(1);
	}

	// Consent config — needed for automatic consent creation
	const consentConfig = (flags.obpUrl && opeyConsumerId && bearerToken)
		? {obpBaseUrl: flags.obpUrl, opeyConsumerId, accessToken: bearerToken}
		: undefined;

	render(<App client={client} consentConfig={consentConfig} />);
}

void main();
