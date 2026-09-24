# Deprecated Files

These files are deprecated and can be deleted once dependent tests/scripts are updated.

## `src/agent/components/tools/` directory

| File | Replaced By | Notes |
|------|-------------|-------|
| `approval_manager.py` | `approval.py` | Complex multi-level approval manager replaced by simple `ApprovalStore` |
| `approval_models.py` | `approval.py` | Pattern-matching models replaced by simple `ApprovalScope`/`ApprovalRequest` |
| `tool_registry.py` | `mcp_integration.py` | Registry no longer needed - tools come from MCP servers |

## `src/agent/components/` directory

| File | Replaced By | Notes |
|------|-------------|-------|
| `tools.py` | MCP servers | Retrieval tools now provided by external MCP server |

## `src/agent/components/retrieval/` directory

| Directory | Replaced By | Notes |
|-----------|-------------|-------|
| `endpoint_retrieval/` | MCP server | Endpoint retrieval now handled by MCP server |
| `glossary_retrieval/` | MCP server | Glossary retrieval now handled by MCP server |

## Files with dependencies on deprecated code

These files import from deprecated modules and need updating:

- `test/agent/test_approval_system.py` - tests old approval system
- `scripts/demo_approval_system.py` - demo script for old system
- `src/agent/agent_test_graph.py` - imports old retrieval tools
- Various docs in `docs/archived/APPROVAL_SYSTEM_*.md`

## Approval system status (added 2026-09-22)

Worth stating plainly, because the `APPROVAL_SYSTEM_*.md` docs listed above read as though the
feature is live: **the human-in-the-loop approval path does not run at all.**

`approval.py` replaced the deprecated `approval_manager.py` / `approval_models.py` /
`tool_registry.py`, but the replacement is not reachable either. All five `OBP_API_MODE`
branches in `src/service/opey_session.py` (lines 163, 177, 187, 198, 211) pass
`.enable_human_review(False)`, so `human_review_node` is never added to the graph.
`create_supervised_opey_graph` (`src/agent/graph_builder.py:460`) is the only caller that
passes `True`, and nothing calls it.

Authorization is handled by the **OBP consent flow** — `consent_check_node`
(`src/agent/components/nodes.py:642`) and the roles carried by the consent JWT, enforced
server-side by OBP. See `../CONSENT_FLOW.md`. This is the intended design, not a regression:
the authority for "may this call proceed" belongs in OBP rather than in a client-side approval
store.

Still-live code that the deprecated docs may lead you to misread:

| Thing | Status |
|---|---|
| `interrupt()` | **Live** — used by the consent flow (`nodes.py:804`) and client-executed tools (`client_tools.py:72`). `INTERRUPT_FLOW_FIX.md` is still accurate. |
| `human_review_node` | Present in `nodes.py`, never added to a graph. |
| `ApprovalStore` (`approval.py`) | Constructed per session in `opey_session.py`, never consulted. |
| `approval_manager` config key | Vestigial: assigned at `streaming/stream_manager.py:307`, never used. |
| `operation_id` in `nodes.py` | **Live**, but it belongs to the consent flow now, not approvals. |

The eight stale `APPROVAL_SYSTEM_*.md` / `BATCH_APPROVAL_ARCHITECTURE.md` documents (now in `docs/archived/`) carry an
out-of-date banner as of 2026-09-22.

## Migration completed

- `src/service/opey_session.py` ✅
- `src/agent/components/nodes.py` ✅
- `src/agent/components/states.py` ✅
- `src/agent/components/tools/__init__.py` ✅
