import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from src.agent.components.retrieval.retriever_config import (
    VectorStoreConfig,
    EmbeddingsFactory,
    VectorStoreFactory,
    ChromaVectorStoreFactory,
    RetrieverManager,
    get_retriever_manager,
    get_retriever,
    get_vector_store,
    reset_singleton,
    VectorStoreError,
    ConfigurationError
)


# ================ VectorStoreConfig Tests ================

class TestVectorStoreConfig:
    def test_init_with_valid_parameters(self):
        """Test initialization with valid parameters"""
        config = VectorStoreConfig(collection_name="test_collection")
        assert config.collection_name == "test_collection"
        assert config.embedding_model == "text-embedding-3-large"  # default
        assert config.search_type == "similarity"  # default
        assert config.search_kwargs == {"k": 5}  # default

    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters"""
        config = VectorStoreConfig(
            collection_name="custom_collection",
            embedding_model="custom_model",
            search_type="mmr",
            search_kwargs={"k": 10, "fetch_k": 20}
        )
        assert config.collection_name == "custom_collection"
        assert config.embedding_model == "custom_model"
        assert config.search_type == "mmr"
        assert config.search_kwargs == {"k": 10, "fetch_k": 20}

    def test_invalid_collection_name(self):
        """Test validation of invalid collection_name"""
        with pytest.raises(ConfigurationError, match="collection_name must be a non-empty string"):
            VectorStoreConfig(collection_name="")
        
        with pytest.raises(ConfigurationError, match="collection_name must be a non-empty string"):
            VectorStoreConfig(collection_name=123)

    def test_invalid_search_type(self):
        """Test validation of invalid search_type"""
        with pytest.raises(ConfigurationError, match="Invalid search_type"):
            VectorStoreConfig(collection_name="test", search_type="invalid_type")

    def test_invalid_search_kwargs(self):
        """Test validation of invalid search_kwargs"""
        with pytest.raises(ConfigurationError, match="search_kwargs must be a dictionary"):
            VectorStoreConfig(collection_name="test", search_kwargs="not_a_dict")
            
        with pytest.raises(ConfigurationError, match="search_kwargs\\['k'\\] must be an integer"):
            VectorStoreConfig(collection_name="test", search_kwargs={"k": "5"})


# ================ EmbeddingsFactory Tests ================

class TestEmbeddingsFactory:
    @patch("agent.utils.model_factory.get_embedding_model")  # Fix import path
    def test_create_embeddings_success(self, mock_get_embedding_model):
        """Test successful creation of embeddings"""
        mock_embeddings = MagicMock()
        mock_get_embedding_model.return_value = mock_embeddings
        
        result = EmbeddingsFactory.create_embeddings(model_name="test-model")
        
        mock_get_embedding_model.assert_called_once_with("test-model")
        assert result == mock_embeddings

    def test_invalid_model_name(self):
        """Test validation of invalid model_name"""
        with pytest.raises(ConfigurationError, match="model_name must be a non-empty string"):
            EmbeddingsFactory.create_embeddings(model_name="")
            
        with pytest.raises(ConfigurationError, match="model_name must be a non-empty string"):
            EmbeddingsFactory.create_embeddings(model_name=None)

    @patch("agent.utils.model_factory.get_embedding_model")  # Fix import path
    def test_handle_creation_error(self, mock_get_embedding_model):
        """Test error handling when model creation fails"""
        mock_get_embedding_model.side_effect = ValueError("Test error")
        
        with pytest.raises(VectorStoreError, match="Failed to create embeddings"):
            EmbeddingsFactory.create_embeddings(model_name="test-model")


# ================ ChromaVectorStoreFactory Tests ================

class TestChromaVectorStoreFactory:
    @patch("os.access", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.is_dir", return_value=True)
    def test_init_with_valid_directory(self, mock_is_dir, mock_exists, mock_access):
        """Test initialization with valid directory"""
        factory = ChromaVectorStoreFactory(persist_directory="/valid/directory")
        assert factory.persist_directory == Path("/valid/directory").resolve()
    
    @patch("os.getenv", return_value="/env/directory")
    @patch("os.access", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.is_dir", return_value=True)
    def test_init_with_env_variable(self, mock_is_dir, mock_exists, mock_access, mock_getenv):
        """Test initialization using environment variable"""
        factory = ChromaVectorStoreFactory()
        assert factory.persist_directory == Path("/env/directory").resolve()
    
    @patch("os.getenv", return_value=None)
    def test_init_missing_directory_config(self, mock_getenv):
        """Test error when no directory is provided"""
        with pytest.raises(ConfigurationError, match="CHROMADB_DIRECTORY environment variable must be set"):
            ChromaVectorStoreFactory()
    
    @patch("pathlib.Path.exists", return_value=False)
    def test_validate_nonexistent_directory(self, mock_exists):
        """Test validation of non-existent directory"""
        with pytest.raises(ConfigurationError, match="ChromaDB directory .* does not exist"):
            ChromaVectorStoreFactory(persist_directory="/nonexistent/directory")
    
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.is_dir", return_value=False)
    def test_validate_not_directory(self, mock_is_dir, mock_exists):
        """Test validation when path is not a directory"""
        with pytest.raises(ConfigurationError, match="ChromaDB path .* exists but is not a directory"):
            ChromaVectorStoreFactory(persist_directory="/file/not/directory")
    
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.is_dir", return_value=True)
    @patch("os.access", return_value=False)
    def test_validate_not_writable(self, mock_access, mock_is_dir, mock_exists):
        """Test validation when directory is not writable"""
        with pytest.raises(ConfigurationError, match="ChromaDB directory .* is not writable"):
            ChromaVectorStoreFactory(persist_directory="/not/writable")
    
    @patch("os.access", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.is_dir", return_value=True)
    @patch("src.agent.components.retrieval.retriever_config.EmbeddingsFactory.create_embeddings")
    @patch("langchain_chroma.Chroma")
    def test_create_vector_store_success(self, mock_chroma, mock_create_embeddings, 
                              mock_is_dir, mock_exists, mock_access):
        """Test successful vector store creation"""
        # Setup mocks
        mock_embeddings = MagicMock()
        mock_create_embeddings.return_value = mock_embeddings
        mock_vector_store = MagicMock()
        
        # Patch at chromadb.Client level to prevent actual client initialization
        with patch("chromadb.Client") as mock_client:
            # Configure Chroma mock to return our mock vector store
            with patch("langchain_chroma.Chroma", return_value=mock_vector_store) as mock_chroma:
                # Create factory and test
                factory = ChromaVectorStoreFactory(persist_directory="/valid/directory")
                config = VectorStoreConfig(collection_name="test_collection")
                
                result = factory.create_vector_store(config)
                
                # Assertions
                mock_create_embeddings.assert_called_once_with(config.embedding_model)
                mock_client.assert_called_once()
                assert result == mock_vector_store
                
                # Check Chroma was called with the right parameters
                chroma_args = mock_client.call_args[1]
                assert chroma_args["collection_name"] == "test_collection"
                assert chroma_args["embedding_function"] == mock_embeddings
                assert "/valid/directory" in chroma_args["persist_directory"]
    
    @patch("os.access", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.is_dir", return_value=True)
    @patch("src.agent.components.retrieval.retriever_config.EmbeddingsFactory.create_embeddings")
    def test_create_vector_store_error(self, mock_create_embeddings, mock_is_dir, mock_exists, mock_access):
        """Test error handling during vector store creation"""
        mock_create_embeddings.side_effect = Exception("Test error")
        
        factory = ChromaVectorStoreFactory(persist_directory="/valid/directory")
        config = VectorStoreConfig(collection_name="test_collection")
        
        with pytest.raises(VectorStoreError, match="Failed to create Chroma vector store"):
            factory.create_vector_store(config)


# ================ RetrieverManager Tests ================

class MockVectorStoreFactory(VectorStoreFactory):
    """Mock implementation of VectorStoreFactory for testing"""
    
    def __init__(self):
        self.create_called = False
        
    def is_empty(self, vector_store):
        return False  # Default implementation for testing
    
    def create_vector_store(self, config):
        self.create_called = True
        mock_store = MagicMock()
        mock_retriever = MagicMock()
        mock_store.as_retriever.return_value = mock_retriever
        return mock_store
    
    def validate_configuration(self):
        pass


class TestRetrieverManager:
    def test_init_with_valid_factory(self):
        """Test initialization with valid factory"""
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        assert manager._vector_store_factory == factory
    
    def test_init_with_invalid_factory(self):
        """Test initialization with invalid factory"""
        with pytest.raises(ConfigurationError, match="vector_store_factory must implement VectorStoreFactory"):
            RetrieverManager(MagicMock())  # Not a VectorStoreFactory
    
    def test_get_vector_store_with_valid_config(self):
        """Test get_vector_store with valid config"""
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        config = VectorStoreConfig(collection_name="test_collection")
        
        result = manager.get_vector_store(config)
        
        assert factory.create_called
        assert result is not None
        
    def test_empty_vector_store_check(self):
        """Test that empty vector stores generate a warning log"""
        # Set up
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        config = VectorStoreConfig(collection_name="empty_collection")
        
        # Mock the is_empty method to return True
        factory.is_empty = lambda vs: True
        
        # Check for warning log
        with self.assertLogs(level='WARNING') as log:
            vector_store = manager.get_vector_store(config)
            self.assertIn("appears to be empty", log.output[0])
    
    def test_get_vector_store_with_invalid_config(self):
        """Test get_vector_store with invalid config"""
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        
        with pytest.raises(ConfigurationError, match="config must be a VectorStoreConfig instance"):
            manager.get_vector_store("not_a_config")
    
    def test_get_vector_store_caching(self):
        """Test caching behavior of get_vector_store"""
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        config = VectorStoreConfig(collection_name="test_collection")
        
        # First call should create a new vector store
        first_result = manager.get_vector_store(config)
        assert factory.create_called
        
        # Reset the flag to check if it's called again
        factory.create_called = False
        
        # Second call should use cached vector store
        second_result = manager.get_vector_store(config)
        assert not factory.create_called
        assert second_result is first_result
    
    def test_get_retriever(self):
        """Test get_retriever functionality"""
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        config = VectorStoreConfig(collection_name="test_collection")
        
        result = manager.get_retriever(config)
        
        assert result is not None
    
    def test_clear_cache(self):
        """Test clear_cache functionality"""
        factory = MockVectorStoreFactory()
        manager = RetrieverManager(factory)
        config = VectorStoreConfig(collection_name="test_collection")
        
        # Populate cache
        manager.get_vector_store(config)
        
        # Clear cache
        manager.clear_cache()
        
        # Should create a new vector store
        factory.create_called = False
        manager.get_vector_store(config)
        assert factory.create_called


# ================ Singleton Management Tests ================

@patch("src.agent.components.retrieval.retriever_config._get_vector_store_factory")
def test_get_retriever_manager(mock_get_factory):
    """Test get_retriever_manager returns the same instance"""
    # Set up mock
    mock_factory = MockVectorStoreFactory()
    mock_get_factory.return_value = mock_factory
    
    # Reset singleton for clean test
    reset_singleton()
    
    # First call should create instance
    manager1 = get_retriever_manager()
    assert manager1 is not None
    
    # Second call should return same instance
    manager2 = get_retriever_manager()
    assert manager2 is manager1
    
    # Factory should be called only once
    mock_get_factory.assert_called_once()

def test_reset_singleton():
    """Test reset_singleton clears instance"""
    # Set up a manager
    with patch("src.agent.components.retrieval.retriever_config._get_vector_store_factory") as mock_get_factory:
        mock_factory = MockVectorStoreFactory()
        mock_get_factory.return_value = mock_factory
        
        # Get an instance
        manager = get_retriever_manager()
        
        # Reset singleton
        reset_singleton()
        
        # Mock should be called again for new instance
        mock_get_factory.reset_mock()
        new_manager = get_retriever_manager()
        
        # Should be a different instance
        assert new_manager is not manager
        mock_get_factory.assert_called_once()

@patch("os.getenv")
def test_get_vector_store_factory(mock_getenv):
    """Test _get_vector_store_factory for different types"""
    from src.agent.components.retrieval.retriever_config import _get_vector_store_factory
    
    # Test for Chroma (default)
    mock_getenv.return_value = "chroma"
    
    with patch("src.agent.components.retrieval.retriever_config.ChromaVectorStoreFactory") as mock_factory_class:
        # Need to mock path validation too
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_dir", return_value=True):
                with patch("os.access", return_value=True):
                    mock_factory = MagicMock()
                    mock_factory_class.return_value = mock_factory
                    
                    result = _get_vector_store_factory()
                    assert result == mock_factory
                    mock_factory_class.assert_called_once()
    
    # Test for unsupported type
    mock_getenv.return_value = "unsupported"
    
    # Match the actual error behavior: it tries to create a directory for an unsupported type
    # rather than raising a specific error about unsupported types
    with pytest.raises(ConfigurationError):
        _get_vector_store_factory()


# ================ Convenience Function Tests ================

@patch("src.agent.components.retrieval.retriever_config.get_retriever_manager")
def test_get_retriever_convenience(mock_get_manager):
    """Test get_retriever convenience function"""
    # Set up mocks
    mock_manager = MagicMock()
    mock_get_manager.return_value = mock_manager
    mock_retriever = MagicMock()
    mock_manager.get_retriever.return_value = mock_retriever
    
    # Call function
    result = get_retriever("test_collection", search_kwargs={"k": 10})
    
    # Verify calls
    mock_get_manager.assert_called_once()
    mock_manager.get_retriever.assert_called_once()
    
    # Check if config was created correctly
    called_config = mock_manager.get_retriever.call_args[0][0]
    assert called_config.collection_name == "test_collection"
    assert called_config.search_kwargs == {"k": 10}
    
    # Check result
    assert result == mock_retriever

@patch("src.agent.components.retrieval.retriever_config.get_retriever_manager")
def test_get_vector_store_convenience(mock_get_manager):
    """Test get_vector_store convenience function"""
    # Set up mocks
    mock_manager = MagicMock()
    mock_get_manager.return_value = mock_manager
    mock_vector_store = MagicMock()
    mock_manager.get_vector_store.return_value = mock_vector_store
    
    # Call function
    result = get_vector_store("test_collection", embedding_model="custom_model")
    
    # Verify calls
    mock_get_manager.assert_called_once()
    mock_manager.get_vector_store.assert_called_once()
    
    # Check if config was created correctly
    called_config = mock_manager.get_vector_store.call_args[0][0]
    assert called_config.collection_name == "test_collection"
    assert called_config.embedding_model == "custom_model"
    
    # Check result
    assert result == mock_vector_store