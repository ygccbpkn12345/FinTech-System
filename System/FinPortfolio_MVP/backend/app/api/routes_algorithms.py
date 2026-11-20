"""算法（插件）管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core.plugin_registry import registry

router = APIRouter(prefix="/api/algorithms", tags=["algorithms"])


@router.get("")
def list_algorithms():
    return registry.list_plugins()


@router.get("/registry/reload")
def reload_registry():
    summary = registry.reload()
    return summary


@router.get("/{algorithm_id}")
def get_algorithm(algorithm_id: str):
    try:
        plugin = registry.get(algorithm_id)
    except KeyError:
        raise HTTPException(404, f"algorithm '{algorithm_id}' not registered")
    return plugin.to_dict(detail=True)


@router.get("/{algorithm_id}/config")
def get_algorithm_config(algorithm_id: str):
    """参数 schema：前端据此动态生成表单。"""
    try:
        plugin = registry.get(algorithm_id)
    except KeyError:
        raise HTTPException(404, f"algorithm '{algorithm_id}' not registered")
    return {
        "algorithm_id": algorithm_id,
        "parameters": [p.model_dump(exclude_none=True) for p in plugin.manifest.parameters],
        "capabilities": list(plugin.manifest.capabilities),
        "default_params": plugin.manifest.default_params(),
        "warnings": plugin.warnings,
    }
