"""插件注册表：扫描 plugins/ 目录、校验 manifest、登记算法。

设计要点：
- 只读取 manifest.yaml 并做 Pydantic 严格校验，绝不 import 插件代码；
- 单个插件损坏（manifest 缺失/非法/依赖缺失）只记录错误，不影响其他插件；
- python_executable 支持插件独立虚拟环境，缺失时回退后端解释器并标记警告；
- 新增插件后调用 reload() 或重启服务即可被发现。
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any, Optional

import yaml

from .manifest_schema import ManifestError, PluginManifest
from .paths import DEFAULT_ORIGINAL_CODE_ROOT, DEFAULT_PYTHON, PLUGINS_DIR


class RegisteredPlugin:
    def __init__(
        self,
        manifest: PluginManifest,
        plugin_dir: Path,
        status: str = "READY",
        error: Optional[str] = None,
        warnings: Optional[list[str]] = None,
        python_executable: Optional[str] = None,
    ) -> None:
        self.manifest = manifest
        self.plugin_dir = plugin_dir
        self.status = status            # READY / ERROR
        self.error = error
        self.warnings = warnings or []
        self.python_executable = python_executable or DEFAULT_PYTHON

    # ------------------------------------------------------------------
    def to_dict(self, detail: bool = False) -> dict[str, Any]:
        m = self.manifest
        info: dict[str, Any] = {
            "algorithm_id": m.id,
            "name": m.name,
            "version": m.version,
            "description": m.description,
            "framework": m.framework,
            "paper": m.paper.model_dump(exclude_none=True),
            "capabilities": list(m.capabilities),
            "dataset_requirements": [r.model_dump(exclude_none=True) for r in m.dataset_requirements],
            "status": self.status,
            "error": self.error,
            "warnings": self.warnings,
            "plugin_dir": str(self.plugin_dir),
            "python_executable": self.python_executable,
        }
        if detail:
            info["parameters"] = [p.model_dump(exclude_none=True) for p in m.parameters]
            info["outputs"] = self.manifest.outputs.model_dump(exclude_none=True)
            info["execution"] = {
                "adapter_file": self.manifest.execution.adapter_file,
                "original_code_dir": self.original_code_dir(),
                "default_timeout_seconds": self.manifest.execution.default_timeout_seconds,
                "max_timeout_seconds": self.manifest.execution.max_timeout_seconds,
            }
        return info

    def original_code_dir(self) -> Optional[Path]:
        sub = self.manifest.execution.original_code_subdir
        if not sub:
            return None
        p = Path(sub)
        if not p.is_absolute():
            p = DEFAULT_ORIGINAL_CODE_ROOT / p
        return p if p.exists() else None


class PluginRegistry:
    def __init__(self, plugins_dir: Path = PLUGINS_DIR) -> None:
        self.plugins_dir = Path(plugins_dir)
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._load_errors: dict[str, str] = {}   # plugin_dir_name -> error
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def reload(self) -> dict[str, Any]:
        """重新扫描 plugins 目录。返回扫描摘要。"""
        with self._lock:
            plugins: dict[str, RegisteredPlugin] = {}
            errors: dict[str, str] = {}
            if self.plugins_dir.is_dir():
                for entry in sorted(self.plugins_dir.iterdir()):
                    if not entry.is_dir() or entry.name.startswith(("_", ".")):
                        continue
                    try:
                        plugin = self._load_one(entry)
                    except ManifestError as e:
                        errors[entry.name] = f"invalid manifest: {e}"
                        continue
                    except Exception as e:  # noqa: BLE001 —— 任何插件故障都不能拖垮注册表
                        errors[entry.name] = f"{type(e).__name__}: {e}"
                        continue
                    if plugin.manifest.id in plugins:
                        errors[entry.name] = (
                            f"duplicate algorithm id '{plugin.manifest.id}' "
                            f"(also used by {plugins[plugin.manifest.id].plugin_dir.name})"
                        )
                        continue
                    plugins[plugin.manifest.id] = plugin
            self._plugins = plugins
            self._load_errors = errors
            return {
                "plugins_dir": str(self.plugins_dir),
                "registered": sorted(plugins.keys()),
                "failed": errors,
                "total_scanned": len(plugins) + len(errors),
            }

    # ------------------------------------------------------------------
    def _load_one(self, plugin_dir: Path) -> RegisteredPlugin:
        manifest_path = plugin_dir / "manifest.yaml"
        if not manifest_path.is_file():
            raise ManifestError(f"missing manifest.yaml in {plugin_dir}")

        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise ManifestError(f"YAML parse error: {e}") from e
        if not isinstance(raw, dict):
            raise ManifestError("manifest root must be a mapping")

        try:
            manifest = PluginManifest(**raw)
        except Exception as e:  # pydantic ValidationError 等
            raise ManifestError(str(e)) from e

        warnings: list[str] = []

        # adapter 文件必须存在（不执行，只检查）
        adapter_file = plugin_dir / manifest.execution.adapter_file
        if not adapter_file.is_file():
            raise ManifestError(
                f"adapter file '{manifest.execution.adapter_file}' not found in {plugin_dir}"
            )

        # 独立 Python 环境解析
        python_exe: Optional[str] = manifest.python_executable
        if python_exe:
            if not Path(python_exe).exists() and not shutil.which(python_exe):
                warnings.append(
                    f"configured python_executable '{python_exe}' not found; "
                    "falling back to backend interpreter"
                )
                python_exe = None
        resolved_python = python_exe or DEFAULT_PYTHON

        # 原始代码目录检查（可选）
        if manifest.execution.original_code_subdir:
            oc = (DEFAULT_ORIGINAL_CODE_ROOT / manifest.execution.original_code_subdir
                  if not Path(manifest.execution.original_code_subdir).is_absolute()
                  else Path(manifest.execution.original_code_subdir))
            if not oc.is_dir():
                warnings.append(
                    f"original code dir '{oc}' not found; execution will fail until configured"
                )

        return RegisteredPlugin(
            manifest=manifest,
            plugin_dir=plugin_dir,
            status="READY",
            warnings=warnings,
            python_executable=resolved_python,
        )

    # ------------------------------------------------------------------
    def list_plugins(self, detail: bool = False) -> list[dict[str, Any]]:
        out = [p.to_dict(detail=detail) for p in self._plugins.values()]
        for name, err in self._load_errors.items():
            out.append({
                "algorithm_id": name,
                "name": name,
                "version": None,
                "description": "",
                "framework": None,
                "paper": {},
                "capabilities": [],
                "dataset_requirements": [],
                "status": "ERROR",
                "error": err,
                "warnings": [],
                "plugin_dir": str(self.plugins_dir / name),
                "python_executable": None,
            })
        return sorted(out, key=lambda x: x["algorithm_id"])

    def get(self, algorithm_id: str) -> RegisteredPlugin:
        plugin = self._plugins.get(algorithm_id)
        if plugin is None:
            raise KeyError(f"algorithm '{algorithm_id}' not registered")
        return plugin

    def scan_summary(self) -> dict[str, Any]:
        return {
            "plugins_dir": str(self.plugins_dir),
            "registered": sorted(self._plugins.keys()),
            "failed": dict(self._load_errors),
            "total_scanned": len(self._plugins) + len(self._load_errors),
        }

    # ------------------------------------------------------------------
    def validate_params(self, algorithm_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """按 manifest 参数声明校验并合并用户参数（未知参数拒绝，越界拒绝）。"""
        plugin = self.get(algorithm_id)
        manifest = plugin.manifest
        known = {p.name: p for p in manifest.parameters}
        unknown = [k for k in params if k not in known]
        if unknown:
            raise ValueError(f"unknown parameters for '{algorithm_id}': {unknown}")

        merged: dict[str, Any] = manifest.default_params()
        for key, value in params.items():
            spec = known[key]
            merged[key] = self._coerce(spec, value)
        # required 参数必须有值
        for spec in manifest.parameters:
            if spec.required and merged.get(spec.name) in (None, ""):
                raise ValueError(f"parameter '{spec.name}' is required")
        return merged

    @staticmethod
    def _coerce(spec, value: Any) -> Any:
        try:
            if spec.type == "int":
                if isinstance(value, bool):
                    raise ValueError("bool given for int parameter")
                v = int(value)
                if not float(value).is_integer():
                    raise ValueError(f"'{value}' is not an integer")
            elif spec.type == "float":
                if isinstance(value, bool):
                    raise ValueError("bool given for float parameter")
                v = float(value)
            elif spec.type == "bool":
                if isinstance(value, str):
                    if value.lower() not in ("true", "false", "1", "0"):
                        raise ValueError(f"'{value}' is not a boolean")
                    v = value.lower() in ("true", "1")
                else:
                    v = bool(value)
            elif spec.type == "enum":
                v = str(value)
                if v not in (spec.choices or []):
                    raise ValueError(f"'{value}' not in {spec.choices}")
            else:
                v = str(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"parameter '{spec.name}' expects {spec.type}: {e}"
            ) from e

        if spec.type in ("int", "float"):
            if spec.min is not None and v < spec.min:
                raise ValueError(f"parameter '{spec.name}' = {v} below min {spec.min}")
            if spec.max is not None and v > spec.max:
                raise ValueError(f"parameter '{spec.name}' = {v} above max {spec.max}")
        return v


# 模块级单例；服务启动时 reload 一次
registry = PluginRegistry()
registry.reload()
