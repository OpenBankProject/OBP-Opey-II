#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import meow from 'meow';
import * as readline from 'node:readline';
import {OpeyApiClient} from './api.js';
import {runOAuthFlow} from './oauth.js';
import App from './app.js';

const cli = meow(
	`
	Usage
	  $ opey [options]

	Options
	  --base-url          Opey backend URL (default: http://localhost:5000)
	  --consent-id        OBP Consent-Id for authenticated session
	  --token             Bearer token for MCP server auth
	  --oauth-base        OAuth provider base URL (metadata discovered)
	  --oauth-issuer      Full issuer discovery URL
	  --client-id         OAuth client ID
	  --scope             OAuth scopes (default: openid email profile)
	  --redirect-port     Local port for OAuth callback (default: 48763)
	  --interactive       Interactive setup wizard
	  --help              Show this help

	Examples
	  $ opey
	  $ opey --base-url http://localhost:5000 --consent-id <jwt>
	  $ opey --oauth-base https://idp.example.com --client-id myapp
	  $ opey --interactive
`,
	{
		importMeta: import.meta,
		flags: {
			baseUrl: {type: 'string', default: 'http://localhost:5000'},
			consentId: {type: 'string'},
			token: {type: 'string'},
			oauthBase: {type: 'string'},
			oauthIssuer: {type: 'string'},
			clientId: {type: 'string'},
			scope: {type: 'string'},
			redirectPort: {type: 'number'},
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
		flags.consentId ?? flags.token ?? flags.clientId ?? flags.oauthBase ?? flags.oauthIssuer,
	);
}

async function promptAuth(rl: readline.Interface, flags: typeof cli.flags): Promise<typeof cli.flags> {
	console.log('\n🔒 No authentication credentials provided.\n');
	console.log('  1) Consent-Id  — Paste an OBP Consent-Id JWT');
	console.log('  2) OAuth       — Browser-based OAuth 2.1 flow');
	console.log('  3) Anonymous   — Continue without authentication\n');

	const choice = await ask(rl, 'Choose auth method (1/2/3)', '1');

	switch (choice) {
		case '1':
		case 'consent': {
			flags.consentId = await ask(rl, 'Consent-Id (JWT)');
			const token = await ask(rl, 'Bearer token (optional)');
			if (token) flags.token = token;
			break;
		}

		case '2':
		case 'oauth': {
			flags.oauthBase = await ask(rl, 'OAuth base URL (for metadata discovery)');
			flags.clientId = await ask(rl, 'OAuth client ID');
			flags.scope = await ask(rl, 'OAuth scopes', 'openid email profile');
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

	let bearerToken = flags.token;

	// Run OAuth flow if configured
	if (flags.clientId && (flags.oauthBase || flags.oauthIssuer)) {
		console.log('🔑 Starting OAuth flow…');
		try {
			const tokenSet = await runOAuthFlow({
				issuerBaseUrl: flags.oauthBase,
				issuerUrl: flags.oauthIssuer,
				clientId: flags.clientId,
				scope: flags.scope,
				redirectPort: flags.redirectPort,
			});

			bearerToken = tokenSet.access_token ?? bearerToken;
			console.log('✓ Authenticated successfully.\n');
		} catch (error: unknown) {
			const msg = error instanceof Error ? error.message : String(error);
			console.error(`✗ OAuth failed: ${msg}`);
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
		process.exit(1);
	}

	render(<App client={client} />);
}

void main();
