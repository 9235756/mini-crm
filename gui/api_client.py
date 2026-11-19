"""HTTP-клиент к бэкенду мини-CRM (requests)."""

from __future__ import annotations

import os
from typing import Any, Callable, Iterator

import requests

PAGE_SIZE = 1000


class APIError(RuntimeError):
    def __init__(self, status: int, detail: Any) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class CRMClient:
    def __init__(self, base_url: str | None = None, timeout: float = 15) -> None:
        self.base_url = (base_url or os.getenv("API_URL") or "http://localhost:8000").rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # ---------- транспорт ----------
    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self.session.request(
                method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs
            )
        except requests.ConnectionError as exc:
            raise APIError(
                0, f"Бэкенд недоступен по адресу {self.base_url}. Запустите: docker compose up -d --build"
            ) from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise APIError(resp.status_code, detail)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    @staticmethod
    def _clean(params: dict) -> dict:
        return {k: v for k, v in params.items() if v not in (None, "")}

    def health(self) -> bool:
        try:
            return self._request("GET", "/health").get("status") == "ok"
        except APIError:
            return False

    def stats(self) -> dict:
        return self._request("GET", "/stats")

    # ---------- списки и пагинация ----------
    def list(self, entity: str, **params) -> dict:
        return self._request("GET", f"/{entity}", params=self._clean(params))

    def iter_all(
        self,
        entity: str,
        progress: Callable[[int, int], None] | None = None,
        **params,
    ) -> Iterator[dict]:
        offset = 0
        while True:
            page = self.list(entity, limit=PAGE_SIZE, offset=offset, **params)
            yield from page["items"]
            offset += len(page["items"])
            if progress:
                progress(offset, page["total"])
            if not page["items"] or offset >= page["total"]:
                return

    def fetch_all(self, entity: str, progress=None, **params) -> list[dict]:
        return list(self.iter_all(entity, progress=progress, **params))

    # ---------- клиенты ----------
    def create_client(self, data: dict) -> dict:
        return self._request("POST", "/clients", json=data)

    def get_client(self, client_id: int) -> dict:
        return self._request("GET", f"/clients/{client_id}")

    def update_client(self, client_id: int, data: dict) -> dict:
        return self._request("PUT", f"/clients/{client_id}", json=data)

    def archive_client(self, client_id: int) -> dict:
        return self._request("POST", f"/clients/{client_id}/archive")

    def delete_client(self, client_id: int) -> None:
        self._request("DELETE", f"/clients/{client_id}")

    # ---------- сделки ----------
    def create_deal(self, data: dict) -> dict:
        return self._request("POST", "/deals", json=data)

    def update_deal(self, deal_id: int, data: dict) -> dict:
        return self._request("PUT", f"/deals/{deal_id}", json=data)

    def set_deal_client(self, deal_id: int, client_id: int | None) -> dict:
        return self._request("PUT", f"/deals/{deal_id}/client", json={"client_id": client_id})

    def set_deal_status(self, deal_id: int, status: str) -> dict:
        return self._request("PUT", f"/deals/{deal_id}/status", json={"status": status})

    def delete_deal(self, deal_id: int) -> None:
        self._request("DELETE", f"/deals/{deal_id}")

    # ---------- задачи ----------
    def create_task(self, data: dict) -> dict:
        return self._request("POST", "/tasks", json=data)

    def update_task(self, task_id: int, data: dict) -> dict:
        return self._request("PUT", f"/tasks/{task_id}", json=data)

    def set_task_done(self, task_id: int, done: bool = True) -> dict:
        return self._request("PUT", f"/tasks/{task_id}/done", json={"is_done": done})

    def delete_task(self, task_id: int) -> None:
        self._request("DELETE", f"/tasks/{task_id}")
