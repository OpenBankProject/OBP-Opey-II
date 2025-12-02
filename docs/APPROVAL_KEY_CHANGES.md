# Approval Key System Changes

## Overview

Refactored the approval key system to be more generic and use `operation_id` for OBP API endpoints instead of `method:path`.

## Changes Made

### 1. Generic Tool Support (`nodes.py`)

**Before:**
```python
def _extract_operation(tool_args: Dict) -> str:
    """Extract operation identifier from tool args"""
    if "method" in tool_args and "path" in tool_args:
        return f"{tool_args['method']}:{tool_args['path']}"
    return "unknown"
```

**After:**
```python
def _extract_operation(tool_name: str, tool_args: Dict) -> str:
    """
    Extract operation identifier from tool args.
    
    For obp_requests tool, prioritizes operation_id if available,
    otherwise falls back to method:path.
    For other tools, uses generic descriptors or returns the tool name.
    """
    # OBP requests tool - use operation_id if available
    if tool_name == "obp_requests":
        if "operation_id" in tool_args and tool_args["operation_id"]:
            return tool_args["operation_id"]
        elif "method" in tool_args and "path" in tool_args:
            # Fallback for when operation_id isn't available
            return f"{tool_args['method']}:{tool_args['path']}"
        return "unknown_operation"
    
    # For other tools, try to extract a meaningful operation identifier
    if "operation" in tool_args:
        return tool_args["operation"]
    
    if "action" in tool_args:
        return tool_args["action"]
    
    # Fallback: use the tool name itself as the operation
    return tool_name
```

**Key improvements:**
- Now accepts `tool_name` parameter to make tool-specific decisions
- Prioritizes `operation_id` for `obp_requests` (the unique OBP endpoint identifier)
- Falls back gracefully to `method:path` if `operation_id` isn't available
- For non-API tools, uses generic fields like "operation" or "action"
- Ultimate fallback: uses tool name itself (approval is per-tool, not per-operation)

### 2. OBP Tool Updates (`obp.py`)

Added optional `operation_id` parameter to both OBP request methods:

```python
async def async_obp_get_requests(self, path: str, operation_id: str | None = None):
    """
    ...
    Args:
        path (str): The API endpoint path to send the request to.
        operation_id (str, optional): The OBP API operation ID for this endpoint (used for approval tracking).
    ...
    """

async def async_obp_requests(self, method: str, path: str, body: str, operation_id: str | None = None):
    """
    ...
    Args:
        method (str): The HTTP method to use for the request (e.g., 'GET', 'POST').
        path (str): The API endpoint path to send the request to.
        body (str): The JSON body to include in the request. If empty, no body is sent.
        operation_id (str, optional): The OBP API operation ID for this endpoint (used for approval tracking).
    ...
    """
```

**Note:** The agent should pass `operation_id` when it's available from endpoint retrieval. If not provided, the system falls back to `method:path`.

### 3. Updated Documentation (`states.py`)

Enhanced the documentation for approval key functions to reflect the new generic approach:

```python
def make_approval_key(tool_name: str, operation: str) -> str:
    """
    Create a serializable approval key from tool name and operation.
    Uses string format instead of tuple to avoid JSON serialization issues.
    
    Args:
        tool_name: Name of the tool (e.g., "obp_requests", "endpoint_retrieval_tool")
        operation: Operation identifier, which varies by tool:
            - For obp_requests: operationId (e.g., "OBPv4.0.0-getBank") or fallback to "METHOD:path"
            - For other tools: generic operation name or the tool name itself
    
    Returns:
        str: Approval key in format "tool_name:operation"
    """
```

### 4. All Call Sites Updated

Updated all 4 call sites in `nodes.py` to pass `tool_name`:
- `_categorize_tool_calls()` - line ~192
- `_build_approval_contexts()` - line ~246
- `_process_batch_approval_response()` - line ~320
- `_process_single_approval_response()` - line ~397

## Benefits

### 1. **More Meaningful Approval Keys**
- Before: `"obp_requests:GET:/obp/v5.1.0/banks/BANK_ID"` 
- After: `"obp_requests:OBPv5.1.0-getBankById"`

The `operation_id` is more stable and meaningful than path patterns with dynamic segments.

### 2. **Tool Agnostic**
The system no longer assumes all tools are HTTP API calls. It gracefully handles:
- API tools (with `operation_id`, `method`, `path`)
- Action-based tools (with `action` field)
- Generic tools (falls back to tool name)

### 3. **Backward Compatible**
If `operation_id` isn't provided, the system falls back to `method:path`, so existing behavior is preserved.

### 4. **Better Approval Granularity**
Using `operation_id` allows users to approve specific operations (e.g., "get bank details") rather than broad patterns (e.g., "all GET requests").

## Migration Path

### For Agent Developers
When the agent calls `obp_requests`, it should pass `operation_id` from the endpoint retrieval context:

```python
# Retrieve endpoint documentation
endpoint_docs = endpoint_retrieval_tool.invoke(query)

# Extract operation_id from the documentation
operation_id = endpoint_docs[0]["operation_id"]

# Call OBP API with operation_id for better approval tracking
result = obp_requests(
    method="GET",
    path="/obp/v5.1.0/banks/BANK_ID",
    body="",
    operation_id=operation_id  # <-- Pass this for granular approvals
)
```

### For Tool Developers
When creating new tools that should support per-operation approvals:

1. Include an `operation`, `action`, or similar field in tool arguments
2. Or rely on the fallback (tool name) for per-tool approvals

Example:
```python
@tool
def custom_tool(action: str, data: dict):
    """
    Custom tool with action-based operations.
    
    Args:
        action: Operation to perform (e.g., "create", "update", "delete")
        data: Data to process
    """
    # The approval system will use "action" as the operation identifier
    pass
```

## Testing

Existing tests in `test_approval_system.py` remain valid as the core key functions haven't changed. The `operation` parameter now varies by tool type, which is transparent to the key system.

## Future Enhancements

1. **Automatic operation_id injection**: Modify the agent's tool-calling logic to automatically include `operation_id` when available from retrieval context
2. **Pattern-based approvals**: Allow approvals for patterns like "OBPv5.1.0-*Bank*" (all bank-related operations)
3. **Operation metadata**: Store additional context about operations (description, tags) for richer approval UI
