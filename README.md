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
### Rate Limiting
Default rate limiting on the stream and invoke endpoints can be set with the environment variable `GLOBAL_RATE_LIMIT`

Visit https://limits.readthedocs.io/en/stable/quickstart.html#rate-limit-string-notation for information on what this value can be.
