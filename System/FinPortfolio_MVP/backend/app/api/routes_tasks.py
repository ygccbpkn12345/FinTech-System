"""任务（子进程）状态 / 日志 / 取消 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _tm(request: Request):
    return request.app.state.tasks


@router.get("")
def list_tasks(request: Request, state: str | None = None):
    return _tm(request).list_tasks(state=state)


@router.get("/{task_id}/status")
def task_status(task_id: str, request: Request):
    try:
        return _tm(request).status(task_id)
    except KeyError:
        raise HTTPException(404, f"task '{task_id}' not found")


@router.get("/{task_id}/logs")
def task_logs(task_id: str, request: Request, tail: int = 200):
    try:
        return _tm(request).logs(task_id, tail=tail)
    except KeyError:
        raise HTTPException(404, f"task '{task_id}' not found")


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, request: Request):
    try:
        return _tm(request).cancel(task_id)
    except KeyError:
        raise HTTPException(404, f"task '{task_id}' not found")
