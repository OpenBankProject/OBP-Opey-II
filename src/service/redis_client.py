import redis.asyncio as aioredis
import os
from typing import Optional

redis_clients = {}

def get_redis_client() -> aioredis.Redis:
    return redis_clients['default']


async def create_redis_client(redis_url: Optional[str] = None) -> aioredis.Redis:
    if not redis_url:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    if redis_url in redis_clients:
        return redis_clients[redis_url]

    client = aioredis.from_url(redis_url, decode_responses=True)
    return client