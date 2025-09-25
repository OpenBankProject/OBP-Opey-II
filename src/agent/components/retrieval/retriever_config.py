import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass, field
from threading import Lock
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.vectorstores import VectorStoreRetriever, VectorStore
from langchain_core.embeddings import Embeddings

# Module-specific logger (follows logging best practices)
logger = logging.getLogger(__name__)


class VectorStoreError(Exception):
    """Custom exception for vector store related errors"""
    pass


class ConfigurationError(VectorStoreError):
    """Raised when configuration is invalid"""
    pass


@dataclass
class VectorStoreConfig:
    """
    Configuration for vector store initialization.
    
    Follows the Configuration Object pattern from "Effective Java" and
    "Clean Code" principles for immutable configuration objects.
    """
    collection_name: str
    embedding_model: str = "text-embedding-3-large"
    search_type: str = "similarity"
    search_kwargs: Optional[Dict[str, Any]] = field(default_factory=lambda: {"k": 5})
    
    def __post_init__(self):
        """Validate configuration parameters (Fail-Fast)"""
        if not isinstance(self.collection_name, str) or not self.collection_name.strip():
            raise ConfigurationError("collection_name must be a non-empty string")
        
        if self.search_type not in ("similarity", "mmr", "similarity_score_threshold"):
            raise ConfigurationError(f"Invalid search_type: {self.search_type}")
        
        if not isinstance(self.search_kwargs, dict):
            raise ConfigurationError("search_kwargs must be a dictionary")
        
        # Ensure k parameter is valid
        if "k" in self.search_kwargs and not isinstance(self.search_kwargs["k"], int):
            raise ConfigurationError("search_kwargs['k'] must be an integer")


class EmbeddingsFactory:
    """
    Factory for creating embeddings instances.
    
    Implements the Factory Method pattern (GoF Design Patterns).
    Future: Should integrate with model_factory for consistency.
    """
    
    @staticmethod
    def create_embeddings(model_name: str = "text-embedding-3-large") -> Embeddings:
        """
        Create embeddings instance with validation.
        
        Args:
            model_name: Name of the embedding model
            
        Returns:
            Embeddings: Configured embeddings instance
            
        Raises:
            ConfigurationError: If model_name is invalid
        """
        from agent.utils.model_factory import get_embedding_model
        
        if not isinstance(model_name, str) or not model_name.strip():
            raise ConfigurationError("model_name must be a non-empty string")
        
        try:
            return get_embedding_model(model_name)
        except Exception as e:
            raise VectorStoreError(f"Failed to create embeddings for model '{model_name}': {e}")

class VectorStoreFactory(ABC):
    """
    Abstract factory for creating vector stores.
    
    Implements the Abstract Factory pattern (GoF Design Patterns).
    """
    @abstractmethod
    def is_empty(self, vector_store: VectorStore) -> bool:
        """
        Check if the vector store is empty.
        
        Args:
            vector_store: Instance of VectorStore
        Returns:
            bool: True if empty, False otherwise
        """
        pass
    
    @abstractmethod
    def get_all_collection_names(self) -> list:
        """
        Retrieve all collection names from the vector store.
        
        Returns:
            list: List of collection names
        """
        pass
    
    @abstractmethod
    def get_vector_store(self, config: VectorStoreConfig) -> VectorStore:
        """
        Get an existing vector store.
        
        Args:
            config: Vector store configuration
            
        Returns:
            VectorStore: Configured vector store instance
            
        Raises:
            VectorStoreError: If vector store creation fails
        """
        pass
    
    @abstractmethod
    def validate_configuration(self) -> None:
        """
        Validate factory-specific configuration.
        
        Raises:
            ConfigurationError: If configuration is invalid
        """
        pass


class ChromaVectorStoreFactory(VectorStoreFactory):
    """
    Factory for creating Chroma vector stores.
    
    Implements the Factory Method pattern with proper validation
    following the Fail-Fast principle.
    """
    
    def __init__(self, persist_directory: Optional[Union[str, Path]] = None):
        """
        Initialize Chroma factory with directory validation.
        
        Args:
            persist_directory: Path to ChromaDB persistence directory
            
        Raises:
            ConfigurationError: If directory configuration is invalid
        """
        self.persist_directory = self._resolve_directory(persist_directory)
        self.validate_configuration()
        
        logger.info(f"ChromaDB factory initialized with directory: {self.persist_directory}")
    
    def is_empty(self, vector_store: VectorStore) -> bool:
        """
        Check if a Chroma vector store is empty.
        
        Args:
            vector_store: The Chroma vector store to check
            
        Returns:
            bool: True if empty, False otherwise
        """
        try:
            # For Chroma, we can check the number of elements in the collection
            # The _collection attribute holds the underlying Chroma collection
            if hasattr(vector_store, "_collection"):
                count = vector_store._collection.count()
                return count == 0
            return True  # If no _collection attribute, assume empty
        except Exception as e:
            logger.warning(f"Failed to check if vector store is empty: {e}")
            return False  # Conservative approach: assume not empty on error

    def get_all_collection_names(self) -> list:
        """Retrieve all collection names from the ChromaDB directory"""
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.persist_directory))
            collections = client.list_collections()
            return [col.name for col in collections]
        except Exception as e:
            raise VectorStoreError(f"Failed to list collections: {e}")
    
    def _resolve_directory(self, persist_directory: Optional[Union[str, Path]]) -> Path:
        """Resolve and validate the persistence directory"""
        if persist_directory:
            directory = Path(persist_directory)
        else:
            env_dir = os.getenv("CHROMADB_DIRECTORY")
            if not env_dir:
                raise ConfigurationError(
                    "CHROMADB_DIRECTORY environment variable must be set or "
                    "persist_directory must be provided"
                )
            directory = Path(env_dir)
        
        return directory.resolve()  # Convert to absolute path
    
    def validate_configuration(self) -> None:
        """
        Validate ChromaDB configuration.
        
        Raises:
            ConfigurationError: If configuration is invalid
        """
        if not self.persist_directory.exists():
            raise ConfigurationError(
                f"ChromaDB directory '{self.persist_directory}' does not exist. "
                f"Please create the directory or check your configuration."
            )
        
        if not self.persist_directory.is_dir():
            raise ConfigurationError(
                f"ChromaDB path '{self.persist_directory}' exists but is not a directory"
            )
        
        # Check if directory is writable (important for ChromaDB operations)
        if not os.access(self.persist_directory, os.W_OK):
            raise ConfigurationError(
                f"ChromaDB directory '{self.persist_directory}' is not writable"
            )
    
    def get_vector_store(self, config: VectorStoreConfig) -> Chroma:
        """
        Create a Chroma vector store with proper error handling.
        
        Args:
            config: Vector store configuration
            
        Returns:
            Chroma: Configured Chroma vector store
            
        Raises:
            VectorStoreError: If vector store creation fails
        """
        try:
            embeddings = EmbeddingsFactory.create_embeddings(config.embedding_model)
            
            return Chroma(
                collection_name=config.collection_name,
                embedding_function=embeddings,
                persist_directory=str(self.persist_directory),
                create_collection_if_not_exists=False
            )
        except Exception as e:
            raise VectorStoreError(
                f"Failed to create Chroma vector store for collection "
                f"'{config.collection_name}': {e}"
            )


class RetrieverManager:
    """
    Manager for vector store retrievers with caching.
    
    Implements the Facade pattern to simplify vector store operations.
    Uses caching to improve performance (Industry standard pattern).
    """
    
    def __init__(self, vector_store_factory: VectorStoreFactory):
        """
        Initialize retriever manager with dependency injection.
        
        Args:
            vector_store_factory: Factory for creating vector stores
        """
        if not isinstance(vector_store_factory, VectorStoreFactory):
            raise ConfigurationError("vector_store_factory must implement VectorStoreFactory")
        
        self._vector_store_factory = vector_store_factory
        self._vector_stores: Dict[str, VectorStore] = {}
        logger.info(f"RetrieverManager initialized with {type(vector_store_factory).__name__}")
    
    def _generate_cache_key(self, config: VectorStoreConfig) -> str:
        """Generate cache key for vector store instances"""
        return f"{config.collection_name}_{config.embedding_model}"
    
    def get_vector_store(self, config: VectorStoreConfig) -> VectorStore:
        """
        Get or create a vector store instance with caching.
        
        Args:
            config: Vector store configuration
            
        Returns:
            VectorStore: Cached or newly created vector store
            
        Raises:
            VectorStoreError: If vector store creation fails
        """
        if not isinstance(config, VectorStoreConfig):
            raise ConfigurationError("config must be a VectorStoreConfig instance")
        
        cache_key = self._generate_cache_key(config)
        
        if cache_key not in self._vector_stores:
            logger.info(f"Creating new vector store for collection: {config.collection_name}")
            self._vector_stores[cache_key] = self._vector_store_factory.get_vector_store(config)
        else:
            logger.debug(f"Using cached vector store for collection: {config.collection_name}")
        
        vector_store = self._vector_stores[cache_key]
        
        # Check if the vector store is empty and log a warning
        if self._vector_store_factory.is_empty(vector_store):
            logger.warning(
                f"Vector store for collection '{config.collection_name}' appears to be empty. "
                f"This may cause retrieval operations to return empty results."
            )
        elif not self._vector_store_factory.get_all_collection_names():
            logger.warning(
                f"No collections found in the vector store directory. "
                f"{'Ensure that the directory \'' + str(self._vector_store_factory.persist_directory) + '\' ' if hasattr(self._vector_store_factory, 'persist_directory') else ''}"
                f"contains valid collections."
            )
        else:
            logger.info(
                f"Vector store for collection '{config.collection_name}' is ready with "
                f"{self._vector_store_factory.get_all_collection_names()} collections available."
            )
            
            
        return vector_store
    
    def get_retriever(self, config: VectorStoreConfig) -> VectorStoreRetriever:
        """
        Get a retriever from the vector store.
        
        Args:
            config: Vector store configuration
            
        Returns:
            VectorStoreRetriever: Configured retriever
            
        Raises:
            VectorStoreError: If retriever creation fails
        """
        try:
            vector_store = self.get_vector_store(config)
            
            return vector_store.as_retriever(
                search_type=config.search_type,
                search_kwargs=config.search_kwargs,
            )
        except Exception as e:
            raise VectorStoreError(f"Failed to create retriever: {e}")
    
    def clear_cache(self) -> None:
        """Clear cached vector stores (useful for testing and memory management)"""
        self._vector_stores.clear()
        logger.info("Vector store cache cleared")


# Thread-safe singleton implementation (Industry standard pattern)
_factory_lock = Lock()
_default_vector_store_type = os.getenv("VECTOR_STORE_TYPE", "chroma").lower()
_default_retriever_manager: Optional[RetrieverManager] = None


def _get_vector_store_factory() -> VectorStoreFactory:
    """
    Factory method to create the appropriate vector store factory.
    
    Implements the Factory Method pattern with proper error handling.
    
    Returns:
        VectorStoreFactory: Configured factory instance
        
    Raises:
        ConfigurationError: If vector store type is unsupported
    """
    if _default_vector_store_type == "chroma":
        return ChromaVectorStoreFactory()
    # TODO: Add other vector store types here following the same pattern
    # elif _default_vector_store_type == "pinecone":
    #     return PineconeVectorStoreFactory()
    # elif _default_vector_store_type == "weaviate":
    #     return WeaviateVectorStoreFactory()
    else:
        raise ConfigurationError(
            f"Unsupported vector store type: '{_default_vector_store_type}'. "
            f"Supported types: chroma"
        )


def get_retriever_manager() -> RetrieverManager:
    """
    Get the default retriever manager using thread-safe singleton pattern.
    
    Returns:
        RetrieverManager: Thread-safe singleton instance
    """
    global _default_retriever_manager
    
    if _default_retriever_manager is None:
        with _factory_lock:
            # Double-checked locking pattern
            if _default_retriever_manager is None:
                try:
                    factory = _get_vector_store_factory()
                    _default_retriever_manager = RetrieverManager(factory)
                    logger.info("Default RetrieverManager initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize RetrieverManager: {e}")
                    raise ConfigurationError(f"Failed to initialize retriever manager: {e}")
    
    return _default_retriever_manager


# Database-agnostic convenience functions (Facade pattern)
def get_retriever(collection_name: str, **kwargs) -> VectorStoreRetriever:
    """
    Get a retriever for the specified collection (database-agnostic).
    
    Args:
        collection_name: Name of the collection
        **kwargs: Additional config parameters (embedding_model, search_type, search_kwargs, etc.)
    
    Returns:
        VectorStoreRetriever: Configured with the current vector store backend
        
    Raises:
        ConfigurationError: If configuration is invalid
        VectorStoreError: If retriever creation fails
    """
    try:
        config = VectorStoreConfig(collection_name=collection_name, **kwargs)
        manager = get_retriever_manager()
        return manager.get_retriever(config)
    except Exception as e:
        logger.error(f"Failed to get retriever for collection '{collection_name}': {e}")
        raise


def get_vector_store(collection_name: str, **kwargs) -> VectorStore:
    """
    Get a vector store for the specified collection (database-agnostic).
    
    Args:
        collection_name: Name of the collection
        **kwargs: Additional config parameters
    
    Returns:
        VectorStore: Configured with the current vector store backend
        
    Raises:
        ConfigurationError: If configuration is invalid
        VectorStoreError: If vector store creation fails
    """
    try:
        config = VectorStoreConfig(collection_name=collection_name, **kwargs)
        manager = get_retriever_manager()
        return manager.get_vector_store(config)
    except Exception as e:
        logger.error(f"Failed to get vector store for collection '{collection_name}': {e}")
        raise


def reset_singleton() -> None:
    """
    Reset the singleton instance (primarily for testing).
    
    This function is useful for unit testing to ensure clean state
    between test runs.
    """
    global _default_retriever_manager
    with _factory_lock:
        if _default_retriever_manager:
            _default_retriever_manager.clear_cache()
        _default_retriever_manager = None
        logger.info("Singleton instance reset")
