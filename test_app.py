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


@pytest.fixture
def poll(client):
    response = client.post("/polls", json={
        "question": "Что изучать?",
        "options": ["Python", "Go", "Rust"],
    })
    assert response.status_code == 201
    return response.json()


def test_version_from_environment(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "2.3.4")
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "2.3.4"}


def test_default_version(client, monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert client.get("/version").json() == {"version": "0.1.0"}


def test_empty_poll_list(client):
    response = client.get("/polls")
    assert response.status_code == 200
    assert response.json() == []


def test_poll_list_shows_newest_first(client, poll):
    second = client.post("/polls", json={
        "question": "Когда встречаемся?",
        "options": ["Утром", "Вечером"],
    }).json()
    response = client.get("/polls")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [second["id"], poll["id"]]
    assert all(item["closed"] is False for item in response.json())


def test_results_before_first_vote(client, poll):
    response = client.get(f"/polls/{poll['id']}/results")
    assert response.status_code == 200
    results = response.json()
    assert results["question"] == poll["question"]
    assert results["total_votes"] == 0
    assert len(results["options"]) == 3
    assert all(option["votes"] == 0 and option["percent"] == 0 for option in results["options"])


def test_votes_update_counts_and_percentages(client, poll):
    poll_id = poll["id"]
    for option_id in [1, 1, 2]:
        response = client.post(f"/polls/{poll_id}/votes", json={"option_id": option_id})
        assert response.status_code == 200
    results = response.json()
    assert results["total_votes"] == 3
    assert [option["votes"] for option in results["options"]] == [2, 1, 0]
    assert [option["percent"] for option in results["options"]] == [66.7, 33.3, 0.0]
    assert client.get(f"/polls/{poll_id}/results").json() == results


def test_reading_results_does_not_add_votes(client, poll):
    poll_id = poll["id"]
    client.post(f"/polls/{poll_id}/votes", json={"option_id": 1})
    first = client.get(f"/polls/{poll_id}/results").json()
    second = client.get(f"/polls/{poll_id}/results").json()
    assert first == second
    assert second["total_votes"] == 1


def test_votes_are_independent_between_polls(client, poll):
    other = client.post("/polls", json={
        "question": "Какой день?",
        "options": ["Понедельник", "Вторник"],
    }).json()
    client.post(f"/polls/{poll['id']}/votes", json={"option_id": 1})
    assert client.get(f"/polls/{poll['id']}/results").json()["total_votes"] == 1
    assert client.get(f"/polls/{other['id']}/results").json()["total_votes"] == 0


@pytest.mark.parametrize("payload", [
    {"option_id": 99},
    {"option_id": 0},
    {"option_id": -1},
    {"option_id": "1"},
    {"option_id": True},
    {},
], ids=["unknown-option", "zero", "negative", "string", "boolean", "missing-field"])
def test_invalid_vote_does_not_change_results(client, poll, payload):
    poll_id = poll["id"]
    response = client.post(f"/polls/{poll_id}/votes", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]
    assert client.get(f"/polls/{poll_id}/results").json()["total_votes"] == 0


def test_closed_poll_rejects_votes_and_preserves_results(client, poll):
    poll_id = poll["id"]
    client.post(f"/polls/{poll_id}/votes", json={"option_id": 1})
    before = client.get(f"/polls/{poll_id}/results").json()
    closed = client.post(f"/polls/{poll_id}/close")
    assert closed.status_code == 200
    assert closed.json()["closed"] is True
    assert client.get(f"/polls/{poll_id}").json()["closed"] is True
    rejected = client.post(f"/polls/{poll_id}/votes", json={"option_id": 2})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]
    assert client.get(f"/polls/{poll_id}/results").json() == before


def test_closing_twice_is_allowed(client, poll):
    path = f"/polls/{poll['id']}/close"
    first = client.post(path)
    second = client.post(path)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["closed"] is True


def test_closing_one_poll_does_not_close_another(client, poll):
    other = client.post("/polls", json={
        "question": "Какой формат?",
        "options": ["Онлайн", "Очно"],
    }).json()
    client.post(f"/polls/{poll['id']}/close")
    assert client.get(f"/polls/{other['id']}").json()["closed"] is False
    assert client.post(f"/polls/{other['id']}/votes", json={"option_id": 1}).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("GET", "/polls/999"),
    ("GET", "/polls/999/results"),
    ("POST", "/polls/999/close"),
])
def test_unknown_poll_in_other_routes(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 404
    assert response.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"question": "", "options": ["A", "B"]},
    {"question": "   ", "options": ["A", "B"]},
    {"question": "Q" * 201, "options": ["A", "B"]},
    {"question": "Question?", "options": ["A"]},
    {"question": "Question?", "options": [str(i) for i in range(9)]},
    {"question": "Question?", "options": ["A", "   "]},
    {"question": "Question?", "options": ["A", "B" * 101]},
    {"question": "Question?", "options": ["Python", " python "]},
    {"options": ["A", "B"]},
    {"question": "Question?"},
], ids=["empty-question", "blank-question", "long-question", "too-few-options", "too-many-options", "blank-option", "long-option", "duplicate-options", "missing-question", "missing-options"])
def test_invalid_poll_is_not_saved(client, payload):
    response = client.post("/polls", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]
    assert client.get("/polls").json() == []


def test_maximum_question_option_length_and_option_count(client):
    payload = {"question": "Q" * 200, "options": [str(i) + "x" * 99 for i in range(8)]}
    response = client.post("/polls", json=payload)
    assert response.status_code == 201
    assert response.json()["question"] == payload["question"]
    assert [option["text"] for option in response.json()["options"]] == payload["options"]


def test_question_and_options_are_trimmed(client):
    response = client.post("/polls", json={
        "question": "  Что изучать?  ",
        "options": [" Python ", " Go "],
    })
    assert response.status_code == 201
    assert response.json()["question"] == "Что изучать?"
    assert [option["text"] for option in response.json()["options"]] == ["Python", "Go"]
