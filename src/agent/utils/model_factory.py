import os
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class ModelConfig:
    """Configuration for a specific model"""
    model_id: str
    provider: str
    api_key_env: Optional[str] = None
    base_url_env: Optional[str] = None
    default_max_tokens: int = 4096
    supports_tools: bool = True

# Define available models with their configurations
MODEL_CONFIGS = {
    # OpenAI models
    "gpt-4o": ModelConfig("gpt-4o", "openai", "OPENAI_API_KEY"),
    "gpt-4o-mini": ModelConfig("gpt-4o-mini", "openai", "OPENAI_API_KEY"),
    "gpt-4-turbo": ModelConfig("gpt-4-turbo", "openai", "OPENAI_API_KEY"),
    "gpt-3.5-turbo": ModelConfig("gpt-3.5-turbo", "openai", "OPENAI_API_KEY"),
    
    # Anthropic models
    "claude-3-5-sonnet-20241022": ModelConfig("claude-3-5-sonnet-20241022", "anthropic", "ANTHROPIC_API_KEY"),
    "claude-3-5-haiku-20241022": ModelConfig("claude-3-5-haiku-20241022", "anthropic", "ANTHROPIC_API_KEY"),
    "claude-3-opus-20240229": ModelConfig("claude-3-opus-20240229", "anthropic", "ANTHROPIC_API_KEY"),
    
    # Ollama models (no API key required)
    "llama3.1": ModelConfig("llama3.1", "ollama"),
    "llama3.1:8b": ModelConfig("llama3.1:8b", "ollama"),
    "llama3.1:70b": ModelConfig("llama3.1:70b", "ollama"),
    "qwen2.5": ModelConfig("qwen2.5", "ollama"),
    "mistral": ModelConfig("mistral", "ollama"),
}

# Add embedding model configs
EMBEDDING_MODELS = {
    "text-embedding-3-large": {
        "provider": "openai",
        "api_key_env": "OPENAI_API_KEY",
    },
    "text-embedding-3-small": {
        "provider": "openai", 
        "api_key_env": "OPENAI_API_KEY",
    },
    # Add more embedding models as needed
}

# Define size categories with fallback chains
MODEL_SIZE_FALLBACKS = {
    "small": [
        "gpt-4o-mini",
        "claude-3-5-haiku-20241022", 
        "gpt-3.5-turbo",
        "llama3.1:8b",
        "qwen2.5"
    ],
    "medium": [
        "gpt-4o",
        "claude-3-5-sonnet-20241022",
        "gpt-4-turbo", 
        "llama3.1:70b",
        "llama3.1"
    ],
    "large": [
        "claude-3-opus-20240229",
        "gpt-4o",
        "claude-3-5-sonnet-20241022",
        "llama3.1:70b"
    ]
}

class ModelFactory:
    """Factory for creating and managing language models with fallbacks"""
    
    def __init__(self):
        self._model_cache: Dict[str, BaseChatModel] = {}
        self._available_models: Optional[List[str]] = None
    
    def _check_model_availability(self, model_name: str) -> bool:
        """Check if a model is available (has required API keys, etc.)"""
        if model_name not in MODEL_CONFIGS:
            return False
            
        config = MODEL_CONFIGS[model_name]
        
        # For Ollama, assume available (could ping the server in future)
        if config.provider == "ollama":
            return True
            
        # Check if required API key is available
        if config.api_key_env and not os.getenv(config.api_key_env):
            return False
            
        return True
    
    def _check_embedding_model_availability(self, model_name: str) -> bool:
        """Check if an embedding model is available"""
        if model_name not in EMBEDDING_MODELS:
            return False
            
        config = EMBEDDING_MODELS[model_name]
        
        # Check if required API key is available
        if config.get("api_key_env") and not os.getenv(config["api_key_env"]):
            return False
            
        return True
    
    def get_embedding_model(self, model_name: str = "text-embedding-3-large") -> Embeddings:
        """
        Get an embedding model instance
        
        Args:
            model_name: Name of the embedding model
            
        Returns:
            An embedding model instance
            
        Raises:
            ValueError: If the model is unknown or unavailable
        """
        if model_name not in EMBEDDING_MODELS:
            raise ValueError(f"Unknown embedding model: {model_name}")
        
        config = EMBEDDING_MODELS[model_name]
        
        if not self._check_embedding_model_availability(model_name):
            raise ValueError(f"Embedding model {model_name} is not available. Check API keys.")
        
        if config["provider"] == "openai":
            return OpenAIEmbeddings(model=model_name)
        
        # Add support for other providers here
        raise ValueError(f"Unsupported embedding model provider: {config['provider']}")

    
    def get_available_models(self) -> List[str]:
        """Get list of available models based on current environment"""
        if self._available_models is None:
            self._available_models = [
                model for model in MODEL_CONFIGS.keys() 
                if self._check_model_availability(model)
            ]
        return self._available_models
    
    def _create_model(self, model_name: str, **kwargs) -> BaseChatModel:
        """Create a model instance"""
        if model_name not in MODEL_CONFIGS:
            raise ValueError(f"Unknown model: {model_name}")
            
        config = MODEL_CONFIGS[model_name]
        
        # Common parameters
        model_kwargs = {
            "temperature": kwargs.get("temperature", 0),
            **{k: v for k, v in kwargs.items() if k != "temperature"}
        }
        
        if config.provider == "openai":
            return ChatOpenAI(
                model=config.model_id,
                api_key=os.getenv(config.api_key_env),
                max_tokens=kwargs.get("max_tokens", config.default_max_tokens),
                **model_kwargs
            )
        elif config.provider == "anthropic":
            return ChatAnthropic(
                model_name=config.model_id,
                api_key=os.getenv(config.api_key_env),
                max_tokens=kwargs.get("max_tokens", config.default_max_tokens),
                **model_kwargs
            )
        elif config.provider == "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            return ChatOllama(
                model=config.model_id,
                base_url=base_url,
                **model_kwargs
            )
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")
    
    def get_model(self, 
                  model_name: str, 
                  use_fallbacks: bool = True,
                  cache: bool = True,
                  **kwargs) -> BaseChatModel:
        """
        Get a model instance with optional fallbacks
        
        Args:
            model_name: Specific model name or size category ("small", "medium", "large")
            use_fallbacks: Whether to try fallback models if primary fails
            cache: Whether to cache the model instance
            **kwargs: Additional parameters for the model
        """
        cache_key = f"{model_name}:{hash(frozenset(kwargs.items()))}"
        
        if cache and cache_key in self._model_cache:
            return self._model_cache[cache_key]
        
        # If it's a size category, get the fallback list
        if model_name in MODEL_SIZE_FALLBACKS:
            candidates = MODEL_SIZE_FALLBACKS[model_name]
        else:
            candidates = [model_name]
        
        # If not using fallbacks, only try the first candidate
        if not use_fallbacks:
            candidates = candidates[:1]
        
        available_models = self.get_available_models()
        
        for candidate in candidates:
            if candidate in available_models:
                try:
                    model = self._create_model(candidate, **kwargs)
                    logger.info(f"Successfully created model: {candidate}")
                    
                    if cache:
                        self._model_cache[cache_key] = model
                    
                    return model
                    
                except Exception as e:
                    logger.warning(f"Failed to create model {candidate}: {e}")
                    continue
        
        raise RuntimeError(
            f"No available models found for '{model_name}'. "
            f"Available models: {available_models}. "
            f"Tried: {candidates}"
        )
    
    def list_models_by_provider(self) -> Dict[str, List[str]]:
        """List available models grouped by provider"""
        available = self.get_available_models()
        by_provider = {}
        
        for model in available:
            provider = MODEL_CONFIGS[model].provider
            if provider not in by_provider:
                by_provider[provider] = []
            by_provider[provider].append(model)
        
        return by_provider

# Global factory instance
model_factory = ModelFactory()

def get_model(model_name: str, **kwargs) -> BaseChatModel:
    """
    Get a model instance with automatic fallbacks
    
    Args:
        model_name: Model name (e.g., "gpt-4o", "claude-3-5-sonnet-20241022") 
                   or size category ("small", "medium", "large")
        **kwargs: Additional model parameters (temperature, max_tokens, etc.)
    
    Returns:
        Configured model instance
        
    Examples:
        >>> model = get_model("gpt-4o", temperature=0.7)
        >>> model = get_model("medium", temperature=0.5, max_tokens=2048)
        >>> model = get_model("claude-3-5-sonnet-20241022")
    """
    return model_factory.get_model(model_name, **kwargs)

def get_embedding_model(model_name: str = "text-embedding-3-large") -> Embeddings:
    """
    Get an embedding model instance
    
    Args:
        model_name: Name of the embedding model
        
    Returns:
        An embedding model instance
    """
    return model_factory.get_embedding_model(model_name)

def get_available_models() -> List[str]:
    """Get list of currently available models"""
    return model_factory.get_available_models()

def list_models_by_provider() -> Dict[str, List[str]]:
    """List available models grouped by provider"""
    return model_factory.list_models_by_provider()

# Backward compatibility
def get_llm(size: str, **kwargs) -> BaseChatModel:
    """Legacy function for backward compatibility"""
    logger.warning("get_llm() is deprecated. Use get_model() instead.")
    return get_model(size, **kwargs)