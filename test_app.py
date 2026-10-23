from itertools import count

import pytest
from fastapi.testclient import TestClient
import app_final as service

@pytest.fixture
def client(monkeypatch):
    service.polls.clear()
    monkeypatch.setattr(service, "poll_ids", count(1))
    with TestClient(service.app) as test_client:
        yield test_client
    service.polls.clear()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_poll(client):
    response = client.post("/polls", json={
        "question": "Что изучать?",
        "options": ["Python", "Go"],
    })
    assert response.status_code == 201
    poll = response.json()
    assert poll["question"] == "Что изучать?"
    assert len(poll["options"]) == 2
    assert client.get(f"/polls/{poll['id']}").status_code == 200


def test_unknown_poll(client):
    response = client.post("/polls/999/votes", json={"option_id": 1})
    assert response.status_code == 404