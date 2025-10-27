import redis.asyncio as aioredis
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

redis_clients = {}

def get_redis_client() -> aioredis.Redis:
    if not redis_clients or 'default' not in redis_clients:
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        logging.info(f"Creating new default Redis client with: URL {redis_url}")
        redis_clients['default'] = aioredis.from_url(redis_url, decode_responses=True)

    return redis_clients['default']


async def create_redis_client(redis_url: Optional[str] = None) -> aioredis.Redis:
    if not redis_url:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    if redis_url in redis_clients:
        return redis_clients[redis_url]

    client = aioredis.from_url(redis_url, decode_responses=True)
    redis_clients[redis_url] = client
    return client