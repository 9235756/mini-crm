"""Pydantic-схемы запросов и ответов."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Generic, Literal, Optional, TypeVar

from pydantic import AfterValidator, BaseModel, EmailStr, Field

ClientStatus = Literal["active", "archived", "lead"]
DealStatus = Literal["new", "in_progress", "won", "lost"]

T = TypeVar("T")


def _check_datetime(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(value).isoformat(timespec="seconds")


def _check_date(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    date.fromisoformat(value)  # ValueError -> 422
    return value


DateStr = Annotated[Optional[str], AfterValidator(_check_date)]
CreatedAt = Annotated[
    Optional[str],
    AfterValidator(_check_datetime),
    Field(description="Для импорта истории (ISO-8601). По умолчанию — текущее время"),
]


# ---------- клиенты ----------
class ClientBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200, examples=["Иванов Иван Иванович"])
    company: Optional[str] = Field(None, max_length=200, examples=["ООО «Ромашка»"])
    email: Optional[EmailStr] = Field(None, examples=["ivanov@example.ru"])
    phone: Optional[str] = Field(None, max_length=40, examples=["+7 900 123-45-67"])
    status: ClientStatus = "active"
    notes: Optional[str] = None


class ClientCreate(ClientBase):
    created_at: CreatedAt = None


class ClientUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=200)
    company: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    status: Optional[ClientStatus] = None
    notes: Optional[str] = None


class Client(ClientBase):
    id: int
    email: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- сделки ----------
class DealBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=300, examples=["Поставка оборудования"])
    client_id: Optional[int] = Field(None, description="NULL — сделка без клиента")
    amount: float = Field(0, ge=0, examples=[150000])
    currency: str = Field("RUB", min_length=3, max_length=3)
    status: DealStatus = "new"
    close_date: DateStr = Field(None, examples=["2026-12-31"], description="ГГГГ-ММ-ДД")


class DealCreate(DealBase):
    created_at: CreatedAt = None


class DealUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    client_id: Optional[int] = None
    amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    status: Optional[DealStatus] = None
    close_date: DateStr = None


class DealClientLink(BaseModel):
    client_id: Optional[int] = Field(None, description="ID клиента; null — отвязать")


class DealStatusChange(BaseModel):
    status: DealStatus


class Deal(DealBase):
    id: int
    client_name: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- задачи ----------
class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=300, examples=["Позвонить клиенту"])
    description: Optional[str] = None
    due_date: DateStr = Field(None, examples=["2026-12-01"], description="ГГГГ-ММ-ДД")
    is_done: bool = False
    client_id: Optional[int] = None
    deal_id: Optional[int] = None


class TaskCreate(TaskBase):
    created_at: CreatedAt = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = None
    due_date: DateStr = None
    is_done: Optional[bool] = None
    client_id: Optional[int] = None
    deal_id: Optional[int] = None


class TaskDone(BaseModel):
    is_done: bool = True


class Task(TaskBase):
    id: int
    created_at: str


# ---------- списки ----------
class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
