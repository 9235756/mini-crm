"""Тесты API бэкенда на временной базе."""

import pytest
from fastapi.testclient import TestClient

import backend.database as database


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_DB_INSTANCE", database.CRMDatabase(tmp_path / "test.db"))
    from backend.main import app

    with TestClient(app) as c:
        yield c
    database._DB_INSTANCE.close()
    monkeypatch.setattr(database, "_DB_INSTANCE", None)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_client_crud_and_cyrillic_search(client):
    created = client.post("/clients", json={"full_name": "Иванов Пётр", "company": "ООО Ромашка"}).json()
    assert created["status"] == "active"
    assert client.get("/clients", params={"search": "ИВАНОВ"}).json()["total"] == 1
    assert client.get("/clients", params={"search": "ромаШКА"}).json()["total"] == 1
    assert client.get("/clients", params={"search": "сидоров"}).json()["total"] == 0

    updated = client.put(f"/clients/{created['id']}", json={"phone": "+7 900 1"}).json()
    assert updated["phone"] == "+7 900 1" and updated["full_name"] == "Иванов Пётр"
    assert client.post(f"/clients/{created['id']}/archive").json()["status"] == "archived"
    assert client.get("/clients", params={"status": "archived"}).json()["total"] == 1
    assert client.delete(f"/clients/{created['id']}").status_code == 204
    assert client.get(f"/clients/{created['id']}").status_code == 404


def test_deal_link_unlink_and_status(client):
    c = client.post("/clients", json={"full_name": "Сидорова Анна"}).json()
    d = client.post("/deals", json={"title": "Поставка", "amount": 1000, "client_id": c["id"]}).json()
    assert d["client_name"] == "Сидорова Анна"
    assert client.put(f"/deals/{d['id']}/client", json={"client_id": None}).json()["client_id"] is None
    assert client.put(f"/deals/{d['id']}/client", json={"client_id": c["id"]}).json()["client_id"] == c["id"]
    assert client.put(f"/deals/{d['id']}/status", json={"status": "won"}).json()["status"] == "won"
    assert client.get("/deals", params={"search": "сидорова"}).json()["total"] == 1
    assert client.get("/deals", params={"client_id": c["id"]}).json()["total"] == 1


def test_deal_without_client_and_validation(client):
    assert client.post("/deals", json={"title": "Без клиента", "amount": 5}).status_code == 201
    assert client.post("/deals", json={"title": "x", "client_id": 999}).status_code == 400
    assert client.post("/deals", json={"title": "x", "close_date": "31.12.2026"}).status_code == 422
    assert client.post("/deals", json={"title": "x", "status": "unknown"}).status_code == 422


def test_task_done_and_stats(client):
    t = client.post("/tasks", json={"title": "Позвонить", "due_date": "2020-01-01"}).json()
    assert t["is_done"] is False
    assert client.put(f"/tasks/{t['id']}/done", json={"is_done": True}).json()["is_done"] is True
    assert client.get("/tasks", params={"is_done": "true"}).json()["total"] == 1
    client.post("/deals", json={"title": "a", "amount": 100})
    client.post("/deals", json={"title": "b", "amount": 300})
    stats = client.get("/stats").json()
    assert stats["deals"]["total_amount"] == 400 and stats["deals"]["avg_amount"] == 200
    assert stats["tasks"]["done"] == 1


def test_pagination(client):
    for i in range(5):
        client.post("/clients", json={"full_name": f"Клиент {i}"})
    page = client.get("/clients", params={"limit": 2, "offset": 4}).json()
    assert page["total"] == 5 and len(page["items"]) == 1
