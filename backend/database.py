"""CRUD-слой на sqlite3 из стандартной библиотеки."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.models import ALL_TABLES, INDEXES


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _py_lower(value: Any) -> Any:
    """lower() из Python: в отличие от встроенного в SQLite, понимает кириллицу."""
    return value.lower() if isinstance(value, str) else value


class CRMDatabase:
    """Хранилище CRM. Таблицы создаются при инициализации."""

    CLIENT_FIELDS = ("full_name", "company", "email", "phone", "status", "notes")
    DEAL_FIELDS = ("title", "client_id", "amount", "currency", "status", "close_date")
    TASK_FIELDS = ("title", "description", "due_date", "is_done", "client_id", "deal_id")

    def __init__(self, db_path: str | os.PathLike) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function("py_lower", 1, _py_lower, deterministic=True)
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            for ddl in ALL_TABLES:
                self._conn.execute(ddl)
            for ddl in INDEXES:
                self._conn.execute(ddl)

    # ---------- служебное ----------
    def _query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def _execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _insert(self, table: str, data: dict) -> int:
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        cur = self._execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(data.values()))
        return int(cur.lastrowid)

    def _update(self, table: str, row_id: int, data: dict, touch: bool = True) -> bool:
        if touch:
            data = {**data, "updated_at": _now()}
        if not data:
            return self._one(f"SELECT id FROM {table} WHERE id = ?", (row_id,)) is not None
        sets = ", ".join(f"{k} = ?" for k in data)
        cur = self._execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), row_id])
        return cur.rowcount > 0

    def _list(
        self,
        table: str,
        where: list[str],
        params: list,
        limit: int,
        offset: int,
        order: str = "id",
    ) -> tuple[list[dict], int]:
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total = self._one(f"SELECT COUNT(*) AS n FROM {table}{clause}", params)["n"]
        rows = self._query(
            f"SELECT * FROM {table}{clause} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return rows, total

    @staticmethod
    def _search_clause(columns: tuple[str, ...], search: str) -> tuple[str, list]:
        needle = f"%{search.lower()}%"
        parts = [f"py_lower({c}) LIKE ? COLLATE NOCASE" for c in columns]
        return "(" + " OR ".join(parts) + ")", [needle] * len(columns)

    # ---------- клиенты ----------
    def create_client(self, data: dict) -> dict:
        now = data.get("created_at") or _now()
        row = {k: data.get(k) for k in self.CLIENT_FIELDS}
        row["status"] = row["status"] or "active"
        new_id = self._insert("clients", {**row, "created_at": now, "updated_at": now})
        return self.get_client(new_id)

    def get_client(self, client_id: int) -> dict | None:
        return self._one("SELECT * FROM clients WHERE id = ?", (client_id,))

    def list_clients(
        self,
        search: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where, params = [], []
        if search:
            clause, p = self._search_clause(("full_name", "company", "email", "phone"), search)
            where.append(clause)
            params += p
        if status:
            where.append("status = ?")
            params.append(status)
        return self._list("clients", where, params, limit, offset)

    def update_client(self, client_id: int, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if k in self.CLIENT_FIELDS}
        if not self._update("clients", client_id, fields):
            return None
        return self.get_client(client_id)

    def archive_client(self, client_id: int) -> dict | None:
        return self.update_client(client_id, {"status": "archived"})

    def delete_client(self, client_id: int) -> bool:
        return self._execute("DELETE FROM clients WHERE id = ?", (client_id,)).rowcount > 0

    # ---------- сделки ----------
    def create_deal(self, data: dict) -> dict:
        now = data.get("created_at") or _now()
        row = {k: data.get(k) for k in self.DEAL_FIELDS}
        row["status"] = row["status"] or "new"
        row["currency"] = row["currency"] or "RUB"
        row["amount"] = row["amount"] or 0
        new_id = self._insert("deals", {**row, "created_at": now, "updated_at": now})
        return self.get_deal(new_id)

    def get_deal(self, deal_id: int) -> dict | None:
        return self._one(
            "SELECT d.*, c.full_name AS client_name FROM deals d "
            "LEFT JOIN clients c ON c.id = d.client_id WHERE d.id = ?",
            (deal_id,),
        )

    def list_deals(
        self,
        search: str | None = None,
        status: str | None = None,
        client_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where, params = [], []
        if search:
            clause, p = self._search_clause(("d.title", "c.full_name", "c.company"), search)
            where.append(clause)
            params += p
        if status:
            where.append("d.status = ?")
            params.append(status)
        if client_id is not None:
            where.append("d.client_id = ?")
            params.append(client_id)
        table = "deals d LEFT JOIN clients c ON c.id = d.client_id"
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total = self._one(f"SELECT COUNT(*) AS n FROM {table}{clause}", params)["n"]
        rows = self._query(
            f"SELECT d.*, c.full_name AS client_name FROM {table}{clause} "
            "ORDER BY d.id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return rows, total

    def update_deal(self, deal_id: int, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if k in self.DEAL_FIELDS}
        if not self._update("deals", deal_id, fields):
            return None
        return self.get_deal(deal_id)

    def set_deal_client(self, deal_id: int, client_id: int | None) -> dict | None:
        """Привязка (client_id) или отвязка (None) клиента."""
        return self.update_deal(deal_id, {"client_id": client_id})

    def set_deal_status(self, deal_id: int, status: str) -> dict | None:
        return self.update_deal(deal_id, {"status": status})

    def delete_deal(self, deal_id: int) -> bool:
        return self._execute("DELETE FROM deals WHERE id = ?", (deal_id,)).rowcount > 0

    # ---------- задачи ----------
    def create_task(self, data: dict) -> dict:
        row = {k: data.get(k) for k in self.TASK_FIELDS}
        row["is_done"] = int(bool(row["is_done"]))
        new_id = self._insert("tasks", {**row, "created_at": data.get("created_at") or _now()})
        return self.get_task(new_id)

    def get_task(self, task_id: int) -> dict | None:
        return self._one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def list_tasks(
        self,
        search: str | None = None,
        is_done: bool | None = None,
        client_id: int | None = None,
        deal_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where, params = [], []
        if search:
            clause, p = self._search_clause(("title", "description"), search)
            where.append(clause)
            params += p
        if is_done is not None:
            where.append("is_done = ?")
            params.append(int(is_done))
        if client_id is not None:
            where.append("client_id = ?")
            params.append(client_id)
        if deal_id is not None:
            where.append("deal_id = ?")
            params.append(deal_id)
        return self._list("tasks", where, params, limit, offset)

    def update_task(self, task_id: int, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if k in self.TASK_FIELDS}
        if "is_done" in fields:
            fields["is_done"] = int(bool(fields["is_done"]))
        if not self._update("tasks", task_id, fields, touch=False):
            return None
        return self.get_task(task_id)

    def set_task_done(self, task_id: int, done: bool) -> dict | None:
        return self.update_task(task_id, {"is_done": done})

    def delete_task(self, task_id: int) -> bool:
        return self._execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount > 0

    # ---------- сводка ----------
    def stats(self) -> dict:
        def by(table: str, col: str) -> dict:
            rows = self._query(f"SELECT {col} AS k, COUNT(*) AS n FROM {table} GROUP BY {col}")
            return {str(r["k"]): r["n"] for r in rows}

        deals = self._one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM deals"
        )
        today = datetime.now().date().isoformat()
        overdue = self._one(
            "SELECT COUNT(*) AS n FROM tasks WHERE is_done = 0 AND due_date < ?", (today,)
        )["n"]
        return {
            "clients": {
                "total": self._one("SELECT COUNT(*) AS n FROM clients")["n"],
                "by_status": by("clients", "status"),
            },
            "deals": {
                "total": deals["n"],
                "total_amount": round(deals["total"], 2),
                "avg_amount": round(deals["total"] / deals["n"], 2) if deals["n"] else 0.0,
                "by_status": by("deals", "status"),
            },
            "tasks": {
                "total": self._one("SELECT COUNT(*) AS n FROM tasks")["n"],
                "done": self._one("SELECT COUNT(*) AS n FROM tasks WHERE is_done = 1")["n"],
                "overdue": overdue,
            },
        }

    def close(self) -> None:
        self._conn.close()


_DB_INSTANCE: CRMDatabase | None = None
_DB_LOCK = threading.Lock()


def get_db() -> CRMDatabase:
    """Единственный экземпляр БД на процесс. Путь — из переменной DATABASE_PATH."""
    global _DB_INSTANCE
    with _DB_LOCK:
        if _DB_INSTANCE is None:
            _DB_INSTANCE = CRMDatabase(os.getenv("DATABASE_PATH", "data/crm.db"))
        return _DB_INSTANCE
