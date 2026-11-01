"""Whether Opey's LLM key works, for the /status endpoint.

A placeholder key (the one in .env.example, or anything too short or of the wrong shape to be real) counts as not
configured. Its characters are not searched for words such as "xxx": a real key is random and may contain them.
A key that looks real is checked with the provider by listing its models, which costs no tokens; the
answer is cached (10 minutes when the key works, 2 when it does not), so the public /status endpoint never sends
the provider more than a request every few minutes.
"""
import hashlib
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("opey.service.llm_credentials")

_MIN_KEY_LENGTH = 40
_PREFIXES = {"anthropic": "sk-ant-", "openai": "sk-"}
_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
_OK_TTL_SEC = 600.0
_FAILED_TTL_SEC = 120.0
_CHECK_TIMEOUT_SEC = 5.0

# (provider, sha256 of the key) -> (up, detail, expires_at)
_verified: dict[tuple[str, str], tuple[bool, str, float]] = {}

# A provider check: (provider, key) -> (up, detail). Replaceable in tests.
KeyCheck = Callable[[str, str], Awaitable[tuple[bool, str]]]


def key_problem(provider: str, key: Optional[str]) -> Optional[str]:
    """Why this key cannot be a real one, or None when it looks real."""
    if not key:
        return f"{_KEY_ENV.get(provider, 'the API key')} is not set"
    value = key.strip().strip("\"'")
    if len(value) < _MIN_KEY_LENGTH:
        return "the API key is a placeholder (too short to be real)"
    prefix = _PREFIXES.get(provider)
    if prefix and not value.startswith(prefix):
        return f"the API key does not look like a {provider} key (it should start {prefix})"
    return None


async def check_with_provider(provider: str, key: str) -> tuple[bool, str]:
    """List the provider's models with this key: free, and refused when the key is not valid."""
    import aiohttp

    if provider == "anthropic":
        base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        url, headers = f"{base}/v1/models?limit=1", {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        url, headers = f"{base}/models", {"Authorization": f"Bearer {key}"}
    try:
        timeout = aiohttp.ClientTimeout(total=_CHECK_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return True, "the API key works"
                if response.status in (401, 403):
                    return False, f"{provider} refused the API key (HTTP {response.status})"
                return False, f"{provider} answered HTTP {response.status}"
    except Exception as e:
        return False, f"could not reach {provider}: {type(e).__name__}"


async def llm_status(check: Optional[KeyCheck] = None) -> dict[str, Any]:
    """{"up", "provider", "detail"} for the configured provider (MODEL_PROVIDER, default anthropic)."""
    provider = (os.getenv("MODEL_PROVIDER") or "anthropic").strip().strip("\"'").lower()
    if provider not in _KEY_ENV:
        # Ollama and other local providers need no key; nothing to check here.
        return {"up": True, "provider": provider, "detail": "no API key needed"}
    key = os.getenv(_KEY_ENV[provider])
    problem = key_problem(provider, key)
    if problem:
        return {"up": False, "provider": provider, "detail": problem}

    cache_key = (provider, hashlib.sha256(key.encode()).hexdigest())
    now = time.monotonic()
    cached = _verified.get(cache_key)
    if cached and cached[2] > now:
        return {"up": cached[0], "provider": provider, "detail": cached[1]}
    up, detail = await (check or check_with_provider)(provider, key.strip().strip("\"'"))
    _verified[cache_key] = (up, detail, now + (_OK_TTL_SEC if up else _FAILED_TTL_SEC))
    if not up:
        logger.warning(f"LLM key check: {detail}")
    return {"up": up, "provider": provider, "detail": detail}
