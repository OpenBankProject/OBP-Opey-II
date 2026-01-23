# Opey Agent



An agentic version of the Opey chatbot for Open Bank Project that uses the [LangGraph](https://www.langchain.com/langgraph) framework

### Installing Locally
### 1. Installing the dependencies
The easiest way to do this is using _poetry_. Install using the [reccomended method](https://python-poetry.org/docs/) rather than trying to manually install.

Run `poetry install` in the top level directory (where your pyproject.toml lives) to install dependencies and get poetry to create a venv for you.

> **_NOTE:_**  If you get an error that your python version is not supported, consider using a python version management system like [PyEnv](https://github.com/pyenv/pyenv) to install the compatible version of python. Else just upgrade the global python version if you don't care about other packages potentially breaking.

You can also then run commands by first activating `poetry shell` which should activate the venv created by poetry. This is a neat way to get into the venv created by poetry.

> **_NOTE:_** Poetry does not come with the `shell` command pre-installed
After installing poetry, install the poetry shell plugin with `poetry self add poetry-plugin-shell` and you should be good to go.


### 2. Creating the vector database
Create the 'data' folder by running 
```bash
mkdir src/data
``` 
Check the README.md in the `src/scripts` directory for more information on how to populate the vector database.

Run the vector database population script to create the vector database collections:
```bash
python src/database/populate_vector_db.py
```

#### Automatic Database Updates
Opey II can automatically check for OBP data changes on startup and update the vector database when changes are detected. To enable this feature, set in your `.env`:

```env
UPDATE_DATABASE_ON_STARTUP="true"
UPDATE_DATABASE_ENDPOINT_TYPE="all"  # Options: "static", "dynamic", "all"
```

When enabled, the system will:
- Fetch current OBP glossary and endpoint data on startup
- Compare with previously imported data using SHA-256 hashes
- Rebuild the database only if changes are detected
- Store hashes for future comparisons

### 3. Setting up the environment 
First you will need to rename the `.env.example` file to `.env` and change several parameters. You have options on which LLM provider you decide to use for the backend agent system. 
### Using different AI models
To use change the model used by opey set the environment variables:

```env
MODEL_PROVIDER="anthropic"
MODEL_NAME="claude-sonnet-4"
```
Just note that the provider must match the MODEL_NAME i.e. you cannot use MODEL_PROVDER="anthropic" and MODEL_NAME="gpt-4.1"

### Adding a new LLM
Not all LLMs are supported by default, they need to be manually added in the config.
If you want to add a new model, edit `MODEL_CONFIGS` in `./src/agent/utils/model_factory.py`

### Ollama (Run models locally)
This is only reccomended if you can run models on a decent size GPU. Trying to run on CPU will take ages, not run properly or even crash your computer.

[Install](https://ollama.com/download) Ollama on your machine. I.e. for linux:

`curl -fsSL https://ollama.com/install.sh | sh` 

Pull a model that you want (and that supports [tool calling](https://ollama.com/search?&c=tools)) from ollama using `ollama pull <model name>` we reccomend the latest llama model from Meta: `ollama pull llama3.2`

Then set
```
MODEL_PROVIDER='ollama'

MODEL_NAME="llama3.2"
```

### 4. Open Bank Project (OBP) credentials
In order for the agent to communicate with the Open Bank Project API, we need to set credentials in the env. First sign up and get an API key on your specific instance of OBP i.e. https://apisandbox.openbankproject.com/ (this should match the `OBP_BASE_URL` in the env). Then set:
```
OBP_USERNAME="your-obp-username"
OBP_PASSWORD="your-obp-password"
OBP_CONSUMER_KEY="your-obp-consumer-key"
```

## Running
Activate the poetry venv using `poetry shell` in the current directory

Run the backend agent with `python src/run_service.py`

In a separate terminal run the frontend streamlit app (within another poetry shell) with `streamlit run src/streamlit_app.py`

The best way to interact with the agent is through the streamlit app, but it also functions as a rest API whose docs can be found at `http://127.0.0.1:8000/docs`

## Experimental Evaluation System

Opey II includes a comprehensive evaluation system for testing and optimizing the retrieval component. This allows you to:
- Run parameter sweeps (batch size, k-value, retry thresholds)
- Export results to CSV for analysis
- Generate visualizations to find optimal configurations
- Test retrieval end-to-end with simple metrics

### Quick Evaluation

Test if your retrieval system is working correctly:
```bash
python scripts/run_retrieval_eval.py quick
```

### Find Optimal Batch Size

Run experiments to find the best batch size for your needs:
```bash
python src/evals/retrieval/experiment_runner.py --experiment batch_size
```

This generates CSV data and plots showing latency vs batch size, recall vs batch size, and helps identify the sweet spot.

See [docs/EXPERIMENTAL_EVALUATION.md](docs/EXPERIMENTAL_EVALUATION.md) for complete documentation.

## Langchain Tracing with Langsmith
If you want to have metrics and tracing for the agent from LangSmith. Obtain a [Langchain tracing API key](https://smith.langchain.com/) and set:
```
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_API_KEY="lsv2_pt_..."
LANGCHAIN_PROJECT="langchain-opey" # or whatever name you want
```

## Docker

To run using docker simply run `docker compose up` (you'll need to have the [docker compose plugin](https://docs.docker.com/compose/install/linux/))

### OBP API configuration

The following props are required in OBP API:
```
skip_consent_sca_for_consumer_id_pairs=[{ \
    "grantor_consumer_id": "<api explorer consumer id>",\
    "grantee_consumer_id": "<opey consumer id>" \
}]

# Make sure Opey has sufficient permissions to operate:
consumer_validation_method_for_consent=CONSUMER_KEY_VALUE
experimental_become_user_that_created_consent=true
```
Consumer IDs will be shown on consumer registration or via the "Get Consumers" endpoint.

### Running with a local OBP-API
In some instances (when developing mostly) you'll be trying to do this with a local instance of OBP i.e. running at `http://127.0.0.1:8080` on the host machine. 

In that case you'll need to change `OBP_BASE_URL` in the _environment variables_ to be your computer's IP address rather than localhost. 

First get your IP address, in linux this is 
```
ip a
```
replace `127.0.0.1` or `localhost` in your `OBP_BASE_URL` with your host machine's IP

```
OBP_BASE_URL="http://127.0.0.1:8080"
```
becomes 
```
OBP_BASE_URL="http://<your IP address>:8080"
```
i.e. 
```
OBP_BASE_URL="http://192.168.0.112:8080"
```

### Admin Client Configuration

Opey II includes an admin OBP client singleton for system-level operations. This is initialized automatically at startup if the required environment variables are present:

```env
OBP_USERNAME=admin@example.com
OBP_PASSWORD=secure_password
OBP_CONSUMER_KEY=your_consumer_key
OBP_BASE_URL=https://api.openbankproject.com
```

The admin client:
- Initializes once at app startup
- Provides a singleton instance accessible throughout the application
- Automatically verifies admin entitlements
- Handles authentication and token refresh centrally


## Logging Configuration

### Username Logging for OBP API Requests

Opey II automatically logs the username from consent JWTs when making requests to the OBP-API. This feature helps with monitoring and debugging by showing which user is making each API request.

The logging includes:
- Function name that created the log entry
- Username extracted from the consent JWT token (with explicit field identification)
- HTTP method (GET, POST, etc.)
- Full request URL

Example log output:
```
INFO - _extract_username_from_jwt says: User identifier extracted from JWT field 'email': john.doe@example.com
INFO - _async_request says: Making OBP API request - User identifier is: john.doe@example.com, Method: GET, URL: https://test.openbankproject.com/obp/v4.0.0/users/current
INFO - async_obp_get_requests says: OBP request successful (status: 200)
```

### Log Levels

- **INFO**: Shows function name, user identifier extraction details, and request details for each OBP API call
- **WARNING**: Shows available JWT fields when no user identifier can be found

### JWT User Identification Fields

The system attempts to extract user identifiers from these JWT fields in order (prioritizing human-readable identifiers):
1. `email`
2. `name`
3. `preferred_username`
4. `username`
5. `user_name` 
6. `login`
7. `sub`
8. `user_id`

The system will log which field was used for user identification:
```
INFO - _extract_username_from_jwt says: User identifier extracted from JWT field 'email': john.doe@example.com
INFO - _extract_username_from_jwt says: User identifier extracted from JWT field 'sub': 91be7e0b-bf6b-4476-8a89-75850a11313b
```

If none of these fields are found, the user identifier will be logged as 'unknown':
```
WARNING - _extract_username_from_jwt says: No user identifier found in JWT fields, using 'unknown'
```

### Debugging JWT Structure

When no user identifier can be found in the JWT, the system will log all available JWT fields to help with debugging. The system prioritizes human-readable identifiers like email addresses and display names over system identifiers like UUIDs.

### Function Name Prefixes

All log messages now include the function name that generated the log for easier debugging:

- `_extract_username_from_jwt says:` - JWT user identifier extraction logs
- `_async_request says:` - HTTP request execution logs  
- `async_obp_get_requests says:` - GET request specific logs
- `async_obp_requests says:` - General request method logs

## Service Configuration

### MCP Server Configuration

Opey II loads tools from external [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers. This allows you to extend Opey's capabilities without modifying the core codebase.

#### Configuration File

Create a `mcp_servers.json` file in the project root (or `src/` directory):

```json
{
  "servers": [
    {
      "name": "obp",
      "url": "http://localhost:8001/sse",
      "transport": "sse"
    },
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "transport": "stdio"
    }
  ]
}
```

Copy `mcp_servers.example.json` to `mcp_servers.json` and edit as needed.

You can also specify a custom path via environment variable:
```env
MCP_SERVERS_FILE=/path/to/my-mcp-config.json
```

#### Server Configuration Options

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier for the server |
| `transport` | Yes | Connection type: `"sse"`, `"http"`, `"streamable_http"`, or `"stdio"` |
| `url` | For sse/http | Server URL (e.g., `http://localhost:8001/sse`) |
| `command` | For stdio | Command to run (e.g., `"npx"`, `"python"`) |
| `args` | For stdio | Command arguments as array |
| `env` | No | Environment variables for stdio processes |
| `headers` | No | HTTP headers for sse/http (e.g., for auth) |
| `oauth` | No | OAuth 2.1 authentication configuration (see below) |

#### Transport Types

- **SSE (Server-Sent Events)**: For HTTP-based MCP servers using SSE streaming
- **HTTP**: For HTTP-based MCP servers using streamable HTTP
- **stdio**: For local process-based MCP servers (spawns a subprocess)

#### OAuth 2.1 Authentication with Dynamic Client Registration

For MCP servers that require OAuth authentication, Opey II supports OAuth 2.1 with Dynamic Client Registration (DCR). This provides automatic, secure authentication without manual client credential setup.

##### Simple OAuth Configuration (Development)

```json
{
  "name": "oauth-server",
  "url": "https://mcp-server.example.com/mcp",
  "transport": "streamable_http",
  "oauth": true
}
```

This uses default settings:
- In-memory token storage (**not suitable for production**)
- Default client name: "OBP-Opey MCP Client"
- Random callback port

##### Production OAuth Configuration (Redis Storage)

```json
{
  "name": "oauth-server",
  "url": "https://mcp-server.example.com/mcp",
  "transport": "http",
  "oauth": {
    "scopes": ["email", "profile", "openid"],
    "client_name": "OBP-Opey Production",
    "storage_type": "redis",
    "redis_key_prefix": "mcp:oauth:tokens"
  }
}
```

**Recommended for production** - Stores tokens in Redis with:
- Persistent storage across restarts
- Secure Redis authentication
- Automatic token expiration
- Multi-instance support

##### Alternative: Encrypted Disk Storage

```json
{
  "name": "oauth-server",
  "url": "https://mcp-server.example.com/mcp",
  "transport": "streamable_http",
  "oauth": {
    "storage_type": "encrypted_disk",
    "token_storage_path": "~/.local/share/obp-opey/oauth-tokens",
    "encryption_key_env": "MCP_TOKEN_ENCRYPTION_KEY"
  }
}
```

Requires encryption key in environment:
```bash
# Generate a new encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Set in .env
MCP_TOKEN_ENCRYPTION_KEY="your-generated-key-here"
```

##### OAuth Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `scopes` | `string[]` | `["email", "profile", "openid"]` | OAuth scopes to request |
| `client_name` | `string` | `"OBP-Opey MCP Client"` | Client name for DCR |
| `callback_port` | `number` | Random | Fixed port for OAuth callback |
| `storage_type` | `"memory"` \| `"redis"` \| `"encrypted_disk"` | `"memory"` | Token storage method |
| `redis_key_prefix` | `string` | `"mcp:oauth:tokens"` | Redis key prefix (redis only) |
| `token_storage_path` | `string` | - | Directory path (encrypted_disk only) |
| `encryption_key_env` | `string` | `"MCP_TOKEN_ENCRYPTION_KEY"` | Env var for encryption key (encrypted_disk only) |

##### OAuth Flow

When connecting to an OAuth-protected server:
1. **Discovery**: Auto-discovers OAuth endpoints via `/.well-known/oauth-authorization-server`
2. **Registration**: Dynamically registers client with the OAuth provider (RFC 7591)
3. **Authorization**: Opens browser for user login and consent
4. **Token Exchange**: Exchanges authorization code for access/refresh tokens (PKCE)
5. **Storage**: Securely stores tokens based on `storage_type`
6. **Refresh**: Automatically refreshes expired tokens

##### Dependencies

OAuth support requires optional dependencies:

```bash
# For OAuth support
pip install fastmcp

# For encrypted disk storage
pip install cryptography
```

If not installed, OAuth servers will be skipped with a warning.

#### Example: Multiple Servers with Different Auth Methods

```json
{
  "servers": [
    {
      "name": "obp",
      "url": "http://localhost:8001/sse",
      "transport": "sse"
    },
    {
      "name": "weather",
      "url": "http://localhost:8002/mcp",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer static-token-123"
      }
    },
    {
      "name": "secure-api",
      "url": "https://api.example.com/mcp",
      "transport": "streamable_http",
      "oauth": {
        "storage_type": "redis"
      }
    }
  ]
}
```

#### Notes

- If no config file is found, no MCP tools will be loaded
- Tools from all configured servers are combined and made available to the agent
- Server names must be unique across configurations
- Tools are loaded once at application startup

### Rate Limiting
Default rate limiting on the stream and invoke endpoints can be set with the environment variable `GLOBAL_RATE_LIMIT`

Visit https://limits.readthedocs.io/en/stable/quickstart.html#rate-limit-string-notation for information on what this value can be.
