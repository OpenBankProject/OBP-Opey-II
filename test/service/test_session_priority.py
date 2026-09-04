"""
Pins the consent-first contract of POST /create-session:

  - both headers present  -> consent session, NO bearer persisted
  - bearer only           -> bearer session (MCP-standard service clients)
  - consent only          -> consent session

Background: the Portal sends both headers; the old bearer-first ordering made
every Portal session a bearer session, silently bypassing the consent ceremony
(see OBP-Frontend/for_team_opey_mcp_auth_contract.md). Auth strategies are
faked — this tests the routing decision, not OBP validation.
"""
import uuid

import pytest

try:
    from httpx import ASGITransport, AsyncClient
    from service.service import app
    from service.dependencies import get_auth_config
    import auth.session as auth_session
except Exception:  # pragma: no cover - mirror conftest's tolerance of a broken env
    app = None


class _AcceptAllStrategy:
    def __init__(self, user_id: str):
        self._user_id = user_id

    async def acheck_auth(self, token: str | None = None) -> bool:
        return True

    async def get_current_user(self, token: str | None = None) -> dict:
        return {"user_id": self._user_id}


class _FakeAuthConfig:
    def __init__(self):
        self.auth_strategies = {
            "obp_consent_id": _AcceptAllStrategy("user-via-consent"),
            "obp_bearer": _AcceptAllStrategy("user-via-bearer"),
        }


captured_sessions: dict[uuid.UUID, object] = {}


@pytest.fixture()
def fake_auth():
    if app is None:
        pytest.skip("service.service app not importable in this environment")
    app.dependency_overrides[get_auth_config] = lambda: _FakeAuthConfig()

    captured_sessions.clear()
    original_create = auth_session.backend.create

    # Pure capture — deliberately NOT delegating to the real backend: this test
    # pins the routing decision, and the shared Redis client is bound to another
    # test's event loop under pytest-asyncio's per-test loops.
    async def capturing_create(session_id, data):
        captured_sessions[session_id] = data

    auth_session.backend.create = capturing_create
    yield
    auth_session.backend.create = original_create
    app.dependency_overrides.pop(get_auth_config, None)


@pytest.mark.asyncio
async def test_both_headers_prefers_consent_and_drops_bearer(fake_auth):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/create-session",
            headers={"Consent-Id": "consent-123", "Authorization": "Bearer user-token"},
        )
    assert response.status_code == 200
    assert len(captured_sessions) == 1
    session = next(iter(captured_sessions.values()))
    assert session.consent_id == "consent-123"
    assert session.bearer_token is None, "user bearer must not be persisted when a consent is presented"
    assert session.user_id == "user-via-consent"


@pytest.mark.asyncio
async def test_bearer_only_creates_bearer_session(fake_auth):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/create-session",
            headers={"Authorization": "Bearer service-or-user-token"},
        )
    assert response.status_code == 200
    session = next(iter(captured_sessions.values()))
    assert session.bearer_token == "service-or-user-token"
    assert session.consent_id is None
    assert session.user_id == "user-via-bearer"


@pytest.mark.asyncio
async def test_consent_only_creates_consent_session(fake_auth):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/create-session", headers={"Consent-Id": "consent-456"})
    assert response.status_code == 200
    session = next(iter(captured_sessions.values()))
    assert session.consent_id == "consent-456"
    assert session.bearer_token is None
