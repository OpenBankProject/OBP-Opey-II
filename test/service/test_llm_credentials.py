"""The LLM key check behind /status: placeholder keys are down, real-looking keys are checked once and cached."""
import asyncio

import pytest

from service import llm_credentials
from service.llm_credentials import key_problem, llm_status

REAL_LOOKING_ANTHROPIC_KEY = "sk-ant-api03-" + "a1B2c3D4e5" * 9


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    llm_credentials._verified.clear()
    monkeypatch.setenv("MODEL_PROVIDER", "anthropic")
    yield
    llm_credentials._verified.clear()


def test_placeholder_keys_are_not_real():
    assert key_problem("anthropic", None) == "ANTHROPIC_API_KEY is not set"
    assert "too short" in key_problem("anthropic", "sk-ant-xxxxxxxx")
    assert "too short" in key_problem("anthropic", "your-anthropic-api-key")
    assert "too short" in key_problem("anthropic", "sk-ant-12345678a")
    assert "should start sk-ant-" in key_problem("anthropic", "a1" * 30)
    assert key_problem("anthropic", REAL_LOOKING_ANTHROPIC_KEY) is None


def test_a_real_key_may_contain_any_characters():
    # Real keys are random: "xxx", "your" or "example" inside one says nothing.
    assert key_problem("anthropic", REAL_LOOKING_ANTHROPIC_KEY[:40] + "xxxYourExample" + REAL_LOOKING_ANTHROPIC_KEY[40:]) is None


def test_a_placeholder_key_is_down_without_asking_the_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-12345678a")
    calls = []

    async def check(provider, key):
        calls.append(key)
        return True, "the API key works"

    status = asyncio.run(llm_status(check))
    assert status["up"] is False and "placeholder" in status["detail"]
    assert calls == []


def test_a_real_looking_key_is_checked_once_and_the_answer_cached(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_LOOKING_ANTHROPIC_KEY)
    calls = []

    async def refused(provider, key):
        calls.append(key)
        return False, "anthropic refused the API key (HTTP 401)"

    first = asyncio.run(llm_status(refused))
    second = asyncio.run(llm_status(refused))
    assert first == second == {"up": False, "provider": "anthropic", "detail": "anthropic refused the API key (HTTP 401)"}
    assert len(calls) == 1


def test_a_working_key_is_up(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_LOOKING_ANTHROPIC_KEY)

    async def works(provider, key):
        return True, "the API key works"

    assert asyncio.run(llm_status(works))["up"] is True


def test_a_local_provider_needs_no_key(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    assert asyncio.run(llm_status())["up"] is True
