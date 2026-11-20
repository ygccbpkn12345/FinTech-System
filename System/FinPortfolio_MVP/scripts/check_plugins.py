"""插件发现与清单检查（部署自检）。

用法： python scripts/check_plugins.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.plugin_registry import PluginRegistry  # noqa: E402
from app.core.paths import PLUGINS_DIR  # noqa: E402


def main() -> int:
    reg = PluginRegistry(PLUGINS_DIR)
    summary = reg.reload()
    print(f"plugins dir : {summary['plugins_dir']}")
    print(f"scanned     : {summary['total_scanned']}")
    for pid in summary["registered"]:
        p = reg.get(pid)
        caps = ", ".join(p.manifest.capabilities)
        print(f"  [READY] {pid:14s} v{p.manifest.version:5s} caps: {caps}")
        for w in p.warnings:
            print(f"          warning: {w}")
    for name, err in summary["failed"].items():
        print(f"  [ERROR] {name}: {err}")
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
