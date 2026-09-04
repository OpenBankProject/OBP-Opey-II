# Prompt Configuration

Opey's system prompt (its "personality" plus tool-usage guidance) can be customised
per deployment without touching the code. There are two prompts:

- **Main system prompt** — the whole personality and behaviour. The shipped default
  lives in `src/agent/components/prompts/opey_system.prompt.yaml` and is baked into
  the Docker image.
- **Supplementary prompt** — optional deployment/project-specific hints **appended
  after** the main prompt (e.g. dynamic-entity guidance for the OGCR project).
  Prefer this over replacing the main prompt: the main prompt evolves in git, and a
  copied override silently goes stale.

## Environment variables

Resolution order for each prompt (first hit wins):

| Prompt        | 1. File variable                 | 2. Inline variable          | 3. Default          |
|---------------|----------------------------------|-----------------------------|---------------------|
| Main          | `OPEY_SYSTEM_PROMPT_FILE`        | `OPEY_SYSTEM_PROMPT`        | bundled YAML prompt |
| Supplementary | `OPEY_SUPPLEMENTARY_PROMPT_FILE` | `OPEY_SUPPLEMENTARY_PROMPT` | nothing appended    |

The `*_FILE` variables hold a **path to a plain text file**; the inline variables hold
the prompt text itself. If a `*_FILE` path is missing, unreadable, or empty, Opey logs
a warning and falls back to the inline variable (then the default) instead of crashing.

Notes:

- The supplementary prompt may freely contain JSON examples — `{` and `}` are escaped
  automatically before the prompt is templated.
- Multi-line inline values work in `.env` files (keep real newlines inside the double
  quotes); see `.env.example`. For anything longer than a few lines, prefer a file.

## Local / docker-compose

Copy the committed example and edit it:

```bash
cp opey_supplementary_prompt.example.md opey_supplementary_prompt.local.md
```

`opey_supplementary_prompt.local.md` (and `opey_system_prompt.local.md`) are
gitignored, like `mcp_servers.json`. Then in `.env`:

```bash
OPEY_SUPPLEMENTARY_PROMPT_FILE="./opey_supplementary_prompt.local.md"
```

For docker-compose, also mount the file into the container (same pattern as the
existing `mcp_servers.json` mount in `docker-compose.yml`):

```yaml
    volumes:
      - ./opey_supplementary_prompt.local.md:/app/opey_supplementary_prompt.local.md:ro
```

## Kubernetes

Put the prompt in a ConfigMap, mount it as a file, and point the env var at the
mount path:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opey-prompts
data:
  supplementary_prompt.md: |
    OGCR project context:
    - This instance makes heavy use of dynamic entities (system-level Dynamic Entities on OBP).
    - When the user mentions carbon credits, projects or registries, look for the matching
      dynamic entity endpoints (e.g. /obp/dynamic-entity/...) before falling back to core endpoints.
    - Example entity record: {"project_id": "OGCR-001", "status": "issued"}
    - Prefer asking the user which registry they mean if more than one is available.
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: opey
spec:
  template:
    spec:
      containers:
        - name: opey
          env:
            - name: OPEY_SUPPLEMENTARY_PROMPT_FILE
              value: /etc/opey/prompts/supplementary_prompt.md
          volumeMounts:
            - name: prompts
              mountPath: /etc/opey/prompts
              readOnly: true
      volumes:
        - name: prompts
          configMap:
            name: opey-prompts
```

To replace the main prompt instead, add a second key (e.g. `system_prompt.md`) to the
same ConfigMap and set `OPEY_SYSTEM_PROMPT_FILE=/etc/opey/prompts/system_prompt.md`.

Why files + ConfigMap rather than an inline env var:

- **No quoting pain** — ConfigMap `data` takes multi-line YAML block text verbatim:
  no `\n` escapes, no shell quoting, JSON examples work as-is.
- **Prompt updates without rebuilding the image** — edit the ConfigMap and
  `kubectl rollout restart deployment/opey`. (The prompt is read once at agent
  startup, so a restart is required; the file mount itself updates in place.)
- **Per-environment personalities from one image** — e.g. the OGCR cluster and a
  vanilla OBP cluster run the same image with different ConfigMaps.
- **Graceful failure** — a missing mount logs a warning and Opey runs with the
  bundled default prompt.

## Where this is implemented

- `src/agent/graph_builder.py` — `_prompt_from_env()` and `OpeyAgentGraphBuilder.reset()`.
- `src/agent/components/chains.py` — loads the bundled YAML default.
