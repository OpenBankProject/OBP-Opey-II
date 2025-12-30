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
- Various docs in `docs/APPROVAL_SYSTEM_*.md`

## Migration completed

- `src/service/opey_session.py` ✅
- `src/agent/components/nodes.py` ✅
- `src/agent/components/states.py` ✅
- `src/agent/components/tools/__init__.py` ✅
