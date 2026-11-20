"""插件执行器（独立子进程入口）。

用法：
    python plugin_runner.py <payload.json>

payload.json 由后端 experiment_service 生成：
    {
      "experiment_id": "...",
      "plugin_dir": "...",            # 插件目录
      "adapter_file": "adapter.py",   # manifest.execution.adapter_file
      "capability": "backtest",       # 调用的能力
      "params": {...},                # 已按 manifest 校验合并的参数
      "work_dir": "...",              # 插件专属工作目录（可写）
      "output_dir": "...",            # result.json 写入目录
      "dataset": {...},               # 数据集元信息与文件路径
      "manifest": {...}               # manifest 摘要
    }

本文件保持纯标准库：它运行在插件自己的 Python 环境里
（可能是 TensorFlow 或 PyTorch 独立虚拟环境），不能假设任何第三方包。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path


def _load_module_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python plugin_runner.py <payload.json>", file=sys.stderr)
        return 2

    payload_path = Path(argv[1]).resolve()
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[plugin_runner] cannot read payload: {e}", file=sys.stderr)
        return 2

    plugin_dir = Path(payload["plugin_dir"])
    adapter_file = payload.get("adapter_file", "adapter.py")
    capability = payload["capability"]
    output_dir = Path(payload["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) 注入纯标准库的插件基类 + 仅依赖 numpy 的指标模块（可选供 adapter 使用）
    core_dir = Path(__file__).resolve().parents[1] / "core"
    interface_path = core_dir / "plugin_interface.py"
    try:
        _load_module_by_path("finportfolio_plugin_interface", interface_path)
    except Exception:  # noqa: BLE001 —— 基类不可用时 adapter 仍可鸭子类型工作
        print(f"[plugin_runner] warning: cannot preload plugin_interface: {interface_path}")
    metrics_path = core_dir / "metrics.py"
    try:
        _load_module_by_path("finportfolio_metrics", metrics_path)
    except Exception:  # noqa: BLE001 —— 指标模块不可用时 adapter 需自行计算
        print(f"[plugin_runner] warning: cannot preload metrics module: {metrics_path}")

    # 2) 加载插件适配器（此时才执行插件目录代码 —— 插件目录属于受控研究代码）
    sys.path.insert(0, str(plugin_dir))
    adapter_path = plugin_dir / adapter_file
    if not adapter_path.is_file():
        print(f"[plugin_runner] adapter not found: {adapter_path}", file=sys.stderr)
        return 2
    try:
        module = _load_module_by_path("finportfolio_plugin_adapter", adapter_path)
    except Exception:
        traceback.print_exc()
        print(f"[plugin_runner] failed to import adapter {adapter_path}", file=sys.stderr)
        return 3

    adapter_cls = getattr(module, "Adapter", None)
    if adapter_cls is None:
        print(f"[plugin_runner] adapter file must define class 'Adapter'", file=sys.stderr)
        return 3

    # 3) 实例化并调用能力方法
    try:
        adapter = adapter_cls(payload)
    except Exception:
        traceback.print_exc()
        print("[plugin_runner] adapter __init__ failed", file=sys.stderr)
        return 3

    method = getattr(adapter, capability, None)
    if not callable(method):
        print(
            f"[plugin_runner] adapter has no method '{capability}' "
            f"(manifest declares it but adapter does not implement it)",
            file=sys.stderr,
        )
        return 3

    params = payload.get("params", {})
    try:
        result = method(params, payload)
    except Exception:
        traceback.print_exc()
        print(f"[plugin_runner] capability '{capability}' raised an exception", file=sys.stderr)
        return 4

    if not isinstance(result, dict):
        print(
            f"[plugin_runner] capability '{capability}' must return a dict "
            f"(StandardPortfolioResult), got {type(result).__name__}",
            file=sys.stderr,
        )
        return 4

    # 4) 写出结果（后端在任务完成后用 Pydantic 严格校验）
    result.setdefault("experiment_id", payload["experiment_id"])
    result.setdefault("algorithm_id", payload.get("manifest", {}).get("id", ""))
    result.setdefault("algorithm_version", payload.get("manifest", {}).get("version", "1"))
    result.setdefault("dataset_id", payload.get("dataset", {}).get("dataset_id", ""))
    result.setdefault("dataset_version", payload.get("dataset", {}).get("version", "1"))
    result.setdefault("configuration", params)

    result_path = output_dir / "result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[plugin_runner] result written to {result_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
