from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from backend.database import get_db
from backend.schemas import (
    Deal,
    DealClientLink,
    DealCreate,
    DealStatus,
    DealStatusChange,
    DealUpdate,
    Page,
)

router = APIRouter(prefix="/deals", tags=["deals"])


def _found(row: Optional[dict]) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return row


@router.get("", response_model=Page[Deal])
def list_deals(
    search: Optional[str] = Query(None, description="Название сделки, ФИО или компания клиента"),
    status: Optional[DealStatus] = None,
    client_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items, total = get_db().list_deals(search, status, client_id, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("", response_model=Deal, status_code=201)
def create_deal(payload: DealCreate):
    return get_db().create_deal(payload.model_dump())


@router.get("/{deal_id}", response_model=Deal)
def get_deal(deal_id: int):
    return _found(get_db().get_deal(deal_id))


@router.put("/{deal_id}", response_model=Deal)
def update_deal(deal_id: int, payload: DealUpdate):
    return _found(get_db().update_deal(deal_id, payload.model_dump(exclude_unset=True)))


@router.put("/{deal_id}/client", response_model=Deal, summary="Привязать или отвязать клиента")
def link_client(deal_id: int, payload: DealClientLink):
    return _found(get_db().set_deal_client(deal_id, payload.client_id))


@router.put("/{deal_id}/status", response_model=Deal, summary="Сменить статус сделки")
def change_status(deal_id: int, payload: DealStatusChange):
    return _found(get_db().set_deal_status(deal_id, payload.status))


@router.delete("/{deal_id}", status_code=204)
def delete_deal(deal_id: int):
    if not get_db().delete_deal(deal_id):
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return Response(status_code=204)
