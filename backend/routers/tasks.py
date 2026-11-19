from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from backend.database import get_db
from backend.schemas import Page, Task, TaskCreate, TaskDone, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _found(row: Optional[dict]) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return row


@router.get("", response_model=Page[Task])
def list_tasks(
    search: Optional[str] = Query(None, description="Название или описание — без учёта регистра"),
    is_done: Optional[bool] = None,
    client_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items, total = get_db().list_tasks(search, is_done, client_id, deal_id, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("", response_model=Task, status_code=201)
def create_task(payload: TaskCreate):
    return get_db().create_task(payload.model_dump())


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: int):
    return _found(get_db().get_task(task_id))


@router.put("/{task_id}", response_model=Task)
def update_task(task_id: int, payload: TaskUpdate):
    return _found(get_db().update_task(task_id, payload.model_dump(exclude_unset=True)))


@router.put("/{task_id}/done", response_model=Task, summary="Отметить выполненной / невыполненной")
def mark_done(task_id: int, payload: TaskDone):
    return _found(get_db().set_task_done(task_id, payload.is_done))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int):
    if not get_db().delete_task(task_id):
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return Response(status_code=204)
