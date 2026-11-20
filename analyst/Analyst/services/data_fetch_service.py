from __future__ import annotations


def build_fetch_result(
    symbol: str,
    latest_date: str,
    market_count: int,
    modules: dict,
    data_status: dict,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    failed = [name for name, detail in modules.items() if detail.get("status") != "ok"]
    status = "partial" if failed else "ok"
    message = (
        f"部分数据获取失败: {', '.join(failed)}"
        if failed
        else "行情、新闻和基本面数据获取完成"
    )
    return {
        "status": status,
        "message": message,
        "count": market_count,
        "symbol": symbol,
        "latestDate": latest_date,
        "startDate": start_date,
        "endDate": end_date,
        "modules": modules,
        "failedModules": failed,
        "dataStatus": data_status,
    }
