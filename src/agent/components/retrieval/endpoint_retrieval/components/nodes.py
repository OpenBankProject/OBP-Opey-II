import os
import json
import re

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from typing import List, Optional
from agent.components.retrieval.endpoint_retrieval.components.states import OutputState
from agent.components.retrieval.retriever_config import get_retriever
from agent.components.retrieval.endpoint_retrieval.components.chains import retrieval_grader, endpoint_question_rewriter
from database.document_schemas import EndpointDocumentSchema
from dotenv import load_dotenv

load_dotenv()

# Default configuration from environment variables
DEFAULT_BATCH_SIZE = int(os.getenv("ENDPOINT_RETRIEVER_BATCH_SIZE", "5"))
DEFAULT_RETRY_THRESHOLD = int(os.getenv("ENDPOINT_RETRIEVER_RETRY_THRESHOLD", "2"))
DEFAULT_MAX_RETRIES = int(os.getenv("ENDPOINT_RETRIEVER_MAX_RETRIES", "2"))
# Enable compact grading format by default (significant token savings)
DEFAULT_USE_COMPACT_GRADING = os.getenv("ENDPOINT_RETRIEVER_COMPACT_GRADING", "true").lower() == "true"


def get_retrieval_config(config: Optional[RunnableConfig]) -> tuple[int, int, int, bool]:
    """Extract retrieval config from RunnableConfig or use defaults.
    
    Config can be passed via: graph.ainvoke(input, config={"configurable": {"batch_size": 10}})
    """
    configurable = (config or {}).get("configurable", {})
    return (
        configurable.get("batch_size", DEFAULT_BATCH_SIZE),
        configurable.get("retry_threshold", DEFAULT_RETRY_THRESHOLD),
        configurable.get("max_retries", DEFAULT_MAX_RETRIES),
        configurable.get("use_compact_grading", DEFAULT_USE_COMPACT_GRADING),
    )


# Cache retrievers by batch_size to avoid recreating them
_retriever_cache: dict[int, any] = {}


def get_endpoint_retriever(batch_size: int):
    """Get or create a retriever with the specified batch size."""
    if batch_size not in _retriever_cache:
        _retriever_cache[batch_size] = get_retriever(
            collection_name="obp_endpoints",
            search_kwargs={"k": batch_size}
        )
    return _retriever_cache[batch_size]


def deduplicate_documents(documents: List[Document]) -> List[Document]:
    """Remove duplicate documents based on document_id metadata."""
    seen = set()
    unique = []
    for doc in documents:
        doc_id = doc.metadata.get("document_id")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            unique.append(doc)
        elif not doc_id:
            # Keep documents without document_id (shouldn't happen with proper schema)
            unique.append(doc)
    return unique


def get_compact_grading_content(doc: Document) -> str:
    """
    Extract compact content for LLM grading to reduce token usage.
    
    Falls back to full content if compact extraction fails.
    """
    try:
        schema = EndpointDocumentSchema.from_document(doc.page_content, doc.metadata)
        return schema.to_grading_content()
    except Exception:
        # Fallback: use metadata + truncated content
        meta = doc.metadata
        parts = [
            f"{meta.get('method', '')} {meta.get('path', '')}",
            f"Summary: {meta.get('summary', '')}" if meta.get('summary') else "",
            f"Tags: {meta.get('tags', '')}" if meta.get('tags') else "",
        ]
        compact = "\n".join(p for p in parts if p)
        return compact if compact.strip() else doc.page_content[:500]


async def retrieve_endpoints(state, config: RunnableConfig = None):
    """
    Retrieve documents

    Args:
        state (dict): The current graph state
        config: LangGraph RunnableConfig with optional configurable.batch_size

    Returns:
        state (dict): New key added to state, documents, that contains retrieved documents
    """
    print("---RETRIEVE ENDPOINTS---")
    batch_size, _, _, _ = get_retrieval_config(config)
    retriever = get_endpoint_retriever(batch_size)
    
    rewritten_question = state.get("rewritten_question", "")
    total_retries = state.get("total_retries", 0)

    if rewritten_question:
        question = state["rewritten_question"]
        total_retries += 1
    else:
        question = state["question"]
    # Retrieval
    documents = await retriever.ainvoke(question)
    # Deduplicate in case of duplicate entries in the vector store
    documents = deduplicate_documents(documents)
    return {"documents": documents, "total_retries": total_retries}


async def return_documents(state) -> OutputState:
    """Return the relevant documents"""
    print("---RETRUN RELEVANT DOCUMENTS---")
    relevant_documents: List[Document] = state["relevant_documents"]

    output_docs = []

    for doc in relevant_documents:
        output_docs.append(
            {
                "method": doc.metadata["method"],
                "path": doc.metadata["path"],
                "operation_id": doc.metadata["operation_id"],
                "documentation": json.loads(doc.page_content),
            }
        )


    return {"output_documents": output_docs}


async def grade_documents(state, config: RunnableConfig = None):
    """
    Determines whether the retrieved documents are relevant to the question.

    Args:
        state (dict): The current graph state
        config: LangGraph RunnableConfig with optional configurable.retry_threshold

    Returns:
        state (dict): Updates documents key with only filtered relevant documents
    """

    print("---CHECK DOCUMENT RELEVANCE TO QUESTION---")
    _, retry_threshold, _, use_compact_grading = get_retrieval_config(config)
    
    question = state["question"]
    documents = state["documents"]

    # Build grading inputs - use compact format to reduce token usage
    if use_compact_grading:
        grading_inputs = [
            {"question": question, "document": get_compact_grading_content(d)} 
            for d in documents
        ]
    else:
        grading_inputs = [
            {"question": question, "document": d.page_content} 
            for d in documents
        ]

    # Batch grade all documents in parallel
    scores = await retrieval_grader.abatch(grading_inputs)

    filtered_docs = []
    for d, score in zip(documents, scores):
        grade = score.binary_score
        if grade == "yes":
            print(f"{d.metadata['method']} - {d.metadata['path']}", " [RELEVANT]")
            filtered_docs.append(d)
        else:
            print(f"{d.metadata['method']} - {d.metadata['path']}", " [NOT RELEVANT]")

    # If there are less documents than the threshold then retry query after rewriting question
    retry_query = len(filtered_docs) < retry_threshold

    return {"documents": documents, "relevant_documents": filtered_docs, "question": question, "retry_query": retry_query}


async def transform_query(state):
    """
    Transform the query to produce a better question.

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): Updates question key with a re-phrased question
    """

    print("---TRANSFORM QUERY---")
    question = state["question"]
    documents = state["documents"]
    total_retries = state.get("total_retries", 0)
    # Re-write question
    better_question = await endpoint_question_rewriter.ainvoke({"question": question})
    print(f"New query: \n{better_question}\n")
    return {"documents": documents, "rewritten_question": better_question}
