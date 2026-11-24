"""The /alive liveness check: `true` as JSON, never cached, with no dependency probes."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.routers import misc


def test_alive_answers_true_as_json_and_is_not_cached():
    app = FastAPI()
    app.include_router(misc.router)
    response = TestClient(app).get("/alive")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.text == "true"
