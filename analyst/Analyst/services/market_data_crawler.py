"""行情数据抓取服务：HTTP 路由与聊天工具共用同一实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.crawl_date_range import validate_crawl_date_range
from services.data_fetch_service import build_fetch_result
from services.eastmoney_data_service import EastmoneyDataService
from services.market_data_normalizer import normalize_market_frame
from services.symbol_service import get_symbol_data_status, normalize_symbol


DEFAULT_DATA_SOURCE = "baostock"
BAOSTOCK_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def normalize_fetch_request(raw: dict[str, Any] | None) -> dict[str, Any]:
    """把 HTTP 的 camelCase 与聊天工具的 snake_case 统一成同一份参数。"""
    payload = raw or {}
    symbol = normalize_symbol(
        str(payload.get("symbol") or payload.get("stockCode") or "")
    )
    if not symbol:
        raise ValueError("缺少股票代码")

    normalized: dict[str, Any] = {
        "symbol": symbol,
        "start_date": payload.get("startDate") or payload.get("start_date"),
        "end_date": payload.get("endDate") or payload.get("end_date"),
        "data_source": str(
            payload.get("dataSource")
            or payload.get("data_source")
            or DEFAULT_DATA_SOURCE
        ),
    }

    token = payload.get("tushareToken") or payload.get("tushare_token")
    if token:
        normalized["tushare_token"] = token
    crawl_url = payload.get("crawlUrl") or payload.get("crawl_url")
    if crawl_url:
        normalized["crawl_url"] = crawl_url
    return normalized


def _load_baostock_frame(symbol: str, start: str, end: str) -> pd.DataFrame:
    import baostock as bs

    bs_code = f"sh.{symbol}" if symbol.startswith(("5", "6", "9")) else f"sz.{symbol}"
    login = bs.login()
    if login.error_code != "0":
        raise ValueError(f"Baostock 登录失败: {login.error_msg}")

    try:
        result = bs.query_history_k_data_plus(
            bs_code,
            ",".join(BAOSTOCK_COLUMNS),
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="2",
        )
        if result.error_code != "0":
            raise ValueError(f"获取数据失败: {result.error_msg}")

        rows = []
        while result.error_code == "0" and result.next():
            rows.append(result.get_row_data())
    finally:
        bs.logout()

    if not rows:
        raise ValueError(f"Baostock 未获取到 {symbol} 的数据")
    return normalize_market_frame(pd.DataFrame(rows, columns=BAOSTOCK_COLUMNS))


def _load_tushare_frame(
    symbol: str,
    start: str,
    end: str,
    tushare_token: str | None,
) -> pd.DataFrame:
    import tushare as ts

    if not tushare_token:
        raise ValueError("Tushare 需要 token")
    ts.set_token(tushare_token)
    pro = ts.pro_api()

    tushare_start = start.replace("-", "")
    tushare_end = end.replace("-", "")
    frame = pro.daily(
        ts_code=f"{symbol}.SZ",
        start_date=tushare_start,
        end_date=tushare_end,
    )
    if frame is None or frame.empty:
        frame = pro.daily(
            ts_code=f"{symbol}.SH",
            start_date=tushare_start,
            end_date=tushare_end,
        )
    if frame is None or frame.empty:
        raise ValueError(f"Tushare 未获取到 {symbol} 的数据")

    frame = frame.rename(
        columns={
            "trade_date": "date",
            "vol": "volume",
        }
    )
    return normalize_market_frame(frame)


def load_price_frame(
    symbol: str,
    start: str,
    end: str,
    data_source: str,
    tushare_token: str | None = None,
) -> pd.DataFrame:
    if data_source == "baostock":
        return _load_baostock_frame(symbol, start, end)
    if data_source == "tushare":
        return _load_tushare_frame(symbol, start, end, tushare_token)
    raise ValueError(f"不支持的数据源: {data_source}")


class MarketDataCrawlerService:
    """抓取行情并写入本地数据目录，返回统一的数据抓取结果。"""

    def __init__(
        self,
        *,
        frame_loader: Callable[..., pd.DataFrame] | None = None,
        eastmoney_fetcher: Callable[[], dict] | None = None,
        data_dir: str | Path | None = None,
        result_dir: str | Path | None = None,
        status_provider: Callable[[str], dict] | None = None,
    ):
        self._frame_loader = frame_loader or load_price_frame
        self._eastmoney_fetcher = eastmoney_fetcher
        self._data_dir = Path(data_dir) if data_dir is not None else Path("data")
        self._result_dir = (
            Path(result_dir) if result_dir is not None else Path("result")
        )
        self._status_provider = status_provider or get_symbol_data_status

    def fetch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").strip()
        try:
            start, end = validate_crawl_date_range(
                arguments.get("start_date"),
                arguments.get("end_date"),
            )
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        data_source = str(arguments.get("data_source") or DEFAULT_DATA_SOURCE)
        try:
            frame = self._frame_loader(
                symbol,
                start,
                end,
                data_source,
                arguments.get("tushare_token"),
            )
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:  # 网络/第三方库异常统一转换为可展示错误
            return {"status": "error", "message": f"行情数据获取失败: {exc}"}

        if frame is None or getattr(frame, "empty", True):
            return {
                "status": "error",
                "message": f"{data_source} 未获取到 {symbol} 的数据",
            }

        try:
            self._save_frames(symbol, frame)
        except Exception as exc:
            return {"status": "error", "message": f"行情数据保存失败: {exc}"}

        latest_value = frame["date"].max()
        latest_date = (
            latest_value.strftime("%Y-%m-%d")
            if hasattr(latest_value, "strftime")
            else str(latest_value)[:10]
        )
        modules: dict[str, Any] = {"market": {"status": "ok", "count": len(frame)}}
        if data_source == "baostock":
            modules.update(self._fetch_eastmoney(symbol, start, end))

        return build_fetch_result(
            symbol,
            latest_date,
            len(frame),
            modules,
            self._status_provider(symbol),
            start_date=start,
            end_date=end,
        )

    def _save_frames(self, symbol: str, frame: pd.DataFrame) -> None:
        temp_file = self._data_dir / "temp" / f"{symbol}.csv"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(temp_file, index=False)

        technical_file = self._data_dir / "technical_indicators" / f"{symbol}.csv"
        technical_file.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(technical_file, index=False)

        close = pd.to_numeric(frame["close"], errors="coerce")
        result_frame = pd.DataFrame(
            {
                "date": frame["date"],
                "pct_change": close.pct_change() * 100,
            }
        ).dropna()

        result_file = self._result_dir / f"{symbol}.csv"
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_frame.to_csv(result_file, index=False)

        compatibility_file = self._data_dir / "temp_result" / f"{symbol}.csv"
        compatibility_file.parent.mkdir(parents=True, exist_ok=True)
        result_frame.to_csv(compatibility_file, index=False)

    def _fetch_eastmoney(self, symbol: str, start: str, end: str) -> dict:
        if self._eastmoney_fetcher is None:
            service = EastmoneyDataService(data_dir=self._data_dir)
            return service.fetch_all(symbol, start, end)
        return self._eastmoney_fetcher()
