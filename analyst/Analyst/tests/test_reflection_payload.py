from __future__ import annotations

from services.reflection_payload import build_reflection_payload


def test_reflection_payload_preserves_full_text_and_structured_role_details(tmp_path):
    long_manager = "经理反思：" + "需要保留的完整内容。" * 40
    risk_text = "风控反思：[CORRECTION] 扩大止损校验范围。"
    final_text = "最终决策反思：[LESSON] 不忽略成交量背离。"
    learned = "\n".join([long_manager, risk_text, final_text])
    state = {
        "learned_beliefs": learned,
        "weekly_summary": "周度策略：降低追高频率。",
        "reflection_details": {
            "routerReflection": '{"market_analyst": 0.4, "news_analyst": 0.1}',
            "routerWeights": {"market_analyst": 0.4, "news_analyst": 0.1},
            "roleReflections": [
                {"role": "经理 (Manager)", "content": long_manager},
                {"role": "风控 (Risk Manager)", "content": risk_text},
                {"role": "最终决策者 (Final Decision Maker)", "content": final_text},
            ],
        },
    }

    reflection = build_reflection_payload(state, current_router_weights={})

    assert reflection["summary"] == learned
    assert reflection["fullText"] == learned
    assert reflection["weeklySummary"] == "周度策略：降低追高频率。"
    assert reflection["roleReflections"][0]["content"] == long_manager
    assert len(reflection["roleReflections"]) == 3
    assert reflection["weightAdjustments"][0]["suggestedWeight"] == 0.4
    assert reflection["promptOptimizations"] == []
