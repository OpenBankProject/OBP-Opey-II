# Opey II - AI Agent Technical Summary

## Executive Overview

**Opey II** is a production-grade, LangGraph-based agentic AI system designed specifically for the **Open Bank Project (OBP) API**. It functions as an intelligent assistant that enables natural language interaction with complex banking APIs, featuring autonomous task completion, multi-modal retrieval, human-in-the-loop safety mechanisms, and comprehensive observability.

## Architecture Overview

### Core Framework: LangGraph State Machine

Built on **LangGraph** (LangChain's graph-based orchestration framework), Opey implements a sophisticated state machine architecture:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   START     │────▶│  Opey Agent  │────▶│   Tools     │
└─────────────┘     └──────────────┘     └─────────────┘
                           │                     │
                           │                     ▼
                           │              ┌─────────────┐
                           │              │  Sanitize   │
                           │              └─────────────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────────┐     ┌─────────────┐
                    │ Summarize    │◀────│    Opey     │
                    └──────────────┘     └─────────────┘
                           │
                           ▼
                        ┌─────┐
                        │ END │
                        └─────┘
```

**Key Components:**
- **OpeyGraphState**: Custom state schema with conversation history, tool messages, summaries, and token tracking
- **Checkpointer**: Persistent conversation state (MemorySaver for local, Redis for distributed)
- **Tool Nodes**: Modular execution units for retrieval and API operations
- **Conditional Edges**: Dynamic routing based on tool calls, token limits, and approval requirements

## Component Deep Dive

### 1. Multi-Modal Retrieval System (RAG)

Opey implements **dual RAG pipelines** for comprehensive API documentation retrieval:

**Endpoint Retrieval Pipeline:**
- **Purpose**: Search through Swagger/OpenAPI specifications for API endpoints
- **Vector Store**: Embeddings of endpoint schemas (path, method, parameters, responses)
- **Query Optimization**: LLM-powered query reformulation with endpoint tag injection
- **Tags**: Pre-defined categories (Transaction, Account, Entitlement, etc.) enhance retrieval accuracy

**Glossary Retrieval Pipeline:**
- **Purpose**: Search technical documentation and banking terminology
- **Vector Store**: Embeddings of glossary definitions and conceptual documentation
- **Context Enrichment**: Provides domain knowledge for complex banking concepts

**Retrieval Graph Architecture:**
```python
query → formulate_query → retrieve_documents → grade_documents → 
  decision → [relevant_docs → generate_answer | 
              not_relevant → transform_query → web_search]
```

**Evaluation Framework:**
- Parameter sweep experiments (batch size: 3-20, k-value: 5-50, retry thresholds: 0-5)
- CSV export of metrics (precision, recall, latency P50/P90/P99, hit rate)
- Visualization tools for identifying optimal configurations
- Combined scoring: 70% recall + 30% speed for sweet spot analysis

### 2. Tool System with Approval Architecture

**Three-Layer Design:**

**Layer 1: ToolRegistry (Declarative Rules)**
```python
@dataclass
class ToolApprovalMetadata:
    tool_name: str
    requires_auth: bool
    default_risk_level: RiskLevel  # SAFE | MODERATE | DANGEROUS | CRITICAL
    patterns: List[ApprovalPattern]  # Method/path-based rules
    custom_approval_checker: Optional[Callable]
    custom_context_builder: Optional[Callable]
```

**Layer 2: ApprovalManager (State Management)**
- Multi-level approval persistence (once/session/user/workspace)
- TTL-based expiration for time-limited approvals
- Pre-approval checking to minimize interrupts
- Batch approval support for similar operations

**Layer 3: Human Review Node (Orchestration)**
- Intelligent interrupt decision (only when truly needed)
- Rich approval context with operation summary, risk assessment, affected resources
- Session history analysis for similar operations
- Dynamic interrupt() calls (not compile-time interrupt_before)

**Risk-Based Routing:**
- **SAFE**: Auto-approve (read-only operations)
- **MODERATE**: Session-level approval (batch operations)
- **DANGEROUS**: User confirmation required (write operations)
- **CRITICAL**: Explicit approval with audit trail (admin operations)

### 3. OBP API Integration

**OBPClient Features:**
- **Async HTTP client** with aiohttp for concurrent operations
- **OAuth 1.0a authentication** via BaseAuth abstraction
- **Consent JWT handling**: User impersonation with consent tokens
- **Request/response logging** with user identifier extraction
- **JSON serialization safeguards** to prevent corruption (ANK bug fix)

**Admin Client Singleton:**
- System-level operations with admin credentials
- Automatic entitlement verification on startup
- Centralized token refresh and authentication
- Used for operations requiring elevated privileges

**Consent JWT Architecture:**
```
Consent-JWT Header → JWT Parsing → Field Prioritization:
  1. email (preferred for human identification)
  2. name
  3. preferred_username
  4. username
  5. sub (fallback to system ID)
→ User Identifier Extraction → Request Logging
```

### 4. Agentic Behaviors & System Prompt

**Core Philosophy: "Task Follow Through"**

The system prompt embeds sophisticated behavioral guidelines:

```
"Task Follow Through: If you reach a snag with a tool, like not having 
the right roles or permissions, or having invalid input, reuse the tools 
to try to complete the task fully. Follow through on the tasks you start 
until they are fully completed. Do not wait for the user to prompt you 
to continue a task."
```

**Key Behavioral Patterns:**
1. **Tool-First Approach**: Prioritize tool usage over knowledge recall to minimize hallucination
2. **Self-Correction**: Automatically assign missing entitlements via API calls
3. **Proactive Verification**: Use endpoint retrieval before answering to ensure accuracy
4. **Transparent Errors**: Acknowledge mistakes and correct using tools
5. **No Hallucination**: Only use information provided by tools, never assume

**Conversation Management:**
- **Token Counting**: Track cumulative tokens per conversation
- **Automatic Summarization**: Triggered when approaching model limits
- **Summary Injection**: Recent context + summary for long conversations
- **Graceful Degradation**: Maintain coherence in extended sessions

## Builder Pattern & Configuration

**OpeyAgentGraphBuilder** enables flexible agent composition:

```python
OpeyAgentGraphBuilder()
    .with_tools([endpoint_retrieval_tool, glossary_retrieval_tool, obp_client_tool])
    .with_model("claude-sonnet-4", temperature=0.7)
    .enable_human_review(True)
    .add_to_system_prompt("Additional safety guidelines...")
    .with_checkpointer(SqliteSaver("./checkpoints.db"))
    .build()
```

**Configuration Options:**
- **Tools**: Any LangChain BaseTool or sub-graph as tool
- **Models**: Provider-agnostic (Anthropic, OpenAI, Ollama)
- **Checkpointer**: MemorySaver (dev) or persistent (prod)
- **Human Review**: Enable/disable approval workflow
- **Summarization**: Toggle conversation compression
- **System Prompt**: Base + dynamic additions (with injection warnings)

## Service Architecture

### REST API with Streaming (FastAPI)

**Endpoints:**
- `POST /invoke` - Synchronous agent invocation (returns full response)
- `POST /stream` - Server-Sent Events streaming (real-time tokens)
- `POST /submit_approval` - Human-in-the-loop approval submission
- `GET /user/consent` - OBP consent JWT information
- `GET /status` - Health check endpoint

**Streaming Event Architecture:**
```
LangGraph Events → Event Processors → Stream Events → SSE

Processors:
├── TokenEventProcessor      (agent tokens, tool outputs)
├── ToolEventProcessor       (tool start/complete/error)
├── HumanReviewProcessor     (approval requests)
├── MetadataProcessor        (run IDs, checkpoints)
└── EndEventProcessor        (conversation end)
```

**Session Management:**
- Cookie-based sessions with FastAPI SessionMiddleware
- Redis-backed storage for distributed deployments
- Session data includes: user_id, consent_jwt, thread_id, metadata
- Automatic cleanup and expiration

### Frontend Interfaces

**1. Streamlit Chat App:**
- Interactive conversational interface
- Real-time streaming display
- Approval UI for human-in-the-loop
- Session persistence and history

**2. REST API (OpenAPI):**
- Auto-generated documentation at `/docs`
- Swagger UI for testing
- Request/response schemas with Pydantic

**3. User Consent Dashboard:**
- JWT token visualization (masked for security)
- Consent claims display (email, name, issuer, expiry)
- Session information and authentication status

## Model Flexibility

**Provider-Agnostic Design via ModelFactory:**

```python
MODEL_CONFIGS = {
    "anthropic": {
        "small": "claude-3-haiku-20240307",
        "medium": "claude-3-5-sonnet-20241022", 
        "large": "claude-3-opus-20240229"
    },
    "openai": {
        "small": "gpt-4o-mini",
        "medium": "gpt-4o",
        "large": "o1"
    },
    "ollama": {
        "small": "llama3.2",
        "medium": "llama3.2",
        "large": "llama3.2:70b"
    }
}
```

**Configuration:**
```env
MODEL_PROVIDER="anthropic"
MODEL_NAME="claude-sonnet-4"  # or size: "medium"
TEMPERATURE=0.7
```

**Adding New Providers:**
1. Add to `MODEL_CONFIGS` in `model_factory.py`
2. Install provider's LangChain integration
3. Update environment configuration

## Advanced Features

### Token Management & Cost Tracking

**Token Counting:**
- Uses `tiktoken` for accurate token estimation
- Per-message and cumulative tracking
- Model-specific encoding (cl100k_base for GPT, etc.)
- Stored in graph state for persistence

**Conversation Summarization:**
```
Token Threshold Reached → Extract Recent Messages → 
  LLM Summarization → Replace History with Summary + Recent Context
```

**Benefits:**
- Maintain long conversations within model limits
- Reduce API costs for extended sessions
- Preserve conversation coherence

### Evaluation & Optimization System

**Quick Evaluation:**
```bash
python scripts/run_retrieval_eval.py quick
# Output: Pass/fail on hit rate (>70%), precision (>0.8), latency (<2s)
```

**Parameter Sweeps:**
```bash
python src/evals/retrieval/experiment_runner.py --experiment batch_size
# Tests: [3, 5, 8, 10, 15]
# Outputs: CSV data + 4-panel visualization
```

**Metrics Tracked:**
- **Hit Rate**: % queries with ≥1 relevant document
- **Precision**: Relevant docs / total retrieved docs
- **Recall**: Relevant docs retrieved / total relevant docs
- **Latency**: P50, P90, P99 response times
- **Retries**: Number of reformulation attempts

**Visualization:**
1. Latency vs Batch Size (P50/P90/Mean)
2. Precision/Recall/Hit Rate vs Batch Size
3. Latency vs Recall Trade-off Scatter
4. Combined Score (70% recall + 30% speed) with optimal point marked

### Observability & Debugging

**LangSmith Integration:**
```env
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_API_KEY="lsv2_pt_..."
LANGCHAIN_PROJECT="opey-production"
```

**Benefits:**
- Full trace visualization of agent reasoning
- Tool call inspection with inputs/outputs
- Error tracking and debugging
- Performance metrics and bottleneck identification

**Structured Logging:**
```python
# Function-level prefixes for easy debugging
"_extract_username_from_jwt says: User identifier extracted from JWT field 'email'"
"_async_request says: Making OBP API request - Method: GET, URL: ..."
"async_obp_get_requests says: OBP request successful (status: 200)"
```

**Log Levels:**
- **DEBUG**: JWT analysis, headers, full API requests
- **INFO**: Request/response summaries, user actions
- **WARNING**: Missing fields, fallback behaviors
- **ERROR**: API failures, authentication issues

## Production Considerations

### Security

**Authentication & Authorization:**
- OAuth 1.0a for OBP API access
- Consent JWT validation with field prioritization
- Consumer key-based authentication
- Skip-SCA configuration for trusted consumer pairs

**Data Protection:**
- JWT token masking in logs (first 20 + last 10 chars)
- No password exposure in responses
- Session-based access control
- CORS configuration for frontend domains

**Prompt Injection Prevention:**
```python
# WARNING in code:
"Do not expose add_to_system_prompt to end users as it may lead 
to prompt injection attacks."
# TODO: LlamaFirewall integration for sanitization
```

### Scalability

**Async Architecture:**
- Full async/await throughout stack
- aiohttp for concurrent HTTP requests
- Async LangChain LCEL chains
- Non-blocking tool execution

**Horizontal Scaling:**
- Redis-backed session storage
- Stateless API design (state in checkpointer)
- Docker Compose for multi-container deployment
- Load balancer ready (sticky sessions for WebSocket)

**Database Management:**
- Vector DB population on startup
- SHA-256 hash comparison for change detection
- Automatic rebuilds only when necessary
- Support for static/dynamic/all endpoint types

### Reliability

**Error Handling:**
- Graceful degradation on tool failures
- Retry logic with exponential backoff
- Transparent error communication to users
- Fallback responses for serialization issues

**Health Monitoring:**
- `/status` endpoint for uptime checks
- Automatic admin entitlement verification
- Database connectivity validation
- Model availability checks

**Rate Limiting:**
```env
GLOBAL_RATE_LIMIT="10/minute"  # per IP address
```
- Configurable per-endpoint throttling
- Uses `slowapi` with Redis backend
- Protects against API abuse

### Deployment

**Docker Compose:**
```yaml
services:
  opey-service:
    build: .
    environment:
      - OBP_BASE_URL
      - MODEL_PROVIDER
      - REDIS_URL
    volumes:
      - ./checkpoints.db:/app/checkpoints.db
      - ./src/data:/app/src/data
```

**Environment Configuration:**
```env
# LLM
MODEL_PROVIDER="anthropic"
MODEL_NAME="claude-sonnet-4"

# OBP API
OBP_BASE_URL="https://api.openbankproject.com"
OBP_USERNAME="admin@example.com"
OBP_PASSWORD="secure_password"
OBP_CONSUMER_KEY="your_consumer_key"

# Database
UPDATE_DATABASE_ON_STARTUP="true"
UPDATE_DATABASE_ENDPOINT_TYPE="all"

# Monitoring
LANGCHAIN_TRACING_V2="true"
LOG_LEVEL="INFO"

# Service
GLOBAL_RATE_LIMIT="10/minute"
PORT=5000
```

## Use Cases & Applications

### Primary Use Case: Banking API Navigation

**Problem:** Banking APIs are complex with hundreds of endpoints, strict authentication requirements, and domain-specific terminology.

**Solution:** Opey provides natural language interface that:
1. Understands user intent ("Show me all accounts for user X")
2. Retrieves relevant endpoint documentation
3. Constructs correct API calls with authentication
4. Handles errors and retries automatically
5. Presents results in user-friendly format

### Example Interactions

**Account Information:**
```
User: "Show me all accounts for user john@example.com"
Opey: [retrieves endpoints] → [calls /users/current/accounts] → 
      [formats response] "John has 3 accounts: Checking ($5,234), 
      Savings ($12,000), Credit Card (-$342)"
```

**Permission Management:**
```
User: "Create a new role called 'AccountManager'"
Opey: [attempts POST /roles] → [receives 403: missing entitlement] → 
      [retrieves entitlement endpoint] → [assigns entitlement to self] → 
      [retries role creation] → "Success! Role 'AccountManager' created."
```

**Documentation Search:**
```
User: "What's a dynamic entity?"
Opey: [retrieves glossary] → "A dynamic entity in OBP is a flexible 
      data structure that can be customized per bank..."
```

## Philosophical Design Principles

### 1. Autonomous Task Completion
Agents should complete tasks end-to-end without constant user prompting. If permission is missing, get it. If information is needed, fetch it.

### 2. Tool-First, Knowledge-Second
Prefer retrieving fresh information via tools over relying on training data to minimize hallucination risk.

### 3. Transparent Operation
When errors occur, explain them clearly and show corrective actions being taken.

### 4. Safety Through Approval, Not Restriction
Allow powerful operations but gate them with intelligent approval systems rather than limiting agent capabilities.

### 5. Declarative Over Imperative
Use declarative configurations (ToolRegistry, ApprovalPatterns) rather than scattered conditional logic for maintainability.

## Performance Characteristics

**Latency (typical):**
- Simple query (cached retrieval): 1-2s
- Complex query (multi-tool): 3-5s
- With human approval: 10s-60s (depends on user)
- Long conversation (with summarization): +2-3s overhead

**Throughput:**
- Concurrent requests: Limited by rate limiting (default 10/min)
- Streaming: Near real-time token delivery (<100ms per chunk)
- Vector DB queries: <500ms for most retrievals

**Evaluation Benchmarks:**
- Quick eval (30 queries): ~30 seconds
- Full batch size sweep (5 configs): 2-5 minutes
- Hit rate target: >70%
- Precision target: >0.8
- Latency target: P99 < 2000ms

## Future Enhancements

**Planned:**
- MCP (Model Context Protocol) tool support
- Multi-agent collaboration (specialist agents for different banking domains)
- Advanced prompt injection defense (LlamaFirewall integration)
- Database storage for evaluation historical results
- Web dashboard for real-time monitoring

**Potential:**
- Voice interface integration
- Multi-language support
- Custom fine-tuned models for banking domain
- A/B testing framework for prompt optimization
- Automated regression testing for API changes

## Getting Started

**Quick Start (Local Development):**
```bash
# Install dependencies
poetry install

# Create vector database
mkdir src/data
python src/database/populate_vector_db.py

# Configure environment
cp .env.example .env
# Edit .env with your API keys and OBP credentials

# Run service
poetry shell
python src/run_service.py

# Run frontend (separate terminal)
streamlit run src/streamlit_app.py
```

**Quick Start (Docker):**
```bash
# Configure environment
cp .env.example .env
# Edit .env with your configuration

# Build and run
docker compose up
```

**Access:**
- Streamlit UI: http://localhost:8501
- REST API: http://localhost:5000
- API Docs: http://localhost:5000/docs

## Key Takeaways for AI Agent Practitioners

1. **LangGraph is powerful for complex agent workflows** - State machines with conditional routing provide fine-grained control over agent behavior

2. **Human-in-the-loop requires intelligent design** - Don't interrupt unnecessarily; check pre-approvals and batch similar operations

3. **RAG for domain knowledge is essential** - Banking APIs have too many endpoints to fit in context; retrieval is mandatory

4. **Builder patterns enable flexibility** - Allow easy configuration changes without modifying core agent logic

5. **Observability is not optional** - LangSmith, structured logging, and evaluation frameworks are necessary for production systems

6. **Tool systems need declarative metadata** - Separate approval rules from execution logic for maintainability

7. **Async everywhere for production** - Non-blocking I/O is critical for handling concurrent conversations

8. **Evaluation drives optimization** - Systematic testing with metrics reveals improvement opportunities

---

**Project**: Open Bank Project - Opey II  
**Framework**: LangGraph (LangChain)  
**Language**: Python 3.11+  
**License**: AGPL-3.0  
**Repository**: OBP-Opey-II  
**Documentation**: See `/docs` directory for detailed guides
