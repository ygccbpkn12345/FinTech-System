"""Single-stock entry comparison, with cash and fills tracked explicitly."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from finportfolio_metrics import compute_metrics
from finportfolio_plugin_interface import BasePortfolioPlugin


WINDOW_SESSIONS = 20
SECOND_ENTRY_SESSION = 6
PRICE_FIELDS = ["open", "close", "volume"]


def load_window(dataset: dict, symbol: str, cutoff_date: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(date.fromisoformat(cutoff_date))
    path = Path(dataset["storage_path"]) / dataset["files"]["prices"]
    prices = pd.read_csv(path, usecols=["date", "tic", *PRICE_FIELDS], dtype={"tic": "string"})
    prices = prices[prices["tic"].str.strip().eq(symbol)].copy()
    prices["date"] = pd.to_datetime(prices["date"], format="%Y-%m-%d", errors="raise")
    prices = prices.loc[prices["date"] < cutoff].sort_values("date")
    if prices["date"].duplicated().any():
        raise ValueError("历史行情包含重复交易日期")
    window = prices.tail(WINDOW_SESSIONS).copy()
    if len(window) < WINDOW_SESSIONS:
        raise ValueError(f"{symbol} 在 {cutoff_date} 前仅有 {len(window)} 条行情，需 {WINDOW_SESSIONS} 条")
    numeric = window[PRICE_FIELDS].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy()).all() or (numeric <= 0).any().any():
        raise ValueError("窗口内有无效价格或成交量，无法模拟成交")
    window[PRICE_FIELDS] = numeric.astype(float)
    window["date"] = window["date"].dt.strftime("%Y-%m-%d")
    return window


def simulate(window: pd.DataFrame, entries: dict[int, float], fee_rate: float) -> dict:
    cash = 1.0
    shares = 0.0
    result = {"values": [], "cash": [], "turnover": [], "returns": [], "fills": []}
    previous_value = 1.0
    for day, bar in enumerate(window.itertuples(index=False), start=1):
        notional = 0.0
        budget = entries.get(day)
        if budget is not None:
            notional = budget / (1 + fee_rate)
            bought = notional / bar.open
            shares += bought
            cash = max(0.0, cash - budget)
            result["fills"].append({
                "date": bar.date, "side": "buy", "price": bar.open,
                "quantity": bought, "notional": notional, "fee": notional * fee_rate,
            })
        if day == len(window):
            notional = shares * bar.close
            fee = notional * fee_rate
            cash += notional - fee
            result["fills"].append({
                "date": bar.date, "side": "sell", "price": bar.close,
                "quantity": shares, "notional": notional, "fee": fee,
            })
            shares = 0.0
        value = cash + shares * bar.close
        result["values"].append(value)
        result["cash"].append(cash / value)
        result["turnover"].append(notional / previous_value)
        result["returns"].append(value / previous_value - 1)
        previous_value = value
    return result


class Adapter(BasePortfolioPlugin):
    capabilities = ("backtest",)

    def backtest(self, params: dict, context: dict) -> dict:
        symbol = params["symbol"].strip()
        window = load_window(context["dataset"], symbol, params["cutoff_date"])
        position = params["position_ratio"]
        fee = params["cost_pct"]
        mode = params["entry_mode"]
        entries = {1: position} if mode == "single" else {
            1: position / 2, SECOND_ENTRY_SESSION: position / 2,
        }
        gross = simulate(window, entries, 0.0)
        net = simulate(window, entries, fee)
        trades_path = Path(context["work_dir"]) / "trades.csv"
        with trades_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(net["fills"][0]))
            writer.writeheader()
            writer.writerows(net["fills"])

        return {
            "backtest_mode": "unified_rebalance",
            "trading_protocol": {
                "symbol": symbol,
                "entry_mode": mode,
                "cutoff_date": params["cutoff_date"],
                "position_ratio": position,
                "cost_pct": fee,
                "execution_timing": "第 1 日开盘买入，分批于第 6 日追加，第 20 日收盘卖出",
                "cost_model": "每笔成交额乘费率，买入费用计入买入预算",
                "date_split_window": {
                    "window_start": window["date"].iloc[0], "window_end": window["date"].iloc[-1],
                },
                "fills": net["fills"],
            },
            "dates": window["date"].tolist(),
            "daily_returns": gross["returns"],
            "net_daily_returns": net["returns"],
            "cost_included": False,
            "portfolio_values": net["values"],
            "stock_weights": [{symbol: 1 - cash} if cash < 1 else {} for cash in net["cash"]],
            "cash_weights": net["cash"],
            "turnover": net["turnover"],
            "metrics": compute_metrics(net["returns"], net["turnover"], net["cash"]),
            "artifacts": [{"name": "trades.csv", "path": str(trades_path), "kind": "csv",
                           "description": "按起始资金为 1 计量的成交及费用明细"}],
            "notes": [
                "使用分析日期前的 20 条日线记录。按日线开收盘价模拟，允许小数股，未模拟涨跌停和滑点。",
                "净值和指标按扣费后的资金计算。历史窗口用于比较买入规则。",
            ],
        }

