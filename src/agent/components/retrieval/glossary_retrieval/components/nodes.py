from agent.components.retrieval.retriever_config import setup_chroma_vector_store, setup_retriever
from agent.components.retrieval.endpoint_retrieval.components.chains import retrieval_grader
from agent.components.retrieval.glossary_retrieval.components.states import SelfRAGGraphState, OutputState, InputState

try:
    glossary_vector_store = setup_chroma_vector_store("obp_glossary")
except:
    print("Glossary vector store not found, check configuration")

glossary_retriever = setup_retriever(k=8, vector_store=glossary_vector_store)

async def retrieve_glossary(state):
    """
    Retrieve documents

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): New key added to state, documents, that contains retrieved documents
    """
    print("---RETRIEVE ITEMS---")
    rewritten_question = state.get("rewritten_question", "")
    total_retries = state.get("total_retries", 0)
    
    if rewritten_question:
        question = state["rewritten_question"]
        total_retries += 1
    else:
        question = state["question"]
    # Retrieval
    documents = await glossary_retriever.ainvoke(question)
    return {"documents": documents, "total_retries": total_retries}

async def grade_documents_glossary(state):
    """
    Determines whether the retrieved documents are relevant to the question.

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): Updates documents key with only filtered relevant documents
    """

    print("---CHECK DOCUMENT RELEVANCE TO QUESTION---")
    question = state["question"]
    documents = state["documents"]
    
    filtered_docs = []
    # web_search = False
    # glossary_search = False
    retry_query = False
    for d in documents:
        score = await retrieval_grader.ainvoke(
            {"question": question, "document": d.page_content}
        )
        grade = score.binary_score
        if grade == "yes":
            print(f"{d.metadata["title"]}", " [RELEVANT]")
            filtered_docs.append(d)
        else:
            print(f"{d.metadata["title"]}", " [NOT RELEVANT]")
            continue
        
    # If there are three or less relevant endpoints then retry query after rewriting question
    retry_threshold = 2
    
    if len(filtered_docs) <= retry_threshold:
        retry_query=True
        
    #print("Documents: \n", "\n".join(f"{doc.metadata["title"]}" for doc in filtered_docs))
    return {"documents": documents, "relevant_documents": filtered_docs, "question": question, "retry_query": retry_query}
              
async def return_documents(state) -> OutputState:
    """Return the relevant documents"""
    print("---RETRUN RELEVANT DOCUMENTS---")
    relevant_documents = state["relevant_documents"]
    return {"relevant_documents": relevant_documents}