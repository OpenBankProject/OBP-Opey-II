import http from 'node:http';
import {Issuer, generators} from 'openid-client';
import open from 'open';

const DEFAULT_SCOPE = 'openid email profile';

const metadataPaths = [
  '/.well-known/oauth-authorization-server',
  '/.well-known/openid-configuration',
];

const normalizeBase = base => base.replace(/\/$/, '');

export async function discoverIssuerFromBase(baseUrl) {
  if (!baseUrl) throw new Error('issuer base URL is required');
  const cleaned = normalizeBase(baseUrl);

  for (const path of metadataPaths) {
    const url = `${cleaned}${path}`;
    try {
      // openid-client supports passing a discovery URL directly
      // and will fetch metadata itself.
      return await Issuer.discover(url);
    } catch (err) {
      // Try next candidate
    }
  }

  throw new Error(`Could not discover OAuth metadata from base ${baseUrl}`);
}

export async function runOAuthFlow({
  issuerUrl,
  issuerBaseUrl,
  clientId,
  clientSecret,
  scope = DEFAULT_SCOPE,
  redirectPort = 48763,
  clientName = 'Opey Ink CLI',
} = {}) {
  if (!clientId) {
    throw new Error('clientId is required for OAuth flow');
  }

  const issuer = issuerUrl
    ? await Issuer.discover(issuerUrl)
    : await discoverIssuerFromBase(issuerBaseUrl);

  const redirectUri = `http://127.0.0.1:${redirectPort}/callback`;
  const codeVerifier = generators.codeVerifier();
  const codeChallenge = generators.codeChallenge(codeVerifier);

  const client = new issuer.Client({
    client_id: clientId,
    client_secret: clientSecret,
    client_name: clientName,
    redirect_uris: [redirectUri],
    response_types: ['code'],
    token_endpoint_auth_method: clientSecret ? 'client_secret_basic' : 'none',
  });

  const authorizationUrl = client.authorizationUrl({
    scope,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
    redirect_uri: redirectUri,
  });

  const params = await waitForCallback({url: authorizationUrl, port: redirectPort});

  return client.callback(redirectUri, params, {code_verifier: codeVerifier});
}

async function waitForCallback({url, port, timeoutMs = 180000}) {
  await open(url, {wait: false});

  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (!req.url?.startsWith('/callback')) return;
      const parsed = new URL(req.url, `http://127.0.0.1:${port}`);
      res.writeHead(200, {'Content-Type': 'text/plain'});
      res.end('Authentication complete. You can return to the terminal.');
      resolve(parsed.searchParams);
      server.close();
    });

    const timer = setTimeout(() => {
      server.close();
      reject(new Error('Timed out waiting for OAuth callback'));
    }, timeoutMs);

    server.on('error', err => {
      clearTimeout(timer);
      reject(err);
    });

    server.listen(port, '127.0.0.1', () => {
      // Server ready, nothing else to do
    });
  });
}
