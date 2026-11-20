"""Normalize market-data provider frames before persistence and analysis."""

from __future__ import annotations

import pandas as pd


def normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "open", "high", "low", "close"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"行情数据缺少字段: {', '.join(missing)}")

    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    if "volume" not in normalized.columns:
        normalized["volume"] = 0.0
    normalized["volume"] = normalized["volume"].fillna(0.0)
    normalized = normalized.dropna(subset=required)
    normalized = normalized.sort_values("date").drop_duplicates("date", keep="last")
    if normalized.empty:
        raise ValueError("行情数据没有可用的完整交易记录")
    return normalized[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
