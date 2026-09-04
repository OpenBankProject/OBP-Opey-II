"""
Client-credentials service token: authenticates Opey ITSELF to MCP servers.

Per the auth contract (OBP-Frontend/for_team_opey_mcp_auth_contract.md):
service identity = the service's own credential; user identity = the consent,
nothing else. MCP ingress stays bearer-based because that is the MCP standard —
but the bearer must be Opey's own OAuth client-credentials JWT (validated by
OBP-MCP's bearer-only MultiIssuerJWTVerifier against the OIDC issuer), never
the user's token.

Configuration (all three required to activate):
  OPEY_OIDC_TOKEN_URL      e.g. http://localhost:9000/obp-oidc/token
  OPEY_OIDC_CLIENT_ID
  OPEY_OIDC_CLIENT_SECRET
"""
import logging
import os
import time
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Refresh this many seconds before expiry so an in-flight tool call never
# carries a token that dies mid-request.
_EXPIRY_MARGIN_SECONDS = 30
_DEFAULT_EXPIRES_IN = 300


class ClientCredentialsTokenProvider:
    """Fetches and caches an OAuth2 client-credentials token for Opey."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    @staticmethod
    def _config() -> Optional[dict]:
        token_url = os.getenv("OPEY_OIDC_TOKEN_URL")
        client_id = os.getenv("OPEY_OIDC_CLIENT_ID")
        client_secret = os.getenv("OPEY_OIDC_CLIENT_SECRET")
        if not (token_url and client_id and client_secret):
            return None
        return {"token_url": token_url, "client_id": client_id, "client_secret": client_secret}

    def is_configured(self) -> bool:
        return self._config() is not None

    async def get_token(self) -> Optional[str]:
        """Return a valid service token, refreshing when near expiry.

        Returns None (with a clear log) when unconfigured or the fetch fails —
        callers then omit the header and the MCP server's own auth policy decides.
        """
        config = self._config()
        if config is None:
            logger.warning(
                "Service token requested but OPEY_OIDC_TOKEN_URL / OPEY_OIDC_CLIENT_ID / "
                "OPEY_OIDC_CLIENT_SECRET are not all set — MCP servers with "
                "use_service_token=true will receive no Authorization header"
            )
            return None

        if self._token and time.time() < self._expires_at - _EXPIRY_MARGIN_SECONDS:
            return self._token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config["token_url"],
                    data={
                        "grant_type": "client_credentials",
                        "client_id": config["client_id"],
                        "client_secret": config["client_secret"],
                    },
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error(
                            f"Service token fetch failed: HTTP {response.status} from "
                            f"{config['token_url']}: {body[:300]}"
                        )
                        return None
                    payload = await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Service token fetch failed: {type(e).__name__}: {e}")
            return None

        access_token = payload.get("access_token")
        if not access_token:
            logger.error(f"Service token response had no access_token: keys={list(payload.keys())}")
            return None

        expires_in = payload.get("expires_in", _DEFAULT_EXPIRES_IN)
        self._token = access_token
        self._expires_at = time.time() + float(expires_in)
        logger.info(f"Fetched Opey service token (expires in {expires_in}s)")
        return self._token


service_token_provider = ClientCredentialsTokenProvider()
