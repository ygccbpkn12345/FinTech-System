"""数据集注册与兼容性检查。

统一的是数据集「元信息与接口协议」；每个算法保留自己的数据加载和
预处理流程（ASACPL 的 CNN 张量、HMMP 的多模态特征互不强求一致）。
storage_path 支持两种模式：
- reference：登记本机已有研究数据目录（不复制，研究数据量大）；
- storage：上传/拷贝到 datasets/storage/<dataset_id>/ 下的受管文件。
"""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ..core.paths import DATASETS_DIR

DATE_COL_CANDIDATES = ("date", "Date", "datetime", "time", "timestamp")
TIC_COL_CANDIDATES = ("tic", "ticker", "symbol", "StockCode", "stock_code", "code")


class DatasetError(Exception):
    pass


def _find_col(columns, candidates) -> Optional[str]:
    lower = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


class DatasetService:
    def __init__(self, datasets_dir: Path = DATASETS_DIR) -> None:
        self.datasets_dir = Path(datasets_dir)
        self.storage_dir = self.datasets_dir / "storage"
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.datasets_dir / "index.json"

    # ------------------------------------------------------------------
    def _read_index(self) -> dict:
        try:
            import json
            raw = self._index_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {"datasets": []}

    def _write_index(self, index: dict) -> None:
        import json
        self._index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    def list_datasets(self) -> list[dict]:
        return self._read_index()["datasets"]

    def get(self, dataset_id: str) -> dict:
        for ds in self.list_datasets():
            if ds["dataset_id"] == dataset_id:
                return ds
        raise DatasetError(f"dataset '{dataset_id}' not found")

    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        market: str,
        files: dict[str, str],
        available_modalities: list[str],
        storage_mode: str = "reference",
        source_dir: Optional[str] = None,
        frequency: str = "daily",
        version: str = "1",
        description: str = "",
        provenance: str = "",
        dataset_id: Optional[str] = None,
    ) -> dict:
        """登记一个数据集。files: 逻辑名 → 相对 source_dir 的文件路径。"""
        dataset_id = dataset_id or re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
        if not dataset_id:
            raise DatasetError("cannot derive dataset_id from name")
        existing = {d["dataset_id"] for d in self.list_datasets()}
        if dataset_id in existing:
            suffix = 2
            while f"{dataset_id}_{suffix}" in existing:
                suffix += 1
            dataset_id = f"{dataset_id}_{suffix}"

        base_dir: Path
        stored_files: dict[str, str]
        if storage_mode == "copy":
            base_dir = self.storage_dir / dataset_id
            base_dir.mkdir(parents=True, exist_ok=True)
            src_root = Path(source_dir) if source_dir else Path.cwd()
            stored_files = {}
            for logical, rel in files.items():
                src = (src_root / rel).resolve()
                if not src.is_file():
                    raise DatasetError(f"file not found: {src}")
                dst = base_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                self._copy_with_retry(src, dst)
                stored_files[logical] = rel
        else:
            if not source_dir:
                raise DatasetError("reference mode requires source_dir")
            base_dir = Path(source_dir).resolve()
            if not base_dir.is_dir():
                raise DatasetError(f"source_dir not found: {base_dir}")
            stored_files = {}
            for logical, rel in files.items():
                p = (base_dir / rel).resolve()
                if not p.is_file():
                    raise DatasetError(f"file not found: {p}")
                stored_files[logical] = rel

        meta = {
            "dataset_id": dataset_id,
            "name": name,
            "market": market,
            "assets": [],
            "date_range": {"start": None, "end": None, "days": 0},
            "frequency": frequency,
            "feature_schema": [],
            "available_modalities": sorted(set(available_modalities)),
            "storage_mode": storage_mode,
            "storage_path": str(base_dir),
            "files": stored_files,
            "version": version,
            "description": description,
            "provenance": provenance,
        }
        # 自动探测行情文件元信息（首个可解析的逻辑文件为准）
        for logical in ("prices", "train_prices", "test_prices",
                        "industry_prices", "industry_news"):
            rel = stored_files.get(logical)
            if rel:
                try:
                    stats = self._price_csv_stats(base_dir / rel)
                except DatasetError:
                    continue
                meta["assets"] = stats.get("assets", [])
                if stats.get("date_range"):
                    meta["date_range"] = stats["date_range"]
                if stats.get("columns"):
                    meta["feature_schema"] = stats["columns"]
                break

        index = self._read_index()
        index["datasets"].append(meta)
        self._write_index(index)
        return meta

    # ------------------------------------------------------------------
    @staticmethod
    def _copy_with_retry(src: Path, dst: Path, attempts: int = 5) -> None:
        """Windows 下刚写完的文件可能被杀软/索引短暂占用，重试复制。"""
        import time as _time
        last_err: Exception | None = None
        for i in range(attempts):
            try:
                if src.resolve() == dst.resolve():
                    return          # 已在受管存储内，无需复制
                shutil.copyfile(src, dst)
                return
            except PermissionError as e:
                last_err = e
                _time.sleep(0.2 * (i + 1))
        raise DatasetError(f"cannot copy {src} -> {dst}: {last_err}")

    # ------------------------------------------------------------------
    def _price_csv_stats(self, path: Path) -> dict:
        try:
            df = pd.read_csv(path, usecols=lambda c: True, nrows=100000)
        except Exception as e:  # noqa: BLE001
            raise DatasetError(f"cannot read price csv {path}: {e}")
        date_col = _find_col(df.columns, DATE_COL_CANDIDATES)
        tic_col = _find_col(df.columns, TIC_COL_CANDIDATES)
        if not date_col:
            raise DatasetError(f"no date column in {path}")
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        info: dict[str, Any] = {"columns": [str(c) for c in df.columns]}
        if not dates.empty:
            info["date_range"] = {
                "start": str(dates.min().date()),
                "end": str(dates.max().date()),
                "days": int(dates.nunique()),
            }
        if tic_col:
            info["assets"] = sorted({str(x) for x in df[tic_col].dropna().unique()})
        return info

    # ------------------------------------------------------------------
    def file_path(self, dataset_id: str, logical: str) -> Path:
        meta = self.get(dataset_id)
        rel = meta["files"].get(logical)
        if rel is None:
            raise DatasetError(
                f"dataset '{dataset_id}' has no file '{logical}'; available: {list(meta['files'])}"
            )
        return Path(meta["storage_path"]) / rel

    # ------------------------------------------------------------------
    def count_price_sessions(self, dataset_id: str, symbol: str, before: date) -> int:
        path = self.file_path(dataset_id, "prices")
        try:
            prices = pd.read_csv(path, usecols=["date", "tic"], dtype={"tic": "string"})
            dates = pd.to_datetime(prices.loc[prices["tic"].str.strip().eq(symbol), "date"],
                                   format="%Y-%m-%d", errors="raise")
        except (OSError, ValueError):
            return 0
        prior = dates[dates < pd.Timestamp(before)]
        return 0 if prior.duplicated().any() else len(prior)

    def validate(self, dataset_id: str) -> dict:
        """格式 / 时间范围 / 缺失字段检查。"""
        meta = self.get(dataset_id)
        report: dict[str, Any] = {
            "dataset_id": dataset_id,
            "valid": True,
            "problems": [],
            "file_reports": {},
        }
        base = Path(meta["storage_path"])
        if not base.is_dir():
            report["problems"].append(f"storage path missing: {base}")
            report["valid"] = False
            return report

        for logical, rel in meta["files"].items():
            p = base / rel
            fr: dict[str, Any] = {"path": str(p), "exists": p.is_file()}
            if not p.is_file():
                report["problems"].append(f"missing file '{logical}': {p}")
                report["valid"] = False
                report["file_reports"][logical] = fr
                continue
            if p.suffix.lower() == ".csv":
                try:
                    head = pd.read_csv(p, nrows=5)
                    fr["columns"] = [str(c) for c in head.columns]
                    fr["rows_head"] = int(len(head))
                    full_dates = None
                    date_col = _find_col(head.columns, DATE_COL_CANDIDATES)
                    if date_col:
                        df = pd.read_csv(p, usecols=[date_col])
                        dt = pd.to_datetime(df[date_col], errors="coerce")
                        fr["date_range"] = {
                            "start": str(dt.min().date()) if dt.notna().any() else None,
                            "end": str(dt.max().date()) if dt.notna().any() else None,
                            "unique_days": int(dt.nunique()),
                            "invalid_dates": int(dt.isna().sum()),
                        }
                        if dt.isna().all():
                            report["problems"].append(
                                f"'{logical}': date column '{date_col}' has no valid dates"
                            )
                            report["valid"] = False
                except Exception as e:  # noqa: BLE001
                    fr["error"] = str(e)
                    report["problems"].append(f"'{logical}' unreadable: {e}")
                    report["valid"] = False
            report["file_reports"][logical] = fr

        if not meta["available_modalities"]:
            report["problems"].append("no modality declared")
            report["valid"] = False
        return report

    # ------------------------------------------------------------------
    def check_compatibility(self, plugin, dataset_id: str) -> dict:
        """算法 manifest 要求 vs 数据集实际。不修改任何一方。"""
        ds = self.get(dataset_id)
        warnings: list[str] = []
        compatible = False
        matched_req = None
        for req in plugin.manifest.dataset_requirements:
            missing_mod = [m for m in req.modalities if m not in ds["available_modalities"]]
            if missing_mod:
                continue
            if req.markets and ds["market"] not in req.markets:
                warnings.append(
                    f"market mismatch: algorithm expects {req.markets}, dataset is '{ds['market']}'"
                )
            fields = req.required_fields or []
            schema = set(ds.get("feature_schema") or [])
            missing_fields = [f for f in fields if f not in schema]
            if missing_fields and schema:
                warnings.append(f"fields not verified in dataset schema: {missing_fields}")
            compatible = True
            matched_req = req.modalities
            break
        if not compatible:
            have = ds["available_modalities"]
            need = plugin.manifest.dataset_requirements[0].modalities
            warnings.insert(
                0,
                f"modality mismatch: algorithm needs {need}, dataset provides {have}",
            )
        if ds.get("date_range", {}).get("days", 0) == 0:
            warnings.append("dataset date range unknown/unparsed")
        return {
            "algorithm_id": plugin.manifest.id,
            "dataset_id": dataset_id,
            "compatible": compatible,
            "matched_modalities": matched_req,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    def compatible_datasets(self, plugin) -> list[dict]:
        out = []
        for ds in self.list_datasets():
            check = self.check_compatibility(plugin, ds["dataset_id"])
            out.append({
                "dataset_id": ds["dataset_id"],
                "name": ds["name"],
                "market": ds["market"],
                "compatible": check["compatible"],
                "warnings": check["warnings"],
            })
        return out

    # ------------------------------------------------------------------
    def delete(self, dataset_id: str) -> None:
        index = self._read_index()
        before = len(index["datasets"])
        index["datasets"] = [d for d in index["datasets"] if d["dataset_id"] != dataset_id]
        if len(index["datasets"]) == before:
            raise DatasetError(f"dataset '{dataset_id}' not found")
        self._write_index(index)
