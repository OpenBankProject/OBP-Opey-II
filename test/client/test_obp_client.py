"""
OBPClient: the one place every request to OBP-API goes through, including the obp_requests tool whose path the
model chooses at run time. No network: the aiohttp session is a fake that records what it was asked to send.

  - a path on an OBP-API version below v5.1.0 is refused before anything is sent
  - paths on v5.1.0 or newer, and paths with no OBP version in them, go through
  - the URL, headers, body and status handling of a request
"""
import json
from unittest.mock import AsyncMock

import aiohttp
import pytest

from client.obp_client import OBPClient, OBPResponse


class _Auth:
    def construct_headers(self, token=None):
        return {"Consent-Id": "consent-1", "Content-Type": "application/json"}


class _Reply:
    def __init__(self, data, status):
        self._data, self.status, self.headers = data, status, {"X-Test": "1"}

    async def json(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    """Records each request and answers with `data` and `status`."""

    def __init__(self, data=None, status=200, error=None):
        self.calls, self._data, self._status, self._error = [], data if data is not None else {}, status, error

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return _Reply(self._data, self._status)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("OBP_BASE_URL", "https://obp.test")
    return OBPClient(_Auth())


def use(client, session):
    client._get_session = AsyncMock(return_value=session)
    return session


BELOW_THE_FLOOR = [
    "/obp/v1.2.1/banks",
    "/obp/v3.1.0/banks/BANK_ID/accounts",
    "/obp/v4.0.0/banks",
    "/obp/v5.0.0/banks",
    "/obp/v5.0.0/banks?limit=5",
    "/obp/v5.0.0",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", BELOW_THE_FLOOR)
@pytest.mark.parametrize("method", ["get", "post", "put", "delete", "patch"])
async def test_a_path_below_v510_is_refused_and_nothing_is_sent(client, method, path):
    session = use(client, _Session())
    call = getattr(client, method)
    args = (path,) if method in ("get", "delete") else (path, {"a": 1})
    with pytest.raises(ValueError, match="v5.1.0"):
        await call(*args)
    assert session.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/obp/v5.1.0/banks",
    "/obp/v6.0.0/my/accounts",
    "/obp/v7.0.0/banks/BANK_ID/dynamic-entities",
    "/obp/v10.0.0/banks",
    "/obp/dynamic-entity/banks/b/parcel",
    "/obp/berlin-group/v1.3/accounts",
    "/open-banking/v3.1/aisp/accounts",
])
async def test_a_path_on_v510_or_newer_or_with_no_obp_version_is_sent(client, path):
    session = use(client, _Session({"ok": True}))
    response = await client.get(path)
    assert response.ok
    assert session.calls[0]["url"] == f"https://obp.test{path}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/obp/v5.1.0/../v4.0.0/banks",
    "/obp/v6.0.0/%2e%2e/v4.0.0/banks",
    "/obp/v6.0.0/banks/../../v3.1.0/banks",
    "/obp/v6.0.0/%252e%252e/v4.0.0/banks",
    "/obp/v6.0.0/..%2fv4.0.0/banks",
])
async def test_a_path_that_climbs_back_to_an_older_version_is_refused(client, path):
    session = use(client, _Session())
    with pytest.raises(ValueError, match="climbs out"):
        await client.get(path)
    assert session.calls == []


@pytest.mark.asyncio
async def test_the_version_is_judged_on_the_number_not_the_text(client):
    session = use(client, _Session())
    await client.get("/obp/v10.0.0/banks")
    with pytest.raises(ValueError):
        await client.get("/OBP/V4.0.0/banks")
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_the_obp_requests_tool_refuses_a_path_below_v510(client):
    session = use(client, _Session())
    tool = client.get_langchain_tool("dangerous")
    with pytest.raises(ValueError, match="v5.1.0"):
        await tool.coroutine(method="GET", path="/obp/v4.0.0/banks")
    assert session.calls == []


@pytest.mark.asyncio
async def test_the_safe_obp_requests_tool_refuses_a_path_below_v510(client):
    session = use(client, _Session())
    tool = client.get_langchain_tool("safe")
    with pytest.raises(ValueError, match="v5.1.0"):
        await tool.coroutine("/obp/v3.1.0/banks")
    assert session.calls == []


@pytest.mark.asyncio
async def test_the_obp_requests_tool_sends_the_method_path_and_body_and_returns_the_text(client):
    session = use(client, _Session({"bank_id": "b1"}))
    tool = client.get_langchain_tool("dangerous")
    text = await tool.coroutine(method="post", path="/obp/v7.0.0/banks", body='{"name": "x"}')
    sent = session.calls[0]
    assert (sent["method"], sent["url"], sent["json"]) == ("POST", "https://obp.test/obp/v7.0.0/banks", {"name": "x"})
    assert json.loads(text) == {"bank_id": "b1"}


@pytest.mark.asyncio
async def test_the_obp_requests_tool_rejects_an_unsupported_method(client):
    use(client, _Session())
    tool = client.get_langchain_tool("test")
    with pytest.raises(ValueError, match="Unsupported HTTP method"):
        await tool.coroutine(method="TRACE", path="/obp/v7.0.0/banks")


@pytest.mark.asyncio
async def test_a_request_carries_the_auth_headers(client):
    session = use(client, _Session())
    await client.get("/obp/v6.0.0/users/current")
    assert session.calls[0]["headers"]["Consent-Id"] == "consent-1"


@pytest.mark.asyncio
async def test_an_error_status_is_returned_not_raised_until_asked(client):
    use(client, _Session({"message": "no such bank"}, status=404))
    response = await client.get("/obp/v6.0.0/banks/x")
    assert not response.ok and response.status_code == 404
    with pytest.raises(Exception, match="HTTP 404: no such bank"):
        response.raise_for_status()


@pytest.mark.asyncio
async def test_a_network_error_is_raised(client):
    use(client, _Session(error=aiohttp.ClientConnectionError("refused")))
    with pytest.raises(aiohttp.ClientError):
        await client.get("/obp/v6.0.0/banks")


def test_the_client_needs_obp_base_url(monkeypatch):
    monkeypatch.delenv("OBP_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="OBP_BASE_URL"):
        OBPClient(_Auth())


def test_an_obp_response_has_json_text_and_ok():
    response = OBPResponse({"a": "é"}, 201, "https://obp.test/x", {})
    assert response.ok and response.json() == {"a": "é"} and response.text == '{"a":"é"}'
    assert not OBPResponse({}, 500, "u", {}).ok
