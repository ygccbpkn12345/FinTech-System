"""股票数据状态扫描与校验。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import get_path_config

MEMORY_COLLECTIONS = (
    "router_memory",
    "manager_memory",
    "risk_memory",
    "final_memory",
)

STOCK_NAMES: dict[str, str] = {
    "000063": "中兴通讯",
    "000157": "中联重科",
    "000333": "美的集团",
    "000921": "海信家电",
    "000988": "华工科技",
}

MISSING_LABELS = {
    "technical_indicators": "technical_indicators（技术指标 CSV）",
    "result": "result（涨跌幅/结果 CSV）",
    "news": "news（新闻 CSV）",
    "fundamentals": "fundamentals（三张财报表 CSV）",
}


def normalize_symbol(symbol: str) -> str:
    return symbol.split(".")[0].strip()


def _paths(data_overrides: dict | None = None) -> dict[str, Path]:
    return get_path_config(data_overrides)


def _has_memory(symbol: str, mode: str, data_cache: Path) -> bool:
    base = data_cache / symbol / mode
    if not base.is_dir():
        return False
    return all((base / name).is_dir() for name in MEMORY_COLLECTIONS)


def _has_fundamentals(symbol: str, data_dir: Path) -> bool:
    bases = (
        data_dir / "fundamentals" / "Balance Sheet" / f"{symbol}.csv",
        data_dir / "fundamentals" / "Income Statement" / f"{symbol}.csv",
        data_dir / "fundamentals" / "Cash Flow Statement" / f"{symbol}.csv",
    )
    return all(path.is_file() for path in bases)


def _read_csv_dates(path: Path) -> set[str]:
    df = pd.read_csv(path, parse_dates=["date"])
    return set(pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"))


def get_symbol_data_status(symbol: str, data_overrides: dict | None = None) -> dict:
    code = normalize_symbol(symbol)
    paths = _paths(data_overrides)
    data_dir = paths["data_dir"]
    result_dir = paths["result"]
    data_cache = paths["data_cache"]

    has_technical = (data_dir / "technical_indicators" / f"{code}.csv").is_file()
    has_news = (data_dir / "news" / f"{code}.csv").is_file()
    has_fundamentals = _has_fundamentals(code, data_dir)
    has_result = (result_dir / f"{code}.csv").is_file()
    has_train = _has_memory(code, "train", data_cache)
    has_test = _has_memory(code, "test", data_cache)

    missing: list[str] = []
    if not has_technical:
        missing.append("technical_indicators")
    if not has_result:
        missing.append("result")
    if not has_news:
        missing.append("news")
    if not has_fundamentals:
        missing.append("fundamentals")
    # test_memory 不再作为必须项，只记录状态

    available = not missing
    message = "数据齐全，可发起分析。" if available else (
        "当前股票缺少本地数据，请上传："
        + "、".join(MISSING_LABELS[item] for item in missing)
        + "。"
    )

    return {
        "code": code,
        "name": STOCK_NAMES.get(code, code),
        "hasTechnicalData": has_technical,
        "hasNewsData": has_news,
        "hasFundamentalData": has_fundamentals,
        "hasResultData": has_result,
        "hasTrainMemory": has_train,
        "hasTestMemory": has_test,
        "available": available,
        "recommended": available,
        "missing": missing,
        "message": message,
    }


def list_symbols(data_overrides: dict | None = None) -> list[dict]:
    paths = _paths(data_overrides)
    data_dir = paths["data_dir"]
    result_dir = paths["result"]
    data_cache = paths["data_cache"]

    technical_dir = data_dir / "technical_indicators"
    technical_codes = (
        {path.stem for path in technical_dir.glob("*.csv")}
        if technical_dir.is_dir()
        else set()
    )
    result_codes = (
        {path.stem for path in result_dir.glob("*.csv")}
        if result_dir.is_dir()
        else set()
    )
    news_codes = (
        {path.stem for path in (data_dir / "news").glob("*.csv")}
        if (data_dir / "news").is_dir()
        else set()
    )
    cache_codes = (
        {path.name for path in data_cache.iterdir() if path.is_dir()}
        if data_cache.is_dir()
        else set()
    )

    all_codes = sorted(technical_codes | result_codes | news_codes | cache_codes)
    symbols: list[dict] = []

    for code in all_codes:
        status = get_symbol_data_status(code, data_overrides)
        symbols.append(status)

    symbols.sort(key=lambda item: (not item["recommended"], item["code"]))
    return symbols


def get_recommended_codes(data_overrides: dict | None = None) -> list[str]:
    return [item["code"] for item in list_symbols(data_overrides) if item["available"]]


def get_available_dates(symbol: str, data_overrides: dict | None = None) -> dict:
    code = normalize_symbol(symbol)
    status = get_symbol_data_status(code, data_overrides)
    if not status["hasTechnicalData"]:
        raise ValueError(f"股票 {code} 缺少 technical_indicators 数据")
    if not status["hasResultData"]:
        raise ValueError(f"股票 {code} 缺少 result 数据")

    paths = _paths(data_overrides)
    technical_path = paths["data_dir"] / "technical_indicators" / f"{code}.csv"
    result_path = paths["result"] / f"{code}.csv"

    technical_dates = _read_csv_dates(technical_path)
    result_dates = _read_csv_dates(result_path)
    dates = sorted(technical_dates & result_dates)

    return {
        "code": code,
        "name": status["name"],
        "dates": dates,
        "count": len(dates),
    }


def validate_symbol_for_analysis(
    stock_code: str,
    analysis_date: str | None = None,
    data_overrides: dict | None = None,
) -> str:
    code = normalize_symbol(stock_code)
    status = get_symbol_data_status(code, data_overrides)

    if not status["available"]:
        raise ValueError(status["message"])

    if analysis_date is not None:
        available = get_available_dates(code, data_overrides)
        if analysis_date not in available["dates"]:
            raise ValueError(
                f"分析日期 {analysis_date} 不可用。"
                f"请从 /api/symbols/{code}/available-dates 选择有效日期。"
            )

    return code


def register_stock_name(code: str, name: str) -> None:
    STOCK_NAMES[code] = name