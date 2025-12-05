import logging
from agent.components.retrieval.retriever_config import get_retriever
from agent.components.retrieval.endpoint_retrieval.components.chains import retrieval_grader
from agent.components.retrieval.glossary_retrieval.components.states import SelfRAGGraphState, OutputState, InputState

logger = logging.getLogger("agent.components.retrieval.glossary_retrieval")

glossary_retriever = get_retriever("obp_glossary", search_kwargs={"k": 8})


def deduplicate_documents(documents):
    """Remove duplicate documents based on document_id metadata."""
    seen = set()
    unique = []
    for doc in documents:
        doc_id = doc.metadata.get("document_id")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            unique.append(doc)
        elif not doc_id:
            unique.append(doc)
    return unique


async def retrieve_glossary(state):
    """
    Retrieve documents

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): New key added to state, documents, that contains retrieved documents
    """
    logging.info("---RETRIEVE ITEMS---")
    rewritten_question = state.get("rewritten_question", "")
    total_retries = state.get("total_retries", 0)
    
    if rewritten_question:
        question = state["rewritten_question"]
        total_retries += 1
    else:
        question = state["question"]
    # Retrieval
    documents = await glossary_retriever.ainvoke(question)
    # Deduplicate in case of duplicate entries in the vector store
    documents = deduplicate_documents(documents)
    return {"documents": documents, "total_retries": total_retries}

async def grade_documents_glossary(state):
    """
    Determines whether the retrieved documents are relevant to the question.

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): Updates documents key with only filtered relevant documents
    """

    logging.info("---CHECK DOCUMENT RELEVANCE TO QUESTION---")
    question = state["question"]
    documents = state["documents"]

    # Batch grade all documents in parallel
    grading_inputs = [{"question": question, "document": d.page_content} for d in documents]
    scores = await retrieval_grader.abatch(grading_inputs)

    filtered_docs = []
    for d, score in zip(documents, scores):
        grade = score.binary_score
        if grade == "yes":
            logging.info(f"{d.metadata['title']} [RELEVANT]")
            filtered_docs.append(d)
        else:
            logging.info(f"{d.metadata['title']} [NOT RELEVANT]")

    # If there are two or fewer relevant documents then retry query after rewriting question
    retry_threshold = 2
    retry_query = len(filtered_docs) <= retry_threshold

    return {"documents": documents, "relevant_documents": filtered_docs, "question": question, "retry_query": retry_query}
              
async def return_documents(state) -> OutputState:
    """Return the relevant documents"""
    logging.info("---RETRUN RELEVANT DOCUMENTS---")
    relevant_documents = state["relevant_documents"]
    return {"relevant_documents": relevant_documents}