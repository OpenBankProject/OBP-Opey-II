"""
The session endpoints, run in the same process with no OBP-API and no Redis:

  - POST /create-session refuses a Consent-Id OBP-API does not accept, and a call with no credentials
  - POST /create-session with an accepted Consent-Id sets the session cookie, and that cookie opens the
    session-protected routes
  - POST /delete-session removes the session, after which the cookie no longer opens them
  - a session-protected route without a cookie answers 403

The auth strategies and the session store are fakes. Which header wins when several arrive is pinned in
test_session_priority.py.
"""
import pytest

try:
    from httpx import ASGITransport, AsyncClient
    from service.service import app
    from service.dependencies import get_auth_config
    import auth.session as auth_session
except Exception:  # pragma: no cover - mirror conftest's tolerance of a broken env
    app = None


class _Strategy:
    def __init__(self, accepts: bool, user_id: str = "user-1"):
        self._accepts = accepts
        self._user_id = user_id

    async def acheck_auth(self, token: str | None = None) -> bool:
        return self._accepts

    async def get_current_user(self, token: str | None = None) -> dict:
        return {"user_id": self._user_id}


class _AuthConfig:
    def __init__(self, accepts: bool):
        self.auth_strategies = {"obp_consent_id": _Strategy(accepts), "obp_bearer": _Strategy(accepts)}


@pytest.fixture()
def store(monkeypatch):
    """An in-memory session store in place of Redis."""
    if app is None:
        pytest.skip("service.service app not importable in this environment")
    sessions: dict = {}

    async def create(session_id, data):
        sessions[session_id] = data

    async def read(session_id):
        return sessions[session_id]

    async def delete(session_id):
        sessions.pop(session_id, None)

    monkeypatch.setattr(auth_session.backend, "create", create)
    monkeypatch.setattr(auth_session.backend, "read", read)
    monkeypatch.setattr(auth_session.backend, "delete", delete)
    monkeypatch.delenv("ALLOW_ANONYMOUS_SESSIONS", raising=False)
    yield sessions
    app.dependency_overrides.pop(get_auth_config, None)


def client() -> "AsyncClient":
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")  # the session cookie is Secure


def accept_consents(accepts: bool) -> None:
    app.dependency_overrides[get_auth_config] = lambda: _AuthConfig(accepts)


@pytest.mark.asyncio
async def test_create_session_refuses_a_consent_id_obp_does_not_accept(store):
    accept_consents(False)
    async with client() as c:
        response = await c.post("/create-session", headers={"Consent-Id": "not-a-consent"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Consent-Id"}
    assert store == {}


@pytest.mark.asyncio
async def test_create_session_without_credentials_is_refused_unless_anonymous_sessions_are_allowed(store):
    accept_consents(True)
    async with client() as c:
        response = await c.post("/create-session")
    assert response.status_code == 401
    assert store == {}


@pytest.mark.asyncio
async def test_a_protected_route_without_a_session_answers_403(store):
    async with client() as c:
        response = await c.get("/usage")
    assert response.status_code == 403
    assert response.json()["message"] == "No session provided"
    assert response.json()["error_code"] == "authentication_failed"


@pytest.mark.asyncio
async def test_a_created_session_opens_protected_routes_until_it_is_deleted(store):
    accept_consents(True)
    async with client() as c:
        created = await c.post("/create-session", headers={"Consent-Id": "consent-1"})
        assert created.status_code == 200
        assert "session" in created.cookies
        assert len(store) == 1
        assert next(iter(store.values())).user_id == "user-1"

        opened = await c.get("/usage")
        assert opened.status_code != 403

        deleted = await c.post("/delete-session")
        assert deleted.status_code == 200
        assert store == {}

        c.cookies.clear()
        closed = await c.get("/usage")
        assert closed.status_code == 403
        assert closed.json()["message"] == "No session provided"
