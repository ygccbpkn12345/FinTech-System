"""插件扫描 / 注册 / 错误隔离测试。"""
import shutil
import textwrap

import pytest

from app.core.plugin_registry import PluginRegistry

GOOD_MANIFEST = textwrap.dedent("""
    schema_version: "1.0"
    id: good_algo
    name: Good
    version: "1.0"
    description: ok
    paper: {title: T}
    framework: numpy
    capabilities: [train]
    dataset_requirements: [{modalities: [prices]}]
    parameters: []
    outputs: {result_format: StandardPortfolioResult}
    execution: {adapter_file: adapter.py}
""")


def _make_plugin(dirs, manifest: str | None = None,
                 adapter: str = "class Adapter:\n    pass\n"):
    d = dirs
    d.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (d / "manifest.yaml").write_text(manifest, encoding="utf-8")
    (d / "adapter.py").write_text(adapter, encoding="utf-8")
    return d


def test_scan_and_register(tmp_path):
    root = tmp_path / "plugins"
    _make_plugin(root / "good", GOOD_MANIFEST)
    _make_plugin(root / "_ignored")          # 下划线目录应被跳过
    reg = PluginRegistry(root)
    summary = reg.reload()
    assert summary["registered"] == ["good_algo"]
    assert summary["failed"] == {}
    plugin = reg.get("good_algo")
    assert plugin.status == "READY"
    assert plugin.manifest.capabilities == ["train"]


def test_missing_manifest_isolated(tmp_path):
    root = tmp_path / "plugins"
    _make_plugin(root / "good", GOOD_MANIFEST)
    _make_plugin(root / "broken", None)       # 无 manifest
    reg = PluginRegistry(root)
    summary = reg.reload()
    assert "good_algo" in summary["registered"]
    assert "broken" in summary["failed"]
    assert "manifest" in summary["failed"]["broken"]


def test_invalid_yaml_isolated(tmp_path):
    root = tmp_path / "plugins"
    _make_plugin(root / "good", GOOD_MANIFEST)
    (root / "badyaml").mkdir()
    (root / "badyaml" / "manifest.yaml").write_text(":\n  - [unclosed", encoding="utf-8")
    (root / "badyaml" / "adapter.py").write_text("x = 1\n", encoding="utf-8")
    reg = PluginRegistry(root)
    summary = reg.reload()
    assert "badyaml" in summary["failed"]
    assert "good_algo" in summary["registered"]


def test_schema_violation_isolated(tmp_path):
    root = tmp_path / "plugins"
    _make_plugin(root / "good", GOOD_MANIFEST)
    bad = GOOD_MANIFEST.replace("capabilities: [train]", "capabilities: [time_travel]")
    _make_plugin(root / "badcap", bad)
    reg = PluginRegistry(root)
    summary = reg.reload()
    assert "badcap" in summary["failed"]
    assert "time_travel" in summary["failed"]["badcap"]


def test_duplicate_id_rejected(tmp_path):
    root = tmp_path / "plugins"
    _make_plugin(root / "one", GOOD_MANIFEST)
    _make_plugin(root / "two", GOOD_MANIFEST)   # 同 id
    reg = PluginRegistry(root)
    summary = reg.reload()
    assert summary["registered"] == ["good_algo"]
    assert "two" in summary["failed"]
    assert "duplicate" in summary["failed"]["two"]


def test_missing_adapter_reports_error(tmp_path):
    root = tmp_path / "plugins"
    d = _make_plugin(root / "noadapter", GOOD_MANIFEST)
    (d / "adapter.py").unlink()
    reg = PluginRegistry(root)
    reg.reload()
    with pytest.raises(KeyError):
        reg.get("good_algo")
    listing = reg.list_plugins()
    assert listing[0]["status"] == "ERROR"


def test_real_plugins_load(real_registry):
    ids = {p["algorithm_id"] for p in real_registry.list_plugins()}
    assert {"equal_weight", "asacpl", "hmmp"} <= ids
    ready = {p["algorithm_id"] for p in real_registry.list_plugins() if p["status"] == "READY"}
    assert {"equal_weight", "asacpl", "hmmp"} <= ready


def test_validate_params_coercion_and_bounds(real_registry):
    merged = real_registry.validate_params("equal_weight", {"top_k": "3"})
    assert merged["top_k"] == 3 and merged["cost_pct"] == 0.0
    with pytest.raises(ValueError):
        real_registry.validate_params("equal_weight", {"top_k": 999999})
    with pytest.raises(ValueError):
        real_registry.validate_params("equal_weight", {"unknown_param": 1})


def test_independent_python_env_configurable(tmp_path):
    """插件可配置独立解释器；解释器缺失时回退并给出警告。"""
    root = tmp_path / "plugins"
    manifest = GOOD_MANIFEST.replace(
        "framework: numpy",
        'framework: numpy\npython_executable: "Z:/nonexistent/venv/python.exe"',
    )
    _make_plugin(root / "good", manifest)
    reg = PluginRegistry(root)
    reg.reload()
    plugin = reg.get("good_algo")
    assert any("python_executable" in w for w in plugin.warnings)
    import sys
    assert plugin.python_executable == sys.executable   # 回退到后端解释器
