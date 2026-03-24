# Opey CLI

Terminal chat interface for [Opey](https://github.com/OpenBankProject/OBP-Opey-II) — the AI assistant for the Open Bank Project API.

Connects to the Opey backend, authenticates via OAuth (auto-discovered from OBP's well-known endpoint), and provides an interactive chat with tool approval and automatic OBP consent creation.

## Prerequisites

- Node.js >= 18
- A running Opey backend (default: `http://localhost:5000`)
- A running OBP-API instance with OBP-OIDC enabled
- The OBP-MCP server configured with `OBP_AUTHORIZATION_VIA=consent`

## Install

```bash
cd cli
npm install
npm run build
```

To install globally:

```bash
npm install -g .
```

## Usage

```
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
  --consent-id          OBP Consent-Id JWT for manual auth
  --token               Bearer token for manual auth
  --interactive         Interactive setup wizard
  --help                Show help
```

## Quick Start

The simplest way to start — just provide the OBP URL and Opey's consumer ID:

```bash
opey --obp-url https://apisandbox.openbankproject.com --opey-consumer-id <id>
```

This will:
1. Discover OBP-OIDC metadata automatically
2. Register a client dynamically (DCR) — no pre-registered client ID needed
3. Open your browser to log in
4. Create an authenticated session on the Opey backend
5. Start the chat interface

## Authentication

### OAuth (recommended)

The CLI authenticates via OAuth 2.1 with PKCE. When `--obp-url` is provided, the OIDC configuration is auto-discovered by calling `GET /obp/v5.1.0/well-known` on the OBP API, which returns the available OAuth providers and their configuration URLs. This is the same mechanism used by OBP-Portal.

**Dynamic Client Registration**: If no `--client-id` is provided, the CLI registers itself automatically via RFC 7591 DCR using the issuer's `registration_endpoint`. The registration is cached in `~/.config/opey/dcr-registration.json` for subsequent runs.

**With a pre-registered client**:

```bash
opey --obp-url https://apisandbox.openbankproject.com --client-id myapp
```

### Manual auth

For development or testing, you can pass credentials directly:

```bash
# With a Consent-Id JWT
opey --consent-id <jwt>

# With a bearer token
opey --token <bearer-token>
```

### Interactive wizard

Run with `--interactive` for a guided setup:

```bash
opey --interactive
```

## Consent-on-Tool Flow

When the Opey agent needs to call an OBP API endpoint that requires elevated permissions, the CLI handles consent creation automatically:

1. The agent attempts the API call via the MCP server
2. MCP returns `consent_required` with the roles needed
3. The CLI shows the required roles and asks for approval
4. On approval, the CLI creates an IMPLICIT consent via the OBP API using your OAuth token
5. The consent JWT is sent back to the agent, which retries the call

Roles are deduplicated using OBP's superseding rules (e.g. `CanCreateAtmAtAnyBank` supersedes `CanCreateAtm`), and the best matching role from your entitlements is selected automatically.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPEY_CONSUMER_ID` | Opey's consumer ID (alternative to `--opey-consumer-id` flag) |

## Development

```bash
npm run dev    # Watch mode — recompiles on changes
npm run build  # One-time build
npm test       # Run prettier, xo linter, and ava tests
```
