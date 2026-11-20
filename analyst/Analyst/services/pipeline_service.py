"""分析流水线服务（mock 实现 + 可选真实模型接入）。"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Callable

from dotenv import load_dotenv

ProgressCallback = Callable[[int, str, int], None]

logger = logging.getLogger(__name__)
_POSTPROCESSORS: dict[str, Callable[[], dict]] = {}

# 与 graph/graph_workflow.py 中分析师节点顺序保持一致，便于后续对接真实流程
PIPELINE_STEPS: list[tuple[str, int]] = [
    ("market_analyst", 10),
    ("news_analyst", 25),
    ("fundamentals_analyst", 40),
    ("industry_analyst", 55),
    ("momentum_analyst", 65),
    ("router", 75),
    ("manager", 85),
    ("risk_manager", 92),
    ("final_decision", 100),
]

_STOCK_PROFILES: dict[str, dict] = {
    "600519": {
        "name": "贵州茅台",
        "industry": "白酒",
        "currentPrice": 1688.50,
        "change": 12.30,
        "changePercent": 0.73,
        "high": 1695.00,
        "low": 1670.50,
        "volume": "125.68 万手",
        "volatility": 18.6,
        "pe": 28.6,
        "marketCap": "2.12 万亿元",
        "basePrice": 1620.0,
    },
    "000063": {
        "name": "中兴通讯",
        "industry": "通信设备",
        "currentPrice": 24.51,
        "change": -0.26,
        "changePercent": -1.05,
        "high": 24.88,
        "low": 24.12,
        "volume": "112.40 万手",
        "volatility": 24.3,
        "pe": 18.2,
        "marketCap": "1173 亿元",
        "basePrice": 23.80,
    },
}

_ANALYST_DEFINITIONS: list[dict] = [
    {
        "id": "market",
        "name": "市场分析师",
        "role": "Market Analyst",
        "dataSource": "技术指标",
        "signal": "bullish",
        "confidence": 0.78,
        "routeWeight": 0.22,
        "routerName": "市场",
        "historicalWeight": 0.72,
        "summary": "短期均线多头排列，量价配合良好，技术面偏强。",
        "report": (
            "过去5个交易日价格运行于 10 日与 20 日均线之上，MACD 柱状图持续放大，"
            "RSI 位于 58-62 区间，尚未进入超买。成交量温和放大，VWAP 支撑有效，"
            "短期趋势偏多，建议关注前高突破后的量价确认。"
        ),
    },
    {
        "id": "news",
        "name": "新闻分析师",
        "role": "News Analyst",
        "dataSource": "新闻舆情",
        "signal": "neutral",
        "confidence": 0.65,
        "routeWeight": 0.12,
        "routerName": "新闻",
        "historicalWeight": 0.68,
        "summary": "近期舆情整体中性偏暖，但缺少强催化，信息增量有限。",
        "report": (
            "近5日相关新闻以行业政策解读与公司经营动态为主，情绪温度 +0.28，"
            "未出现重大利空或超预期利好。北向资金小幅净流入，融资余额平稳，"
            "新闻面对股价影响偏中性，需等待更明确的业绩或政策催化。"
        ),
    },
    {
        "id": "industry",
        "name": "行业分析师",
        "role": "Industry Analyst",
        "dataSource": "行业因子",
        "signal": "bullish",
        "confidence": 0.72,
        "routeWeight": 0.18,
        "routerName": "行业",
        "historicalWeight": 0.70,
        "summary": "行业景气度边际改善，龙头份额稳定，政策环境偏友好。",
        "report": (
            "行业层面，需求端呈现结构性复苏，龙头公司渠道库存处于健康区间。"
            "政策端对高端消费与科技创新均有支撑，行业 Beta 略高于大盘。"
            "竞争格局未显著恶化，龙头定价权仍强，行业中长期逻辑 intact。"
        ),
    },
    {
        "id": "company",
        "name": "公司分析师",
        "role": "Company Analyst",
        "dataSource": "财务报表",
        "signal": "bullish",
        "confidence": 0.82,
        "routeWeight": 0.28,
        "routerName": "公司",
        "historicalWeight": 0.75,
        "summary": "盈利质量高，现金流充沛，分红稳定，基本面支撑较强。",
        "report": (
            "公司近四个季度营收与净利润保持双位数增长，毛利率维持高位，"
            "ROE 显著高于行业平均。资产负债表健康，经营现金流/净利润比值 > 1，"
            "分红率稳定。当前估值处于历史中位偏上，但盈利确定性较高。"
        ),
    },
    {
        "id": "momentum",
        "name": "股票动量分析师",
        "role": "Momentum Analyst",
        "dataSource": "相对强弱",
        "signal": "neutral",
        "confidence": 0.68,
        "routeWeight": 0.20,
        "routerName": "股票动量",
        "historicalWeight": 0.66,
        "summary": "相对大盘强弱中性，板块联动一般，暂未形成强势突破。",
        "report": (
            "近20日相对沪深300超额收益 +1.2%，动量评分处于中性区间。"
            "与行业对标股相关性 0.78，板块内排名中游偏上，"
            "尚未出现明显的动量加速信号，建议等待突破确认。"
        ),
    },
]


def _normalize_stock_code(stock_code: str) -> str:
    return stock_code.split(".")[0]


def _resolve_stock_profile(stock_code: str) -> dict:
    normalized = _normalize_stock_code(stock_code)
    if normalized in _STOCK_PROFILES:
        return dict(_STOCK_PROFILES[normalized])
    return {
        "name": f"股票 {normalized}",
        "industry": "综合",
        "currentPrice": 100.0,
        "change": 1.2,
        "changePercent": 1.2,
        "high": 101.5,
        "low": 98.8,
        "volume": "50.00 万手",
        "volatility": 20.0,
        "pe": 22.0,
        "marketCap": "500 亿元",
        "basePrice": 98.0,
    }


def _generate_chart_data(analysis_date: str, base_price: float, current_price: float) -> list[dict]:
    """生成 30 条模拟交易日 K 线数据。"""
    end_date = datetime.strptime(analysis_date, "%Y-%m-%d")
    prices: list[float] = []
    price = base_price

    for index in range(30):
        drift = (current_price - base_price) / 29
        noise = ((index % 5) - 2) * 0.003 * base_price
        price = max(base_price * 0.95, min(current_price * 1.02, base_price + drift * index + noise))
        prices.append(round(price, 2))

    prices[-1] = current_price
    chart_data: list[dict] = []

    for index, price in enumerate(prices):
        day_offset = 29 - index
        current_day = end_date - timedelta(days=day_offset)
        while current_day.weekday() >= 5:
            current_day -= timedelta(days=1)

        ma5_slice = prices[max(0, index - 4): index + 1]
        ma10_slice = prices[max(0, index - 9): index + 1]
        ma5 = round(sum(ma5_slice) / len(ma5_slice), 2)
        ma10 = round(sum(ma10_slice) / len(ma10_slice), 2)
        prev_price = prices[index - 1] if index > 0 else price

        chart_data.append(
            {
                "date": current_day.strftime("%Y-%m-%d"),
                "price": price,
                "ma5": ma5,
                "ma10": ma10,
                "volume": 800 + (index * 17) % 600,
                "up": price >= prev_price,
            }
        )

    return chart_data


def _build_analysts(stock_name: str) -> list[dict]:
    analysts: list[dict] = []
    for item in _ANALYST_DEFINITIONS:
        report = item["report"]
        if item["id"] == "company":
            report = report.replace("公司", stock_name, 1)
        analysts.append(
            {
                "id": item["id"],
                "name": item["name"],
                "role": item["role"],
                "dataSource": item["dataSource"],
                "status": "completed",
                "signal": item["signal"],
                "confidence": item["confidence"],
                "routeWeight": item["routeWeight"],
                "summary": item["summary"],
                "report": report,
            }
        )
    return analysts


def _build_router_weights() -> list[dict]:
    return [
        {
            "id": item["id"],
            "name": item["routerName"],
            "confidenceWeight": item["confidence"],
            "historicalWeight": item["historicalWeight"],
            "finalWeight": item["routeWeight"],
        }
        for item in _ANALYST_DEFINITIONS
    ]


def _build_mock_result(stock_code: str, analysis_date: str) -> dict:
    """构造与前端展示结构完全对齐的分析结果。"""
    profile = _resolve_stock_profile(stock_code)
    stock_name = profile["name"]
    current_price = profile["currentPrice"]

    return {
        "analysisMode": "mock",
        "stock": {
            "code": stock_code,
            "name": stock_name,
            "industry": profile["industry"],
            "currentPrice": current_price,
            "change": profile["change"],
            "changePercent": profile["changePercent"],
            "high": profile["high"],
            "low": profile["low"],
            "volume": profile["volume"],
            "volatility": profile["volatility"],
            "pe": profile["pe"],
            "marketCap": profile["marketCap"],
            "analysisDate": analysis_date,
        },
        "chartData": _generate_chart_data(
            analysis_date=analysis_date,
            base_price=profile["basePrice"],
            current_price=current_price,
        ),
        "analysts": _build_analysts(stock_name),
        "routerWeights": _build_router_weights(),
        "managerDecision": {
            "summary": "经理基于五位分析师意见进行树状推演，最终形成谨慎买入方案。",
            "branches": [
                {
                    "name": "基本面确认分支",
                    "condition": f"{stock_name} 基本面稳健，盈利能力较强",
                    "score": "+6",
                    "action": "进入等待评估流程",
                    "position": "观察",
                },
                {
                    "name": "技术共振分支",
                    "condition": "市场分析师与动量分析师信号偏强，短期趋势向上",
                    "score": "+4",
                    "action": "提升进攻意愿",
                    "position": "轻仓试探",
                },
                {
                    "name": "估值约束分支",
                    "condition": "当前 PE 高于历史中位，估值安全边际有限",
                    "score": "-3",
                    "action": "限制最大仓位",
                    "position": "8%-12%",
                },
            ],
            "preReflection": [
                {
                    "title": "少数派意见",
                    "status": "待改进",
                    "content": "新闻与动量分析师置信度相对较低，需要防止忽略弱信号。",
                },
                {
                    "title": "权重分配复核",
                    "status": "已确认",
                    "content": "公司分析师权重最高（28%），与市场强势信号形成有效互补。",
                },
            ],
        },
        "riskAssessment": {
            "summary": "存在 2 项中等风险，决策可执行但需持续监控。",
            "risks": [
                {
                    "type": "估值风险",
                    "level": "medium",
                    "description": "当前 PE 高于历史中位水平，估值安全边际有限。",
                    "mitigation": "控制仓位，避免一次性重仓。",
                },
                {
                    "type": "回撤风险",
                    "level": "medium",
                    "description": "短期涨幅较大，若遇大盘调整可能出现快速回撤。",
                    "mitigation": "设置机械止损位，严格执行纪律。",
                },
                {
                    "type": "政策风险",
                    "level": "low",
                    "description": "行业政策总体偏友好，但需关注消费刺激力度变化。",
                    "mitigation": "跟踪政策窗口期，动态调整仓位。",
                },
                {
                    "type": "流动性风险",
                    "level": "low",
                    "description": "龙头标的流动性充足，大额交易冲击有限。",
                    "mitigation": "正常分批建仓即可。",
                },
                {
                    "type": "信息风险",
                    "level": "low",
                    "description": "新闻面信息增量有限，可能存在预期差。",
                    "mitigation": "关注财报与行业数据验证。",
                },
            ],
            "high": 0,
            "medium": 2,
            "low": 3,
        },
        "finalDecision": {
            "action": "谨慎买入",
            "actionEn": "Cautious Buy",
            "position": "8%",
            "confidence": 0.71,
            "riskScore": 39,
            "holdingPeriod": "1-3 个月",
            "targetPrice": "1750 - 1820",
            "stopLoss": f"{round(current_price * 0.959, 2):.2f}（-4.1%）",
            "coreReason": (
                "五位分析师中 3 位偏多，2 位中性，无看空信号。"
                f"{stock_name} 基本面稳健，技术面短期偏强，但估值处于历史中高分位，因此建议谨慎买入。"
            ),
            "keyRisks": [
                "估值溢价较高，安全边际有限",
                "短期涨幅较大，存在回撤风险",
                "若大盘系统性下跌，防御能力有限",
            ],
        },
        "reflection": {
            "summary": "本次分析整体质量良好，但应降低低置信度分析师权重，并提升公司分析师贡献。",
            "weightAdjustments": [
                {
                    "analystId": "news",
                    "currentWeight": 0.14,
                    "suggestedWeight": 0.12,
                    "reason": "新闻分析师近期信息增量有限，建议下调权重。",
                },
                {
                    "analystId": "company",
                    "currentWeight": 0.25,
                    "suggestedWeight": 0.28,
                    "reason": "公司基本面信号强且稳定，建议适度上调权重。",
                },
            ],
            "roleReflections": [
                {
                    "role": "经理",
                    "content": "已复核少数派意见；后续应更明确量化新闻与动量弱信号对综合结论的影响。",
                },
                {
                    "role": "风险管理者",
                    "content": "应联合评估估值风险与系统性风险，并将目标价、止损价纳入一致性校验。",
                },
                {
                    "role": "最终决策者",
                    "content": "当前结论可用，但需在决策前再次核对仓位、目标价、止损价及低置信度信号。",
                },
            ],
            "managerBlindSpots": [
                "对新闻和动量弱信号关注不足",
            ],
            "riskSuggestions": [
                "风险管理者应加强对估值风险和系统性风险的联合评估",
            ],
            "promptOptimizations": [
                "经理 Prompt 中增加少数派分析师意见复核步骤",
                "最终决策者 Prompt 中增加目标价与止损价约束",
            ],
        },
    }


def _use_real_model() -> bool:
    load_dotenv()
    return os.getenv("BACKEND_USE_REAL_MODEL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_analysis_pipeline(
    stock_code: str,
    analysis_date: str,
    data_source: str = "local_file",
    on_progress: ProgressCallback | None = None,
    llm_config: dict | None = None,
    data_config: dict | None = None,
    runtime_config: dict | None = None,
    task_id: str | None = None,
    on_module_event=None,
) -> dict:
    """
    执行多分析师分析流水线。

    当 BACKEND_USE_REAL_MODEL=true 且 API Key 已配置时，调用真实 test 模式分析；
    真实分析失败时直接抛出异常，不回退 mock。
    
    Args:
        stock_code: 股票代码
        analysis_date: 分析日期
        data_source: 数据源 (local_file / baostock / tushare)  # 改这里
        on_progress: 进度回调
        llm_config: LLM 配置
        data_config: 数据配置
    """
    # 当 data_source 不是 local_file 时，强制走真实模式
    if data_source != "local_file" or _use_real_model():
        from services.analysis_runner import run_full_analysis

        if on_progress is not None:
            on_progress(1, "init", 5)

        prepared = run_full_analysis(
            stock_code,
            analysis_date,
            data_source=data_source,
            llm_config=llm_config,
            data_config=data_config,
            runtime_config=runtime_config,
            task_id=task_id,
            on_module_event=on_module_event,
            defer_postprocessing=True,
        )
        result, postprocessor = prepared
        if task_id and datetime.strptime(analysis_date, "%Y-%m-%d").date() < datetime.now().astimezone().date():
            _POSTPROCESSORS[task_id] = postprocessor

        if on_progress is not None:
            on_progress(len(PIPELINE_STEPS), "final_decision", 100)

        return {**result, "analysisMode": "model"}

    # Mock 模式：直接返回模拟数据
    for step_index, (node_name, progress) in enumerate(PIPELINE_STEPS, start=1):
        if on_progress is not None:
            on_progress(step_index, node_name, progress)
        time.sleep(0.3)

    result = _build_mock_result(stock_code, analysis_date)
    result.pop("reflection", None)
    return result


def run_reflection_pipeline(*, task_id: str, stock_code: str, analysis_date: str, **_) -> dict:
    postprocessor = _POSTPROCESSORS.pop(task_id, None)
    if postprocessor is not None:
        return postprocessor()
    mock = _build_mock_result(stock_code, analysis_date)
    return {"reflection": mock.get("reflection", {}), "environmentSimulation": {}}
