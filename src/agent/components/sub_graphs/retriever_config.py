import os

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.vectorstores import VectorStoreRetriever

def setup_chroma_vector_store(chroma_collection_name: str) -> Chroma:
    """
    Args:
        chroma_collection_name (str): name of the collection on chromadb
    """
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

    chroma_directory = os.getenv("CHROMADB_DIRECTORY")
    if not chroma_directory:
        raise ValueError("Could not find CHROMADB_DIRECTORY in environment variables")
    
    # Check if the directory exists
    if not os.path.exists(chroma_directory):
        raise ValueError(f"Chroma directory {chroma_directory} does not exist")

    vector_store = Chroma(
        collection_name=chroma_collection_name,
        embedding_function=embeddings,
        persist_directory=chroma_directory
    )

    return vector_store

def setup_retriever(k: int, vector_store: Chroma) -> VectorStoreRetriever:
    """
    Args:
        chroma_collection_name (str): name of the collection on chromadb
    """
    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
    return retriever
    
