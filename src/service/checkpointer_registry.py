import os
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Global checkpointer dictionary
checkpointers = {}

def get_global_checkpointer() -> BaseCheckpointSaver:
    """
    Get the checkpointer for the app based on CHECKPOINTER_TYPE env var.
    
    Returns:
        BaseCheckpointSaver: The configured checkpointer (OBP or SQLite)
    """
    checkpointer_type = os.getenv('CHECKPOINTER_TYPE', 'aiosql')
    
    if checkpointer_type == 'obp' and 'obp' in checkpointers:
        return checkpointers['obp']
    
    # Default to SQLite
    return checkpointers['aiosql']