from fastapi import APIRouter

from backend.database import get_db

router = APIRouter(tags=["stats"])


@router.get("/stats", summary="Сводка по клиентам, сделкам и задачам")
def stats() -> dict:
    return get_db().stats()
