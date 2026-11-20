"""Build the public reflection payload without truncating model output."""

from __future__ import annotations

from typing import Any


def build_reflection_payload(
    final_state: dict[str, Any],
    current_router_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    learned_beliefs = str(final_state.get("learned_beliefs", "") or "")
    weekly_summary = str(final_state.get("weekly_summary", "") or "")
    details = final_state.get("reflection_details") or {}
    role_reflections = list(details.get("roleReflections") or [])
    suggested_weights = details.get("routerWeights") or {}
    current_router_weights = current_router_weights or {}
    weight_adjustments = [
        {
            "analystId": analyst_id,
            "currentWeight": float(current_router_weights.get(analyst_id, 0.0)),
            "suggestedWeight": float(weight),
            "reason": "根据本次实际结果重新评估分析师可信度",
        }
        for analyst_id, weight in suggested_weights.items()
        if isinstance(weight, (int, float))
    ]
    risk_reflections = [
        item.get("content", "")
        for item in role_reflections
        if "风控" in str(item.get("role", "")) and item.get("content")
    ]
    full_text = learned_beliefs or "本次暂无显著反思更新"
    return {
        "summary": full_text,
        "metaReflection": full_text,
        "fullText": full_text,
        "routerReflection": str(details.get("routerReflection", "") or ""),
        "roleReflections": role_reflections,
        "weeklySummary": weekly_summary,
        "weightAdjustments": weight_adjustments,
        "managerBlindSpots": [],
        "riskSuggestions": risk_reflections,
        "promptOptimizations": [],
    }
