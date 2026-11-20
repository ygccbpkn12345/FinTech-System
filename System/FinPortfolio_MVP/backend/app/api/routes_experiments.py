"""实验管理 API（创建 / 查询 / 导入论文结果）。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..core.plugin_registry import registry
from ..schemas.api_models import ExperimentCreate, ImportCreate
from ..services.experiment_service import ExperimentError
from ..services.import_service import ImportError_, import_result

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _svc(request: Request):
    return request.app.state.experiments


@router.post("")
def create_experiment(body: ExperimentCreate, request: Request):
    try:
        return _svc(request).create_experiment(body.model_dump())
    except ExperimentError as e:
        raise HTTPException(400, str(e))


@router.get("")
def list_experiments(request: Request, limit: int = 500, name_prefix: str | None = None):
    return _svc(request).list_experiments(limit=limit, name_prefix=name_prefix)


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str, request: Request):
    try:
        return _svc(request).get_experiment(experiment_id)
    except ExperimentError as e:
        raise HTTPException(404, str(e))


@router.delete("/{experiment_id}")
def delete_experiment(experiment_id: str, request: Request):
    try:
        _svc(request).delete_experiment(experiment_id)
    except ExperimentError as e:
        raise HTTPException(404, str(e))
    return {"deleted": experiment_id}


# ----------------------------------------------------------------------
# 论文结果 CSV 上传导入（原 MVP 功能，升级为 StandardPortfolioResult）
# ----------------------------------------------------------------------
@router.post("/upload")
async def upload_result(
    request: Request,
    algorithm_id: str = Form(...),
    name: str = Form("Imported paper result"),
    dataset_id: str = Form("unknown"),
    dataset_name: str = Form("unknown"),
    returns: UploadFile = File(...),
    weights: UploadFile | None = File(None),
    industry: UploadFile | None = File(None),
    intra: UploadFile | None = File(None),
):
    try:
        plugin = registry.get(algorithm_id)
    except KeyError:
        raise HTTPException(400, f"algorithm '{algorithm_id}' not registered")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        saved: dict[str, Path] = {}
        for key, fh in (("returns", returns), ("weights", weights),
                        ("industry", industry), ("intra", intra)):
            if fh is None:
                continue
            data = await fh.read(20_000_001)
            if len(data) > 20_000_000:
                raise HTTPException(400, f"{key} csv exceeds 20 MB")
            p = tmp_path / fh.filename
            p.write_bytes(data)
            saved[key] = p
        try:
            meta = _import_from_files(
                request, plugin, saved, name, dataset_id, dataset_name,
                source_note=f"uploaded files: {sorted(saved)}",
            )
        except (ImportError_, ValueError) as e:
            raise HTTPException(400, str(e))
    return meta


@router.post("/import-path")
def import_path(body: ImportCreate, request: Request):
    if os.environ.get("FINPORTFOLIO_ALLOW_PATH_IMPORT") != "1":
        raise HTTPException(
            403, "server-local path import disabled; set FINPORTFOLIO_ALLOW_PATH_IMPORT=1 "
                 "for trusted admin use"
        )
    try:
        plugin = registry.get(body.algorithm_id)
    except KeyError:
        raise HTTPException(400, f"algorithm '{body.algorithm_id}' not registered")
    src = Path(body.source_dir)
    saved: dict[str, Path] = {}
    mapping = {
        "returns": body.returns_file,
        "weights": body.weights_file,
        "industry": body.industry_file,
        "intra": body.intra_file,
    }
    for key, rel in mapping.items():
        if rel:
            p = src / rel
            if not p.is_file():
                raise HTTPException(400, f"file not found: {p}")
            saved[key] = p
    try:
        meta = _import_from_files(
            request, plugin, saved, body.name, body.dataset_id, body.dataset_name,
            source_note=f"server-local import from {src}",
        )
    except (ImportError_, ValueError) as e:
        raise HTTPException(400, str(e))
    return meta


def _import_from_files(request: Request, plugin, saved: dict, name: str,
                       dataset_id: str, dataset_name: str, source_note: str) -> dict:
    svc = _svc(request)
    returns_df = pd.read_csv(saved["returns"])

    weights_kind = None
    industry_df = intra_df = weights_df = None
    if "industry" in saved:
        industry_df = pd.read_csv(saved["industry"])
        weights_kind = "hmmp"
        if "intra" in saved:
            intra_df = pd.read_csv(saved["intra"], dtype=str)
    elif "weights" in saved:
        weights_df = pd.read_csv(saved["weights"])
        weights_kind = "asacpl"

    return import_result(
        algorithm_id=plugin.manifest.id,
        algorithm_name=plugin.manifest.name,
        algorithm_version=plugin.manifest.version,
        returns_df=returns_df,
        weights_kind=weights_kind,
        industry_df=industry_df,
        intra_df=intra_df if weights_kind == "hmmp" else weights_df,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        name=name,
        experiments_dir=svc.experiments_dir,
        source_note=source_note,
    )
