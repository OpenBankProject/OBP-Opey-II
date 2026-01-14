from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Global checkpointer dictionary
checkpointers = {}

def get_global_checkpointer() -> AsyncSqliteSaver:
    """
    Get the checkpointer for the app.
    """
    return checkpointers['aiosql']