"""实验管理：创建实验 → 派发子进程任务 → 结果校验与落盘。

一次实验 = 一个算法能力（train / backtest / ...）在一份数据集上的一次真实执行。
执行通过 TaskManager 在插件自己的 Python 解释器子进程中完成，
FastAPI 线程绝不直接运行算法代码。
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date as _date
from pathlib import Path
from typing import Any, Optional

from ..core import metrics as metrics_mod
from ..core.paths import EXPERIMENTS_DIR, PLUGIN_RUNNER_PATH
from ..core.plugin_registry import PluginRegistry, registry
from ..core.result_schema import StandardPortfolioResult, validate_result_dict
from ..database.json_store import JsonStore
from ..workers.task_manager import Task, TaskManager
from .dataset_service import DatasetError, DatasetService

CAPABILITY_RUNNABLE = ("train", "predict", "backtest", "stock_selection")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_split_date(value: str, field: str) -> _date:
    if not DATE_RE.fullmatch(value or ""):
        raise ExperimentError(
            f"data_split.{field} must be YYYY-MM-DD, got '{value}'"
        )
    try:
        return _date.fromisoformat(value)
    except ValueError as e:
        raise ExperimentError(f"data_split.{field} is not a valid date: {value}") from e


def validate_data_split(split: dict, dataset_meta: dict) -> Optional[dict]:
    """校验并归一化数据时间切片；全空返回 None（= 数据集全量）。

    规则（防泄漏、防越界，全部显式拒绝）：
    - 每个字段须为合法 YYYY-MM-DD；
    - train_start <= train_end、test_start <= test_end（区间内闭合）；
    - train_end < test_start（训练集不得与测试集重叠）；
    - 数据集 date_range 已知时，切片必须落在数据集范围内。
    """
    keys = ("train_start", "train_end", "test_start", "test_end")
    provided = {k: split.get(k) for k in keys if split.get(k)}
    if not provided:
        return None

    parsed = {k: _parse_split_date(v, k) for k, v in provided.items()}

    if "train_start" in parsed and "train_end" in parsed and parsed["train_start"] > parsed["train_end"]:
        raise ExperimentError("data_split.train_start > train_end")
    if "test_start" in parsed and "test_end" in parsed and parsed["test_start"] > parsed["test_end"]:
        raise ExperimentError("data_split.test_start > test_end")
    if "train_end" in parsed and "test_start" in parsed and parsed["train_end"] >= parsed["test_start"]:
        raise ExperimentError(
            "data_split requires train_end < test_start (no train/test overlap)"
        )

    dr = dataset_meta.get("date_range") or {}
    ds_start, ds_end = dr.get("start"), dr.get("end")
    if ds_start and ds_end:
        lo, hi = _parse_split_date(ds_start, "dataset.start"), _parse_split_date(ds_end, "dataset.end")
        for k, v in parsed.items():
            if v < lo or v > hi:
                raise ExperimentError(
                    f"data_split.{k}={split[k]} outside dataset range "
                    f"[{ds_start}, {ds_end}]"
                )
    return provided


class ExperimentError(Exception):
    pass


class ExperimentService:
    def __init__(
        self,
        task_manager: TaskManager,
        dataset_service: DatasetService,
        plugin_registry: PluginRegistry = None,
        experiments_dir: Path = EXPERIMENTS_DIR,
    ) -> None:
        self.tm = task_manager
        self.ds = dataset_service
        self.registry = plugin_registry or registry
        self.experiments_dir = Path(experiments_dir)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        self.tm.on_finish = self._on_task_finish

    # ------------------------------------------------------------------
    # 实验 CRUD
    # ------------------------------------------------------------------
    def _exp_dir(self, experiment_id: str) -> Path:
        return self.experiments_dir / experiment_id

    def _meta_path(self, experiment_id: str) -> Path:
        return self._exp_dir(experiment_id) / "meta.json"

    def list_experiments(self, limit: int = 500, name_prefix: str | None = None) -> list[dict]:
        out = []
        for meta_file in sorted(self.experiments_dir.glob("*/meta.json")):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if name_prefix is None or (meta.get("name") or "").startswith(name_prefix):
                    out.append(self._public_meta(meta))
            except (OSError, ValueError):
                continue
        out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return out[:limit]

    def get_experiment(self, experiment_id: str) -> dict:
        p = self._meta_path(experiment_id)
        if not p.is_file():
            raise ExperimentError(f"experiment '{experiment_id}' not found")
        meta = json.loads(p.read_text(encoding="utf-8"))
        return self._public_meta(meta, detail=True)

    @staticmethod
    def _public_meta(meta: dict, detail: bool = False) -> dict:
        pub = {
            "experiment_id": meta["experiment_id"],
            "name": meta.get("name"),
            "kind": meta.get("kind", "run"),          # run / import
            "algorithm_id": meta.get("algorithm_id"),
            "algorithm_name": meta.get("algorithm_name"),
            "algorithm_version": meta.get("algorithm_version"),
            "dataset_id": meta.get("dataset_id"),
            "dataset_name": meta.get("dataset_name"),
            "capability": meta.get("capability"),
            "backtest_mode": meta.get("backtest_mode"),
            "status": meta.get("status", "UNKNOWN"),
            "error": meta.get("error"),
            "created_at": meta.get("created_at"),
            "finished_at": meta.get("finished_at"),
            "result_summary": meta.get("result_summary"),
            "task_id": meta.get("task_id"),
            "data_split": meta.get("data_split"),
        }
        if detail:
            pub["params"] = meta.get("params")
            pub["notes"] = meta.get("notes", [])
            pub["artifacts"] = meta.get("artifacts", [])
            pub["import_source"] = meta.get("import_source")
        return pub

    def _save_meta(self, meta: dict) -> None:
        JsonStore(self._meta_path(meta["experiment_id"])).write(meta)

    def _load_meta(self, experiment_id: str) -> dict:
        p = self._meta_path(experiment_id)
        if not p.is_file():
            raise ExperimentError(f"experiment '{experiment_id}' not found")
        return json.loads(p.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # 创建并启动实验
    # ------------------------------------------------------------------
    def create_experiment(self, body: dict) -> dict:
        algorithm_id = body.get("algorithm_id")
        dataset_id = body.get("dataset_id")
        capability = body.get("capability", "train")
        params = body.get("params") or {}
        name = body.get("name") or None

        try:
            plugin = self.registry.get(algorithm_id)
        except KeyError as e:
            raise ExperimentError(str(e))
        if plugin.status != "READY":
            raise ExperimentError(f"algorithm '{algorithm_id}' not loadable: {plugin.error}")

        if capability not in plugin.manifest.capabilities:
            raise ExperimentError(
                f"algorithm '{algorithm_id}' does not declare capability '{capability}'; "
                f"declared: {plugin.manifest.capabilities}"
            )
        if capability not in CAPABILITY_RUNNABLE:
            raise ExperimentError(
                f"capability '{capability}' is a result-level capability; "
                f"runnable capabilities: {CAPABILITY_RUNNABLE}"
            )

        try:
            dataset_meta = self.ds.get(dataset_id)
        except DatasetError as e:
            raise ExperimentError(str(e))

        compat = self.ds.check_compatibility(plugin, dataset_id)
        if not compat["compatible"]:
            raise ExperimentError(
                f"dataset '{dataset_id}' incompatible with '{algorithm_id}': {compat['warnings']}"
            )

        try:
            merged_params = self.registry.validate_params(algorithm_id, params)
        except ValueError as e:
            raise ExperimentError(str(e))

        data_split = validate_data_split(body.get("data_split") or {}, dataset_meta)

        experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
        exp_dir = self._exp_dir(experiment_id)
        work_dir = exp_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        timeout = plugin.manifest.execution.default_timeout_seconds

        payload = {
            "experiment_id": experiment_id,
            "plugin_dir": str(plugin.plugin_dir),
            "adapter_file": plugin.manifest.execution.adapter_file,
            "capability": capability,
            "params": merged_params,
            "work_dir": str(work_dir),
            "output_dir": str(exp_dir),
            "dataset": {
                "dataset_id": dataset_meta["dataset_id"],
                "name": dataset_meta["name"],
                "market": dataset_meta["market"],
                "version": dataset_meta.get("version", "1"),
                "storage_path": dataset_meta["storage_path"],
                "storage_mode": dataset_meta.get("storage_mode", "reference"),
                "files": dataset_meta["files"],
                "available_modalities": dataset_meta["available_modalities"],
                "date_range": dataset_meta.get("date_range"),
                "assets": dataset_meta.get("assets"),
                # 实验级时间切片（可选）：适配器按自身加载流程消费
                "date_split": data_split,
            },
            "manifest": plugin.manifest.model_dump(mode="json", exclude_none=True),
        }
        payload_path = exp_dir / "payload.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 安全参数列表：绝不拼接 shell 字符串
        command = [
            plugin.python_executable,
            str(PLUGIN_RUNNER_PATH),
            str(payload_path),
        ]

        meta = {
            "experiment_id": experiment_id,
            "name": name or f"{plugin.manifest.name} {capability} {dataset_meta['name']}",
            "kind": "run",
            "algorithm_id": plugin.manifest.id,
            "algorithm_name": plugin.manifest.name,
            "algorithm_version": plugin.manifest.version,
            "dataset_id": dataset_meta["dataset_id"],
            "dataset_name": dataset_meta["name"],
            "capability": capability,
            "params": merged_params,
            "data_split": data_split,
            "status": "PENDING",
            "error": None,
            "created_at": time.time(),
            "finished_at": None,
            "task_id": experiment_id,
            "notes": plugin.warnings[:],
            "artifacts": [],
            "result_summary": None,
        }
        self._save_meta(meta)

        log_path = exp_dir / "run.log"
        self.tm.submit(
            task_id=experiment_id,
            command=command,
            cwd=str(plugin.plugin_dir),
            log_path=str(log_path),
            timeout_seconds=timeout,
        )
        return self.get_experiment(experiment_id)

    # ------------------------------------------------------------------
    # 任务完成回调（TaskManager worker 线程调用）
    # ------------------------------------------------------------------
    def _on_task_finish(self, task: Task) -> None:
        try:
            meta = self._load_meta(task.task_id)
        except ExperimentError:
            return
        meta["status"] = task.state
        meta["finished_at"] = task.finished_at
        if task.state == "FAILED":
            meta["error"] = task.error or f"exit code {task.returncode}"
        if task.state == "SUCCEEDED":
            result_path = self._exp_dir(task.task_id) / "result.json"
            if not result_path.is_file():
                meta["status"] = "FAILED"
                meta["error"] = (
                    "task exited 0 but no result.json was produced by the plugin adapter"
                )
            else:
                try:
                    raw = json.loads(result_path.read_text(encoding="utf-8"))
                    result = validate_result_dict(raw)
                    meta["backtest_mode"] = result.backtest_mode
                    meta["result_summary"] = self._summary(result)
                    meta["artifacts"] = [a.model_dump() for a in result.artifacts]
                    meta.setdefault("notes", []).extend(result.notes)
                except Exception as e:  # noqa: BLE001 —— 校验失败如实记录
                    meta["status"] = "FAILED"
                    meta["error"] = f"result.json failed schema validation: {e}"
        self._save_meta(meta)

    @staticmethod
    def _summary(result: StandardPortfolioResult) -> dict:
        keep = (
            "days", "annualized_return", "annualized_volatility", "sharpe_ratio",
            "sortino_ratio", "max_drawdown", "calmar_ratio", "cumulative_return",
            "avg_turnover", "avg_cash_ratio",
        )
        return {k: result.metrics[k] for k in keep if k in result.metrics}

    # ------------------------------------------------------------------
    # 结果读取
    # ------------------------------------------------------------------
    def get_result(self, experiment_id: str) -> StandardPortfolioResult:
        meta = self._load_meta(experiment_id)
        result_path = self._exp_dir(experiment_id) / "result.json"
        if not result_path.is_file():
            raise ExperimentError(
                f"experiment '{experiment_id}' (status={meta.get('status')}) has no result"
            )
        raw = json.loads(result_path.read_text(encoding="utf-8"))
        return validate_result_dict(raw)

    def delete_experiment(self, experiment_id: str) -> None:
        meta = self._load_meta(experiment_id)
        if meta.get("status") in ("PENDING", "RUNNING"):
            try:
                self.tm.cancel(experiment_id)
            except KeyError:
                pass
        import shutil
        shutil.rmtree(self._exp_dir(experiment_id), ignore_errors=True)

    # ------------------------------------------------------------------
    # 服务重启恢复：把中断的 RUNNING 实验标记为 FAILED
    # ------------------------------------------------------------------
    def recover_interrupted(self) -> int:
        count = 0
        for meta_file in self.experiments_dir.glob("*/meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("status") in ("PENDING", "RUNNING"):
                meta["status"] = "FAILED"
                meta["error"] = "backend restarted while task was running"
                meta["finished_at"] = time.time()
                self._save_meta(meta)
                count += 1
        return count
