"""manifest 严格校验测试。"""
import pytest
from pydantic import ValidationError

from app.core.manifest_schema import ParameterSpec, PluginManifest


def _base_manifest(**over):
    data = {
        "schema_version": "1.0",
        "id": "demo_algo",
        "name": "Demo",
        "version": "1.0",
        "description": "demo plugin",
        "paper": {"title": "A Demo Paper"},
        "framework": "numpy",
        "capabilities": ["train"],
        "dataset_requirements": [{"modalities": ["prices"]}],
        "parameters": [],
        "outputs": {"result_format": "StandardPortfolioResult"},
        "execution": {"adapter_file": "adapter.py"},
    }
    data.update(over)
    return data


def test_valid_manifest():
    m = PluginManifest(**_base_manifest())
    assert m.id == "demo_algo"
    assert m.capabilities == ["train"]


def test_bad_id_rejected():
    with pytest.raises(ValidationError):
        PluginManifest(**_base_manifest(id="1Bad"))


def test_unknown_capability_rejected():
    with pytest.raises(ValidationError):
        PluginManifest(**_base_manifest(capabilities=["teleport"]))


def test_empty_capabilities_rejected():
    with pytest.raises(ValidationError):
        PluginManifest(**_base_manifest(capabilities=[]))


def test_unknown_modality_rejected():
    with pytest.raises(ValidationError):
        PluginManifest(**_base_manifest(
            dataset_requirements=[{"modalities": ["telepathy"]}]
        ))


def test_duplicate_parameter_rejected():
    with pytest.raises(ValidationError):
        PluginManifest(**_base_manifest(parameters=[
            {"name": "lr", "type": "float", "default": 0.1},
            {"name": "lr", "type": "float", "default": 0.2},
        ]))


def test_extra_top_level_field_rejected():
    with pytest.raises(ValidationError):
        PluginManifest(**_base_manifest(surprise="boom"))


# ---------------- ParameterSpec ----------------
def test_enum_param_requires_choices():
    with pytest.raises(ValidationError):
        ParameterSpec(name="mode", type="enum", default="a")


def test_enum_default_must_be_in_choices():
    with pytest.raises(ValidationError):
        ParameterSpec(name="mode", type="enum", default="x", choices=["a", "b"])


def test_numeric_default_range_enforced():
    with pytest.raises(ValidationError):
        ParameterSpec(name="lr", type="float", default=5.0, min=0.0, max=1.0)
    with pytest.raises(ValidationError):
        ParameterSpec(name="ep", type="int", default=1.5)


def test_bool_default_enforced():
    with pytest.raises(ValidationError):
        ParameterSpec(name="flag", type="bool", default="yes")


def test_param_name_must_be_identifier():
    with pytest.raises(ValidationError):
        ParameterSpec(name="bad-name", type="float", default=0.1)
