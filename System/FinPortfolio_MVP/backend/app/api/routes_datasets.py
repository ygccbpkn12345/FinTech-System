"""数据集管理 API。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request

from ..core.plugin_registry import registry
from ..schemas.api_models import DatasetRegister
from ..services.dataset_service import DatasetError

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _svc(request: Request):
    return request.app.state.datasets


@router.get("")
def list_datasets(request: Request):
    return _svc(request).list_datasets()


@router.post("")
def register_dataset(body: DatasetRegister, request: Request):
    svc = _svc(request)
    try:
        meta = svc.register(
            name=body.name,
            market=body.market,
            files=body.files,
            available_modalities=body.available_modalities,
            storage_mode=body.storage_mode,
            source_dir=body.source_dir,
            frequency=body.frequency,
            version=body.version,
            description=body.description,
            provenance=body.provenance,
            dataset_id=body.dataset_id,
        )
    except DatasetError as e:
        raise HTTPException(400, str(e))
    return meta


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    try:
        return _svc(request).get(dataset_id)
    except DatasetError as e:
        raise HTTPException(404, str(e))


@router.get("/{dataset_id}/price-coverage")
def price_coverage(dataset_id: str, symbol: str, before: date, request: Request):
    try:
        return {"sessions": _svc(request).count_price_sessions(dataset_id, symbol, before)}
    except DatasetError as exc:
        raise HTTPException(404, "没有可用的已登记行情") from exc


@router.post("/{dataset_id}/validate")
def validate_dataset(dataset_id: str, request: Request):
    try:
        return _svc(request).validate(dataset_id)
    except DatasetError as e:
        raise HTTPException(404, str(e))


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, request: Request):
    try:
        _svc(request).delete(dataset_id)
    except DatasetError as e:
        raise HTTPException(404, str(e))
    return {"deleted": dataset_id}


@router.get("/{dataset_id}/compatibility/{algorithm_id}")
def check_compatibility(dataset_id: str, algorithm_id: str, request: Request):
    try:
        plugin = registry.get(algorithm_id)
    except KeyError:
        raise HTTPException(404, f"algorithm '{algorithm_id}' not registered")
    try:
        return _svc(request).check_compatibility(plugin, dataset_id)
    except DatasetError as e:
        raise HTTPException(404, str(e))
