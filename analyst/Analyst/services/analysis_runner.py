"""真实模型单日分析封装（test 模式）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from config import apply_data_paths, build_runtime_config_view, get_config, get_path_config
from graph.train import TextGradTraderRunner
from services.runtime_config import build_data_overrides, build_llm_overrides
from services.reflection_payload import build_reflection_payload
from services.market_data_normalizer import normalize_market_frame
from services.symbol_service import STOCK_NAMES, normalize_symbol, validate_symbol_for_analysis
import utils

STOCK_INDUSTRY: dict[str, str] = {
    "000063": "通信设备",
    "000157": "工程机械",
    "000333": "家电",
    "000921": "家电",
    "000988": "激光设备",
}

_ANALYST_META: list[dict] = [
    {
        "id": "market",
        "name": "市场分析师",
        "role": "Market Analyst",
        "dataSource": "技术指标",
        "stateKey": "market_report",
        "routerKey": "market_analyst",
        "routerName": "市场",
    },
    {
        "id": "news",
        "name": "新闻分析师",
        "role": "News Analyst",
        "dataSource": "新闻舆情",
        "stateKey": "news_report",
        "routerKey": "news_analyst",
        "routerName": "新闻",
    },
    {
        "id": "industry",
        "name": "行业分析师",
        "role": "Industry Analyst",
        "dataSource": "行业因子",
        "stateKey": "industry_report",
        "routerKey": "industry_analyst",
        "routerName": "行业",
    },
    {
        "id": "company",
        "name": "公司分析师",
        "role": "Company Analyst",
        "dataSource": "财务报表",
        "stateKey": "fundamentals_report",
        "routerKey": "fundamentals_analyst",
        "routerName": "公司",
    },
    {
        "id": "momentum",
        "name": "股票动量分析师",
        "role": "Momentum Analyst",
        "dataSource": "相对强弱",
        "stateKey": "momentum_report",
        "routerKey": "momentum_analyst",
        "routerName": "股票动量",
    },
]


class AnalysisPreconditionError(ValueError):
    """分析前置条件不满足。"""


def _ensure_preconditions(
    stock_code: str,
    analysis_date: str,
    data_overrides: dict | None = None,
) -> str:
    try:
        return validate_symbol_for_analysis(stock_code, analysis_date, data_overrides)
    except ValueError as exc:
        raise AnalysisPreconditionError(str(exc)) from exc


def _parse_confidence(text: str) -> float:
    match = re.search(r"置信度[：:]\s*([0-9.]+)", text or "")
    if match:
        try:
            return round(float(match.group(1)), 2)
        except ValueError:
            pass
    return 0.5


def _parse_signal(text: str) -> str:
    content = text or ""
    if re.search(r"建议决策[：:]\s*\[?买入\]?", content):
        return "bullish"
    if re.search(r"建议决策[：:]\s*\[?观望\]?", content):
        return "neutral"
    if "买入" in content[:80]:
        return "bullish"
    return "neutral"


def _extract_summary(text: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return "暂无摘要"
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."


def _parse_router_weights(raw_router: str) -> dict[str, float]:
    if not raw_router:
        return {}

    try:
        parsed = json.loads(raw_router)
        if isinstance(parsed, dict):
            return {key: float(value) for key, value in parsed.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    matches = re.findall(r'"?([a-z_]+)"?\s*:\s*([0-9.]+)', raw_router)
    return {key: float(value) for key, value in matches}


def _parse_action_fields(text: str) -> dict[str, str | float]:
    action_match = re.search(r"操作[：:]\s*\[?(买入|观望)\]?", text or "")
    position_match = re.search(r"仓位[：:]\s*\[?(\d+(?:\.\d+)?)%?\]?", text or "")

    action = action_match.group(1) if action_match else "观望"
    position = f"{position_match.group(1)}%" if position_match else "0%"

    action_en = "Buy" if action == "买入" else "Hold"
    if action == "买入" and position != "0%":
        action_label = "谨慎买入" if float(position_match.group(1)) <= 20 else "买入"
        action_en = "Cautious Buy" if float(position_match.group(1)) <= 20 else "Buy"
    else:
        action_label = "观望"
        action_en = "Hold"

    return {
        "action": action_label,
        "actionEn": action_en,
        "position": position,
    }


def _load_technical_df(symbol: str, data_dir: Path) -> pd.DataFrame:
    path = data_dir / "technical_indicators" / f"{symbol}.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    if "trade_date" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"trade_date": "date"})
    return df.sort_values("date")


def _resolve_price_column(df: pd.DataFrame) -> str:
    for column in ("close", "current_price", "price"):
        if column in df.columns:
            return column
    raise AnalysisPreconditionError("technical_indicators CSV 缺少 close/current_price 字段")


def _resolve_volume_column(df: pd.DataFrame) -> str | None:
    for column in ("volume", "vol", "turnover"):
        if column in df.columns:
            return column
    return None


def _build_chart_data(symbol: str, analysis_date: str, data_dir: Path) -> list[dict]:
    df = _load_technical_df(symbol, data_dir)
    price_col = _resolve_price_column(df)
    volume_col = _resolve_volume_column(df)

    end_date = pd.to_datetime(analysis_date)
    filtered = df[df["date"] <= end_date].tail(30).copy()
    if filtered.empty:
        return []

    ma5_col = "close_5_sma" if "close_5_sma" in filtered.columns else None
    ma10_col = "close_10_sma" if "close_10_sma" in filtered.columns else None

    chart_data: list[dict] = []
    prices = filtered[price_col].astype(float).tolist()

    for index, row in filtered.reset_index(drop=True).iterrows():
        price = float(row[price_col])
        prev_price = prices[index - 1] if index > 0 else price
        ma5_slice = prices[max(0, index - 4): index + 1]
        ma10_slice = prices[max(0, index - 9): index + 1]

        volume_value = 0
        if volume_col is not None and pd.notna(row.get(volume_col)):
            volume_value = int(float(row[volume_col]))

        chart_data.append(
            {
                "date": pd.to_datetime(row["date"]).strftime("%Y-%m-%d"),
                "price": round(price, 2),
                "ma5": round(sum(ma5_slice) / len(ma5_slice), 2),
                "ma10": round(sum(ma10_slice) / len(ma10_slice), 2),
                "volume": volume_value,
                "up": price >= prev_price,
            }
        )

    return chart_data


def _build_stock_info(
    symbol: str,
    stock_code: str,
    analysis_date: str,
    data_dir: Path,
    result_dir: Path,
) -> dict:
    technical_df = _load_technical_df(symbol, data_dir)
    result_df = pd.read_csv(result_dir / f"{symbol}.csv", parse_dates=["date"])
    price_col = _resolve_price_column(technical_df)
    volume_col = _resolve_volume_column(technical_df)

    target_day = pd.to_datetime(analysis_date)
    tech_row = technical_df[technical_df["date"].dt.normalize() == target_day.normalize()]
    result_row = result_df[result_df["date"].dt.normalize() == target_day.normalize()]

    if tech_row.empty:
        raise AnalysisPreconditionError(f"technical_indicators 中不存在日期 {analysis_date}")

    tech = tech_row.iloc[-1]
    current_price = float(tech[price_col])
    high = float(tech["high"]) if "high" in tech and pd.notna(tech["high"]) else current_price
    low = float(tech["low"]) if "low" in tech and pd.notna(tech["low"]) else current_price

    change = 0.0
    change_percent = 0.0
    if not result_row.empty:
        result = result_row.iloc[-1]
        change_percent = float(result.get("pct_change", 0.0))
        if "current_price" in result and pd.notna(result["current_price"]):
            current_price = float(result["current_price"])
        change = round(current_price * change_percent / 100, 2)

    volume_text = "--"
    if volume_col and pd.notna(tech.get(volume_col)):
        volume_value = float(tech[volume_col]) / 10000
        volume_text = f"{volume_value:.2f} 万手"

    return {
        "code": stock_code if "." in stock_code else symbol,
        "name": STOCK_NAMES.get(symbol, symbol),
        "industry": STOCK_INDUSTRY.get(symbol, "综合"),
        "currentPrice": round(current_price, 2),
        "change": round(change, 2),
        "changePercent": round(change_percent, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "volume": volume_text,
        "volatility": round(abs(change_percent) * 10, 1) if change_percent else 0.0,
        "pe": 0.0,
        "marketCap": "--",
        "analysisDate": analysis_date,
    }


def map_final_state_to_frontend(
    final_state: dict,
    stock_code: str,
    analysis_date: str,
    runtime_config: dict | None = None,
    data_dir: Path | None = None,
    result_dir: Path | None = None,
) -> dict:
    symbol = normalize_symbol(stock_code)
    paths = get_path_config()
    data_dir = data_dir or paths["data_dir"]
    result_dir = result_dir or paths["result"]
    router_raw = str(final_state.get("router") or final_state.get("router_report") or "")
    router_map = _parse_router_weights(router_raw)

    analysts: list[dict] = []
    for meta in _ANALYST_META:
        report = str(final_state.get(meta["stateKey"], "") or "")
        weight = float(router_map.get(meta["routerKey"], 0.0))
        analysts.append(
            {
                "id": meta["id"],
                "name": meta["name"],
                "role": meta["role"],
                "dataSource": meta["dataSource"],
                "status": "completed" if report.strip() else "pending",
                "signal": _parse_signal(report),
                "confidence": _parse_confidence(report),
                "routeWeight": round(weight, 2),
                "summary": _extract_summary(report),
                "report": report or "暂无报告",
            }
        )

    router_weights = []
    for meta in _ANALYST_META:
        final_weight = float(router_map.get(meta["routerKey"], 0.0))
        confidence = _parse_confidence(str(final_state.get(meta["stateKey"], "")))
        router_weights.append(
            {
                "id": meta["id"],
                "name": meta["routerName"],
                "confidenceWeight": confidence,
                "historicalWeight": round(max(final_weight - 0.05, 0.0), 2),
                "finalWeight": round(final_weight, 2),
            }
        )

    investment_plan = str(final_state.get("investment_plan", "") or "")
    risk_plan = str(final_state.get("risk_plan", "") or "")
    final_decision_text = str(final_state.get("final_decision", "") or "")
    action_fields = _parse_action_fields(final_decision_text or investment_plan)

    payload = {
        "stock": _build_stock_info(symbol, stock_code, analysis_date, data_dir, result_dir),
        "chartData": _build_chart_data(symbol, analysis_date, data_dir),
        "analysts": analysts,
        "routerWeights": router_weights,
        "managerDecision": {
            "summary": _extract_summary(investment_plan, 180),
            "branches": [
                {
                    "name": "经理决策分支",
                    "condition": "综合五位分析师报告与路由权重",
                    "score": "+5" if action_fields["action"] != "观望" else "0",
                    "action": action_fields["action"],
                    "position": action_fields["position"],
                }
            ],
            "preReflection": [
                {
                    "title": "经理原始方案",
                    "status": "已完成",
                    "content": investment_plan or "暂无经理决策内容",
                }
            ],
        },
        "riskAssessment": {
            "summary": _extract_summary(risk_plan, 180) or "暂无风险评估摘要",
            "risks": [
                {
                    "type": "风控审计",
                    "level": "medium",
                    "description": _extract_summary(risk_plan, 300),
                    "mitigation": "请参考完整风控报告执行仓位与止损约束。",
                }
            ],
            "high": 0,
            "medium": 1 if risk_plan else 0,
            "low": 0,
        },
        "finalDecision": {
            **action_fields,
            "confidence": round(
                sum(item["confidence"] for item in analysts) / max(len(analysts), 1),
                2,
            ),
            "riskScore": 40,
            "holdingPeriod": "1-3 个月",
            "targetPrice": "--",
            "stopLoss": "--",
            "coreReason": _extract_summary(final_decision_text or investment_plan, 300),
            "keyRisks": [
                line.strip("- ").strip()
                for line in (risk_plan or "").splitlines()
                if line.strip().startswith("-")
            ][:5]
            or ["请参考 riskAssessment 查看完整风险项"],
        },
    }
    reflection = build_reflection_payload(final_state, router_map)
    if reflection.get("summary") or reflection.get("fullText") or reflection.get("roleReflections"):
        payload["reflection"] = reflection
    if runtime_config is not None:
        payload["runtimeConfig"] = runtime_config
    return payload


def run_full_analysis(
    stock_code: str,
    analysis_date: str,
    data_source: str = "local_file",
    llm_config: dict | None = None,
    data_config: dict | None = None,
    runtime_config: dict | None = None,
    task_id: str | None = None,
    on_module_event=None,
    defer_postprocessing: bool = False,
) -> dict:
    """
    执行 test 模式单日真实分析，并映射为前端结构。

    Args:
        stock_code: 股票代码
        analysis_date: 分析日期
        data_source: 数据源 (local_file / baostock / tushare)，前端传入
        llm_config: LLM 配置
        data_config: 数据配置
    """
    import os
    
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    data_overrides = build_data_overrides(data_config)
    llm_overrides = build_llm_overrides(llm_config)
    merged_overrides = {**data_overrides, **llm_overrides}
    config = dict(runtime_config) if runtime_config is not None else get_config(merged_overrides)

    # ================================================================
    # 🔽 从环境变量读取数据源配置
    # ================================================================
    
    # 如果前端没有传 data_source 或传的是 local_file，从环境变量读取
    if not data_source:
        data_source = config.get("data_source", "local_file")
    
    # 从环境变量读取爬虫和 API 配置
    crawl_url = config.get("crawl_url", "https://finance.eastmoney.com/")
    tushare_token = config.get("tushare_token", "")
    
    print(f"📊 当前数据源: {data_source}")
    if data_source == "baostock":
        print(f"   🌐 爬虫源: Baostock")
    elif data_source == "tushare":
        print(f"   🔗 Tushare Token: {tushare_token[:8] + '...' if tushare_token else '未配置'}")
    
    # ================================================================
    # 根据 data_source 获取数据
    # ================================================================
    
    if data_source != "local_file":
        configured_paths = get_path_config(config)
        temp_dir = configured_paths["data_dir"] / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        temp_result_dir = configured_paths["data_dir"] / "temp_result"
        temp_result_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"📊 从 {data_source} 获取股票 {stock_code} 的数据...")
        
        try:
            if data_source == "baostock":
                # ---- Baostock 爬虫 ----
                try:
                    import baostock as bs
                except ImportError:
                    raise ImportError("请先安装 baostock: pip install baostock")
                
                # 判断市场
                if stock_code.startswith('6'):
                    bs_code = f"sh.{stock_code}"
                else:
                    bs_code = f"sz.{stock_code}"
                
                # 登录
                lg = bs.login()
                if lg.error_code != '0':
                    raise RuntimeError(f"Baostock 登录失败: {lg.error_msg}")
                
                start = "2022-01-01"
                end = analysis_date
                
                print(f"   🌐 正在从 Baostock 获取: {stock_code}")
                
                # 获取数据
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date=start,
                    end_date=end,
                    frequency="d",
                    adjustflag="2"  # 前复权
                )
                
                if rs.error_code != '0':
                    bs.logout()
                    raise RuntimeError(f"获取数据失败: {rs.error_msg}")
                
                # 提取数据
                data_list = []
                while (rs.error_code == '0') and rs.next():
                    data_list.append(rs.get_row_data())
                bs.logout()
                
                if not data_list:
                    raise RuntimeError(f"Baostock 未获取到 {stock_code} 的数据")
                
                df = pd.DataFrame(data_list, columns=["date", "open", "high", "low", "close", "volume"])
                df = normalize_market_frame(df)
                
                print(f"   ✅ Baostock 获取成功: {len(df)} 条记录")
                
            elif data_source == "tushare":
                # ---- Tushare API ----
                try:
                    import tushare as ts
                except ImportError:
                    raise ImportError("请先安装 tushare: pip install tushare")
                
                if not tushare_token:
                    raise ValueError("Tushare 需要 token，请在系统配置中设置")
                
                ts.set_token(tushare_token)
                pro = ts.pro_api()
                
                start = "20220101"
                end = analysis_date.replace("-", "")
                
                print(f"   🔗 正在调用 Tushare API: {stock_code}")
                
                df = pro.daily(ts_code=f"{stock_code}.SZ", start_date=start, end_date=end)
                if df is None or df.empty:
                    df = pro.daily(ts_code=f"{stock_code}.SH", start_date=start, end_date=end)
                
                if df is None or df.empty:
                    raise ValueError(f"Tushare 未获取到 {stock_code} 的数据")
                
                df = df.rename(columns={
                    "trade_date": "date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "vol": "volume"
                })
                df = normalize_market_frame(df)
                
                print(f"   ✅ Tushare 获取成功: {len(df)} 条记录")
                
            else:
                raise ValueError(f"不支持的数据源: {data_source}")
            
            # ---- 保存数据到临时目录 ----
            temp_file = temp_dir / f"{stock_code}.csv"
            df.to_csv(temp_file, index=False)
            
            close = pd.to_numeric(df["close"], errors="coerce")
            result_df = pd.DataFrame({
                "date": df["date"],
                "pct_change": close.pct_change() * 100,
            }).dropna()
            
            result_file = temp_result_dir / f"{stock_code}.csv"
            result_df.to_csv(result_file, index=False)
            
            print(f"   ✅ 数据已保存: {temp_file}")
            
            # 下载目录只保存行情缓存；新闻、财报等仍位于配置的数据根目录。
            # 校验和模型必须使用同一份配置，不能把 data/temp 当作完整数据目录。
            
        except Exception as e:
            raise RuntimeError(f"从 {data_source} 获取数据失败: {e}")
    
    # ================================================================
    # 后面的代码不变，继续执行分析
    # ================================================================

    symbol = _ensure_preconditions(stock_code, analysis_date, config)

    if not config.get("api_key"):
        raise AnalysisPreconditionError(
            "未配置 API Key，请在系统配置或本次请求的 llmConfig 中提供。"
        )

    paths = get_path_config(config)
    runtime_view = build_runtime_config_view(config)

    old_data_dir = utils.DATA_DIR
    old_result_dir = utils.RESULT_DIR
    apply_data_paths(paths["data_dir"], paths["result"])

    try:
        runner = TextGradTraderRunner(
            config,
            symbol,
            model="test",
            task_id=task_id,
            module_output_root=paths["result"] / "module_results",
            on_module_event=on_module_event,
        )
        if defer_postprocessing:
            main_state, postprocess = runner.run_main(analysis_date, cash=10000.0, day_count=0)
            result = map_final_state_to_frontend(
                main_state,
                stock_code,
                analysis_date,
                runtime_config=runtime_view,
                data_dir=paths["data_dir"],
                result_dir=paths["result"],
            )

            def finish_postprocessing():
                old_post_data_dir = utils.DATA_DIR
                old_post_result_dir = utils.RESULT_DIR
                apply_data_paths(paths["data_dir"], paths["result"])
                try:
                    completed_state = postprocess(dict(main_state))
                    mapped = map_final_state_to_frontend(
                        completed_state, stock_code, analysis_date,
                        runtime_config=runtime_view,
                        data_dir=paths["data_dir"], result_dir=paths["result"],
                    )
                    return {
                        "reflection": mapped.get("reflection", {}),
                        "environmentSimulation": {
                            "actualOutcome": completed_state.get("actual_outcome", "")
                        },
                    }
                finally:
                    utils.DATA_DIR = old_post_data_dir
                    utils.RESULT_DIR = old_post_result_dir

            return result, finish_postprocessing

        final_state = runner.run(analysis_date, cash=10000.0, day_count=0)
        return map_final_state_to_frontend(
            final_state,
            stock_code,
            analysis_date,
            runtime_config=runtime_view,
            data_dir=paths["data_dir"],
            result_dir=paths["result"],
        )
    finally:
        utils.DATA_DIR = old_data_dir
        utils.RESULT_DIR = old_result_dir
