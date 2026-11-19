"""FastAPI-приложение мини-CRM."""

from __future__ import annotations

import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.database import get_db
from backend.routers import clients, deals, stats, tasks

app = FastAPI(
    title="Мини-CRM",
    description="Клиенты, сделки и задачи. SQLite + FastAPI. Отчёты выгружаются из GUI в Google Drive.",
    version="1.0.0",
)


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error_handler(_: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
    # Например, client_id указывает на несуществующего клиента
    return JSONResponse(status_code=400, content={"detail": f"Нарушение целостности данных: {exc}"})


@app.get("/health", tags=["service"])
def health() -> dict:
    get_db()._one("SELECT 1 AS ok")
    return {"status": "ok"}


app.include_router(clients.router)
app.include_router(deals.router)
app.include_router(tasks.router)
app.include_router(stats.router)
