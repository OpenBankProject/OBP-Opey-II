import os
import json
import logging
from typing import Optional, Any, Protocol

import redis.asyncio as aioredis

from service.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class AsyncKeyValue(Protocol):
    """FastMCP AsyncKeyValue interface (py-key-value protocol)."""
    
    async def get(self, key: str, *, collection: Optional[str] = None) -> Optional[Any]: ...
    async def put(self, key: str, value: Any, *, collection: Optional[str] = None, ttl: Optional[float] = None) -> None: ...
    async def delete(self, key: str, *, collection: Optional[str] = None) -> bool: ...


class RedisTokenStorage:
    """Redis-based OAuth token storage for MCP servers."""
    
    
    def __init__(
        self, 
        server_name: str, 
        redis_key_prefix: str = "mcp:oauth:tokens",
        redis_client: Optional[aioredis.Redis] = None,
        ttl_seconds: Optional[int] = None,
    ):
        self._server_name = server_name
        self._redis_key_prefix = redis_key_prefix
        self._ttl = ttl_seconds
        self._client = redis_client or get_redis_client()
        
        
    def _make_key(self, key: str) -> str:
        return f"{self._redis_key_prefix}:{self._server_name}:{key}"
    
    async def get(self, key: str, *, collection: Optional[str] = None) -> Optional[Any]:
        value = await self._client.get(self._make_key(key))
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Return as-is if not JSON (backward compatibility)
            return value
    
    
    async def put(self, key: str, value: Any, *, collection: Optional[str] = None, ttl: Optional[float] = None) -> None:
        redis_key = self._make_key(key)
        # Serialize to JSON if dict/list, otherwise use as-is
        if isinstance(value, (dict, list)):
            serialized_value = json.dumps(value)
        else:
            serialized_value = value
        
        effective_ttl = ttl or self._ttl
        if effective_ttl:
            await self._client.setex(redis_key, int(effective_ttl), serialized_value)
        else:
            await self._client.set(redis_key, serialized_value)
            
    async def delete(self, key: str, *, collection: Optional[str] = None) -> bool:
        result = await self._client.delete(self._make_key(key))
        return result > 0
        

class EncryptedDiskTokenStorage:
    """Encrypted disk-based OAuth token storage for MCP servers."""
    
    def __init__(
        self,
        server_name: str,
        storage_path: str,
        encryption_key_env: str = "MCP_TOKEN_ENCRYPTION_KEY",
    ):
        self._server_name = server_name
        self._storage_path = storage_path
        self._encryption_key = os.getenv(encryption_key_env)
        
        if not self._encryption_key:
            raise ValueError(f"Encryption key not found in environment variable {encryption_key_env}")
        
        try:
            from cryptography.fernet import Fernet
            self._fernet = Fernet(self._encryption_key.encode())
        except ImportError:
            raise ImportError("cryptography package not installed, install with poetry add cryptography")
    
        os.makedirs(storage_path, exist_ok=True, mode=0o700)
        
        
    def _get_file_path(self, key: str) -> str:
        import hashlib
        safe_key = hashlib.sha256(f"{self._server_name}:{key}".encode()).hexdigest()
        return os.path.join(self._storage_path, f"{safe_key}.enc")
    
    async def get(self, key: str, *, collection: Optional[str] = None) -> Optional[Any]:
        try:
            with open(self._get_file_path(key), 'rb') as f:
                encrypted = f.read()
            decrypted = self._fernet.decrypt(encrypted).decode('utf-8')
            try:
                return json.loads(decrypted)
            except (json.JSONDecodeError, TypeError):
                # Return as-is if not JSON
                return decrypted
        except FileNotFoundError:
            return None
    
    async def put(self, key: str, value: Any, *, collection: Optional[str] = None, ttl: Optional[float] = None) -> None:
        file_path = self._get_file_path(key)
        # Serialize to JSON if dict/list, otherwise use as-is
        if isinstance(value, (dict, list)):
            serialized_value = json.dumps(value)
        else:
            serialized_value = str(value)
        
        encrypted = self._fernet.encrypt(serialized_value.encode('utf-8'))
        with open(file_path, 'wb') as f:
            f.write(encrypted)
        os.chmod(file_path, 0o600)
    
    async def delete(self, key: str, *, collection: Optional[str] = None) -> bool:
        try:
            os.remove(self._get_file_path(key))
            return True
        except FileNotFoundError:
            return False
        

def create_token_storage(
    server_name: str,
    storage_type: str = "memory",
    **kwargs
) -> Optional[AsyncKeyValue]:
    """
    Create token storage for MCP server
    
    Returns None for memory storage i.e. FastMCP OAuth class handles this internally
    """
    if storage_type == "memory":
        logger.warning(f"Using in-memory token storage for '{server_name}' - not suitable for production")
        return None
    
    if storage_type == "redis":
        return RedisTokenStorage(
            server_name,
            redis_key_prefix=kwargs.get("redis_key_prefix", "mcp:oauth:tokens"),
            ttl_seconds=kwargs.get("ttl_seconds"),
        )
        
    if storage_type == "encrypted_disk":
        storage_path = kwargs.get("token_storage_path")
        if not storage_path:
            raise ValueError("token_storage_path must be provided for encrypted_disk storage")
        return EncryptedDiskTokenStorage(
            server_name,
            storage_path,
            encryption_key_env=kwargs.get("encryption_key_env", "MCP_TOKEN_ENCRYPTION_KEY"),
        )
        
    raise ValueError(f"Unknown storage_type '{storage_type}' for MCP server '{server_name}'")