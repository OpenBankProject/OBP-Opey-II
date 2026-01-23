import os
import logging
from typing import Optional, Any, Protocol

import redis.asyncio as aioredis

from src.service.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class AsyncKeyValue(Protocol):
    """FastMCP AsyncKeyValue interface."""
    
    async def get(self, key: str) -> Optional[Any]: ...
    async def set(self, key: str, value: Any) -> None: ...
    async def delete(self, key: str) -> None: ...


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
    
    async def get(self, key: str) -> Optional[str]:
        return await self._client.get(self._make_key(key))
    
    
    async def set(self, key: str, value: str) -> None:
        redis_key = self._make_key(key)
        if self._ttl:
            await self._client.setex(redis_key, self._ttl, value)
        else:
            await self._client.set(redis_key, value)
            
    async def delete(self, key: str) -> None:
        await self._client.delete(self._make_key(key))
        

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
        
    
    async def get(self, key: str) -> Optional[bytes]:
        file_path = self._get_file_path(key)
        if not os.path.exists(file_path):
            return None
        # Decrypt and read the token from file (implementation omitted)
        # ...
        return b""  # Placeholder
    
    async def set(self, key: str, value: bytes) -> None:
        file_path = self._get_file_path(key)
        # Encrypt and write the token to file (implementation omitted)
        # ...
    
    async def delete(self, key: str) -> None:
        file_path = self._get_file_path(key)
        if os.path.exists(file_path):
            os.remove(file_path)