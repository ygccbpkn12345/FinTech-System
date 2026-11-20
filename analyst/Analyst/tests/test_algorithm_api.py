from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.algorithm_api import build_algorithm_router
from services.algorithm_manager import AlgorithmManager
from test_algorithm_manager import Echo, definition


def test_api_crud_and_validation(tmp_path):
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()})
    app = FastAPI()
    app.include_router(build_algorithm_router(manager))
    with TestClient(app) as client:
        assert client.get("/api/algorithms/local-tools").json()["items"][0]["name"] == "echo"
        assert client.post("/api/algorithms", json=definition()).status_code == 201
        assert client.post("/api/algorithms", json=definition()).status_code == 409
        assert client.get("/api/algorithms").json()["items"][0]["name"] == "echo"
        assert client.get("/api/algorithms/echo").status_code == 200
        assert client.put("/api/algorithms/echo", json=definition(description="Updated")).json()["description"] == "Updated"
        assert client.put("/api/algorithms/echo", json=definition(required_parameters=[])).status_code == 422
        assert client.post("/api/algorithms", json=definition(name="remote", kind="http", local_tool=None, http={"url": "file:///tmp/x"})).status_code == 422
        assert client.delete("/api/algorithms/echo").status_code == 204
        assert client.get("/api/algorithms/echo").status_code == 404
        assert client.put("/api/algorithms/echo", json=definition()).status_code == 404
        assert client.delete("/api/algorithms/echo").status_code == 404


def test_disk_error_is_safe_and_keeps_live_tool(tmp_path, monkeypatch):
    manager = AlgorithmManager(tmp_path / "algorithms.json", {"echo": Echo()})
    manager.create(definition())
    app = FastAPI()
    app.include_router(build_algorithm_router(manager))

    def fail(*args):
        raise OSError("secret filesystem path")

    monkeypatch.setattr("services.algorithm_manager.os.replace", fail)
    with TestClient(app) as client:
        response = client.delete("/api/algorithms/echo")
        assert response.status_code == 503
        assert "secret" not in response.text
        assert client.get("/api/algorithms/echo").status_code == 200
