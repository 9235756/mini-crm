from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from backend.database import get_db
from backend.schemas import Client, ClientCreate, ClientStatus, ClientUpdate, Page

router = APIRouter(prefix="/clients", tags=["clients"])


def _found(row: Optional[dict]) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return row


@router.get("", response_model=Page[Client])
def list_clients(
    search: Optional[str] = Query(None, description="ФИО, компания, email, телефон — без учёта регистра"),
    status: Optional[ClientStatus] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items, total = get_db().list_clients(search, status, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("", response_model=Client, status_code=201)
def create_client(payload: ClientCreate):
    return get_db().create_client(payload.model_dump())


@router.get("/{client_id}", response_model=Client)
def get_client(client_id: int):
    return _found(get_db().get_client(client_id))


@router.put("/{client_id}", response_model=Client)
def update_client(client_id: int, payload: ClientUpdate):
    return _found(get_db().update_client(client_id, payload.model_dump(exclude_unset=True)))


@router.post("/{client_id}/archive", response_model=Client)
def archive_client(client_id: int):
    return _found(get_db().archive_client(client_id))


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: int):
    if not get_db().delete_client(client_id):
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return Response(status_code=204)
