import os

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv("REDIS_URL")
    default_limits=os.getenv("GLOBAL_RATE_LIMIT", "10/minute"),
)