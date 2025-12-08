### EDGES
import os
from langchain_core.runnables import RunnableConfig
from dotenv import load_dotenv

load_dotenv()

# Default from env
DEFAULT_MAX_RETRIES = int(os.getenv("ENDPOINT_RETRIEVER_MAX_RETRIES", 2))


def decide_to_generate(state, config: RunnableConfig = None):
    """
    Determines whether to generate an answer, or re-generate a question.

    Args:
        state (dict): The current graph state
        config: LangGraph RunnableConfig with optional configurable.max_retries

    Returns:
        str: Binary decision for next node to call
    """

    print("---ASSESS GRADED DOCUMENTS---")
    relevant_documents = state["relevant_documents"]
    retry_query = state["retry_query"]
    
    configurable = (config or {}).get("configurable", {})
    max_retries = configurable.get("max_retries", DEFAULT_MAX_RETRIES)

    total_retries = state.get("total_retries", 0)
    print(f"Total retries: {total_retries}")
    print("Documents returned: \n", "\n".join(f"{doc.metadata["method"]} {doc.metadata["path"]} — operationId: {doc.metadata["operation_id"]}" for doc in relevant_documents))
    
    if retry_query and (total_retries < max_retries):
        # All documents have been filtered check_relevance
        # We will re-generate a new query
        print(
            "---DECISION: ALL DOCUMENTS ARE NOT RELEVANT TO QUESTION, TRANSFORM QUERY---"
        )
        return "transform_query"
    else:
        # We have relevant documents, so finish
        print("---DECISION: RETURN DOCUMENTS---")
        return "return_documents"