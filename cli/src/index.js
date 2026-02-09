#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import {Command} from 'commander';
import {createInterface} from 'node:readline/promises';
import {stdin as input, stdout as output} from 'node:process';

import {App} from './app.js';
import {runOAuthFlow} from './oauth.js';

async function main() {
  const program = new Command();

  program
    .name('opey-cli')
    .description('Ink-based CLI for the Opey agent')
    .option('--base-url <url>', 'Opey service base URL', process.env.OPEY_BASE_URL || 'http://localhost:5000')
    .option('--consent-id <jwt>', 'OBP Consent-Id for authenticated sessions', process.env.CONSENT_ID)
    .option('--token <token>', 'Bearer token for MCP OAuth pass-through', process.env.OPEY_BEARER_TOKEN)
    .option('--oauth-issuer <url>', 'OIDC issuer/discovery URL to run OAuth flow')
    .option('--oauth-base <url>', 'OIDC base URL; will resolve .well-known metadata automatically')
    .option('--client-id <id>', 'OIDC client_id for the CLI')
    .option('--client-secret <secret>', 'OIDC client_secret (if required)')
    .option('--scope <scope>', 'OIDC scopes', process.env.OPEY_OAUTH_SCOPE || 'openid email profile')
    .option('--redirect-port <port>', 'Local port for OAuth redirect', value => parseInt(value, 10), 48763)
    .option('--skip-oauth', 'Do not run OAuth even if issuer is provided', false)
    .option('-i, --interactive', 'Prompt for missing configuration before starting', false)
    .parse(process.argv);

  const opts = program.opts();

  const config = opts.interactive
    ? await interactiveSetup(opts)
    : await nonInteractiveConfig(opts);

  render(
    <App
      baseUrl={config.baseUrl}
      consentId={config.consentId}
      bearerToken={config.bearerToken}
    />
  );
}

main();

async function nonInteractiveConfig(opts) {
  let bearerToken = opts.token;

  const shouldRunOAuth = !opts.skipOauth && (opts.oauthIssuer || opts.oauthBase) && opts.clientId;

  if (shouldRunOAuth) {
    try {
      const tokens = await runOAuthFlow({
        issuerUrl: opts.oauthIssuer,
        issuerBaseUrl: opts.oauthBase || opts.oauthIssuer,
        clientId: opts.clientId,
        clientSecret: opts.clientSecret,
        scope: opts.scope,
        redirectPort: opts.redirectPort,
      });
      bearerToken = tokens.access_token;
      // eslint-disable-next-line no-console
      console.error(`OAuth success. Access token expires in ${tokens.expires_in || 'unknown'}s.`);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`OAuth flow failed: ${err.message}`);
      process.exit(1);
    }
  }

  return {
    baseUrl: opts.baseUrl,
    consentId: opts.consentId,
    bearerToken,
  };
}

async function interactiveSetup(opts) {
  const rl = createInterface({input, output});
  const ask = async (question, fallback = '') => {
    const answer = await rl.question(question);
    return answer.trim() || fallback;
  };

  const baseUrl = await ask(`Opey base URL [${opts.baseUrl}]: `, opts.baseUrl);
  const consentId = await ask('Consent-Id (optional): ', opts.consentId || '');

  let bearerToken = opts.token;

  const runOAuth = /^y(es)?/i.test((await ask('Run OAuth now? (y/N): ', 'n')).toLowerCase());

  if (runOAuth) {
    const oauthBase = await ask('OAuth issuer base (e.g. https://idp.example.com): ', opts.oauthBase || opts.oauthIssuer || '');
    const oauthIssuer = await ask('OAuth issuer discovery URL (optional, overrides base): ', opts.oauthIssuer || '');
    const clientId = await ask('OAuth client_id: ', opts.clientId || '');
    const clientSecret = await ask('OAuth client_secret (optional): ', opts.clientSecret || '');
    const scope = await ask(`Scopes [${opts.scope}]: `, opts.scope);
    const redirectPortAnswer = await ask(`Redirect port [${opts.redirectPort}]: `, String(opts.redirectPort));
    const redirectPort = parseInt(redirectPortAnswer, 10) || opts.redirectPort;

    try {
      const tokens = await runOAuthFlow({
        issuerUrl: oauthIssuer || undefined,
        issuerBaseUrl: oauthBase || oauthIssuer,
        clientId,
        clientSecret: clientSecret || undefined,
        scope,
        redirectPort,
      });
      bearerToken = tokens.access_token;
      // eslint-disable-next-line no-console
      console.error(`OAuth success. Access token expires in ${tokens.expires_in || 'unknown'}s.`);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`OAuth flow failed: ${err.message}`);
      process.exit(1);
    }
  }

  rl.close();

  return {
    baseUrl,
    consentId: consentId || undefined,
    bearerToken,
  };
}
