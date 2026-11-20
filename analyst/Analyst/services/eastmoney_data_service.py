from __future__ import annotations

import re
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd


class EastmoneyResponseError(RuntimeError):
    """Raised when Eastmoney returns an unusable response."""


def eastmoney_security_code(symbol: str) -> str:
    value = str(symbol).strip().upper()
    if re.fullmatch(r"\d{6}\.(SH|SZ)", value):
        return value
    if not re.fullmatch(r"\d{6}", value):
        raise ValueError(f"无效股票代码: {symbol}")
    return f"{value}.SH" if value.startswith(("5", "6", "9")) else f"{value}.SZ"


def _clean_html(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("\u3000", "").replace("\r", " ").replace("\n", " ").strip()


def normalize_news_payload(
    payload: dict,
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    rows = ((payload.get("result") or {}).get("cmsArticleWebOld") or [])
    if not rows:
        raise EastmoneyResponseError("东方财富新闻数据为空")
    frame = pd.DataFrame(
        {
            "Publish Time": [row.get("date") for row in rows],
            "Title": [_clean_html(row.get("title")) for row in rows],
            "keyword": [symbol] * len(rows),
            "source": [_clean_html(row.get("mediaName")) for row in rows],
            "Content": [_clean_html(row.get("content")) for row in rows],
        }
    )
    frame["Publish Time"] = pd.to_datetime(frame["Publish Time"], errors="coerce")
    frame = frame.dropna(subset=["Publish Time"])
    if start_date:
        frame = frame[frame["Publish Time"] >= pd.Timestamp(start_date)]
    if end_date:
        frame = frame[frame["Publish Time"] < pd.Timestamp(end_date) + pd.Timedelta(days=1)]
    frame = frame[frame["Title"].astype(str).str.strip().ne("")]
    if frame.empty:
        raise EastmoneyResponseError("东方财富新闻数据为空或字段无效")
    return frame.reset_index(drop=True)


def normalize_financial_payload(
    payload: dict,
    statement_name: str,
    *,
    end_date: str | None = None,
) -> pd.DataFrame:
    result = payload.get("result") or {}
    rows = result.get("data") or []
    if payload.get("success") is False or not rows:
        raise EastmoneyResponseError(f"东方财富{statement_name}数据为空")
    frame = pd.DataFrame(rows)
    if "REPORT_DATE" not in frame.columns:
        raise EastmoneyResponseError(f"东方财富{statement_name}缺少 REPORT_DATE")
    frame["REPORT_DATE"] = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
    frame = frame.dropna(subset=["REPORT_DATE"])
    if frame.empty:
        raise EastmoneyResponseError(f"东方财富{statement_name} REPORT_DATE 无效")
    if end_date:
        visible_column = "NOTICE_DATE" if "NOTICE_DATE" in frame.columns else "REPORT_DATE"
        visible_dates = pd.to_datetime(frame[visible_column], errors="coerce")
        frame = frame[visible_dates <= pd.Timestamp(end_date)]
        if frame.empty:
            raise EastmoneyResponseError(f"东方财富{statement_name}截止 {end_date} 无可用数据")
    if "UPDATE_DATE" in frame.columns:
        frame["UPDATE_DATE"] = pd.to_datetime(frame["UPDATE_DATE"], errors="coerce")
        frame = frame.sort_values(["REPORT_DATE", "UPDATE_DATE"], ascending=[False, False])
    else:
        frame = frame.sort_values("REPORT_DATE", ascending=False)
    keys = [column for column in ("SECURITY_CODE", "REPORT_DATE") if column in frame.columns]
    return frame.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)


class EastmoneyDataService:
    NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
    FINANCE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    STATEMENTS = {
        "balanceSheet": ("RPT_DMSK_FN_BALANCE", "资产负债表", "Balance Sheet"),
        "incomeStatement": ("RPT_DMSK_FN_INCOME", "利润表", "Income Statement"),
        "cashFlowStatement": ("RPT_DMSK_FN_CASHFLOW", "现金流量表", "Cash Flow Statement"),
    }

    def __init__(self, client=None, data_dir: str | Path = "data", max_news_pages: int = 10, retries: int = 2):
        if client is None:
            import httpx

            client = httpx.Client(
                timeout=httpx.Timeout(20.0, connect=8.0),
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.eastmoney.com/"},
            )
        self.client = client
        self.data_dir = Path(data_dir)
        self.max_news_pages = max_news_pages
        self.retries = retries

    def _get(self, url: str, params: dict, *, jsonp: bool = False) -> dict:
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                if not jsonp:
                    return response.json()
                match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", response.text, re.S)
                if not match:
                    raise EastmoneyResponseError("东方财富新闻响应不是有效 JSONP")
                return json.loads(match.group(1))
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.1 * (attempt + 1))
        raise EastmoneyResponseError(str(last_error)) from last_error

    @staticmethod
    def _atomic_csv(frame: pd.DataFrame, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".csv", dir=target.parent)
        os.close(fd)
        try:
            frame.to_csv(temp_name, index=False, encoding="utf-8-sig")
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _news_params(self, symbol: str, page: int) -> dict:
        inner = {
            "uid": "",
            "keyword": symbol,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time", "pageIndex": page, "pageSize": 50, "preTag": "<em>", "postTag": "</em>"}},
        }
        return {"cb": "callback", "param": json.dumps(inner, ensure_ascii=False)}

    def fetch_news(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> dict:
        frames = []
        for page in range(1, self.max_news_pages + 1):
            payload = self._get(self.NEWS_URL, self._news_params(symbol, page), jsonp=True)
            rows = ((payload.get("result") or {}).get("cmsArticleWebOld") or [])
            if not rows:
                break
            try:
                frames.append(normalize_news_payload(payload, symbol, start_date, end_date))
            except EastmoneyResponseError:
                continue
        if not frames:
            raise EastmoneyResponseError("东方财富新闻数据为空")
        frame = pd.concat(frames, ignore_index=True)
        target = self.data_dir / "news" / f"{symbol}.csv"
        if target.is_file():
            old = pd.read_csv(target)
            frame = pd.concat([old, frame], ignore_index=True)
        frame["Publish Time"] = pd.to_datetime(frame["Publish Time"], errors="coerce")
        frame = frame.dropna(subset=["Publish Time"])
        if start_date:
            frame = frame[frame["Publish Time"] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame["Publish Time"] < pd.Timestamp(end_date) + pd.Timedelta(days=1)]
        frame = frame.drop_duplicates(subset=["Publish Time", "Title"], keep="last")
        frame = frame.sort_values("Publish Time", ascending=False).reset_index(drop=True)
        self._atomic_csv(frame, target)
        return {"status": "ok", "count": len(frame)}

    def fetch_statement(self, symbol: str, module: str, end_date: str | None = None) -> dict:
        report_name, display_name, directory = self.STATEMENTS[module]
        params = {
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "pageSize": "500",
            "pageNumber": "1",
            "reportName": report_name,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{symbol}")',
        }
        payload = self._get(self.FINANCE_URL, params)
        frame = normalize_financial_payload(payload, display_name, end_date=end_date)
        output = frame.rename(columns={"REPORT_DATE": "统计截止日期"})
        target = self.data_dir / "fundamentals" / directory / f"{symbol}.csv"
        self._atomic_csv(output, target)
        return {"status": "ok", "count": len(output)}

    def fetch_all(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> dict:
        operations = {"news": lambda: self.fetch_news(symbol, start_date, end_date)}
        operations.update({name: lambda name=name: self.fetch_statement(symbol, name, end_date) for name in self.STATEMENTS})
        results = {}
        for name, operation in operations.items():
            try:
                results[name] = operation()
            except Exception as exc:
                results[name] = {"status": "error", "count": 0, "message": str(exc)}
        return results
