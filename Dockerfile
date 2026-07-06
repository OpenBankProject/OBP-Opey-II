FROM python:3.12.7-bookworm AS builder

RUN pip install poetry==2.1.1 --no-cache-dir

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN touch README.md

RUN --mount=type=cache,target=$POETRY_CACHE_DIR poetry install --without dev --no-root

FROM python:3.12.7-slim-bookworm AS runtime

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY src ./src

# mcp_servers.json is gitignored (deployment-specific) so it is not baked into
# the image — mount it at /app/mcp_servers.json (see docker-compose.yml) or set
# MCP_SERVERS_FILE to a mounted path. Without it, Opey loads no MCP tools.

EXPOSE 5000

ENTRYPOINT ["python", "src/run_service.py"]