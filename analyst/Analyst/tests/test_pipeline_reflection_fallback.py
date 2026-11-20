import math

from services.pipeline_service import _build_mock_result


def test_mock_reflection_uses_canonical_complete_schema():
    reflection = _build_mock_result("600519.SH", "2026-08-11")["reflection"]

    assert len(reflection["roleReflections"]) == 3
    assert {item["role"] for item in reflection["roleReflections"]} == {
        "经理",
        "风险管理者",
        "最终决策者",
    }

    for item in reflection["weightAdjustments"]:
        assert item["analystId"] in {"news", "company"}
        assert math.isfinite(item["currentWeight"])
        assert math.isfinite(item["suggestedWeight"])
        assert 0 <= item["currentWeight"] <= 1
        assert 0 <= item["suggestedWeight"] <= 1


def test_mock_analysis_result_marks_its_source():
    result = _build_mock_result("000063", "2026-10-30")
    assert result["analysisMode"] == "mock"
