"""Equal Weight 插件适配器。

在插件子进程中由 plugin_runner 加载执行；依赖 pandas/numpy（插件环境需具备）。
回测口径（unified_rebalance）：
- 每日收盘价计算个股日收益，组合毛收益 = 等权平均；
- 每日再平衡回目标权重，换手率按「目标权重 vs 漂移后权重」的单边差额计算；
- cost_pct > 0 时给出扣费后收益序列；指标在扣费序列上计算。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from finportfolio_plugin_interface import BasePortfolioPlugin
except ImportError:  # 允许独立运行（例如调试）
    class BasePortfolioPlugin:  # type: ignore
        pass


PRICE_LOGICAL_NAMES = ("prices", "test_prices", "train_prices")


class Adapter(BasePortfolioPlugin):
    capabilities = ("backtest", "portfolio_weights")

    # ------------------------------------------------------------------
    def _load_prices(self, dataset: dict) -> pd.DataFrame:
        files = dataset.get("files", {})
        logical = next((k for k in PRICE_LOGICAL_NAMES if k in files), None)
        if logical is None:
            raise ValueError(
                f"dataset '{dataset.get('dataset_id')}' has none of {PRICE_LOGICAL_NAMES}"
            )
        path = Path(dataset["storage_path"]) / files[logical]
        df = pd.read_csv(path)
        cols = {str(c).strip().lower(): c for c in df.columns}
        date_col = next((cols[c] for c in ("date", "datetime", "time") if c in cols), None)
        tic_col = next(
            (cols[c] for c in ("tic", "ticker", "symbol", "stockcode", "stock_code") if c in cols),
            None,
        )
        close_col = next(
            (cols[c] for c in ("close", "adj_close", "closeprice", "close_price") if c in cols),
            None,
        )
        if not (date_col and tic_col and close_col):
            raise ValueError(
                f"price csv must contain date/tic/close columns; found {list(df.columns)}"
            )
        df = df[[date_col, tic_col, close_col]].copy()
        df.columns = ["date", "tic", "close"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["tic"] = df["tic"].astype(str)
        df = df.dropna().sort_values(["date", "tic"])
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        wide = df.pivot(index="date", columns="tic", values="close").sort_index()
        # 剔除全程无价的列；前向填充中途缺失（停牌按最后价持有）
        wide = wide.dropna(axis=1, how="all").ffill()
        if wide.shape[1] == 0 or len(wide) < 2:
            raise ValueError("not enough valid price data for equal-weight backtest")
        return wide

    # ------------------------------------------------------------------
    @staticmethod
    def _apply_date_split(prices: pd.DataFrame, dataset: dict) -> tuple[pd.DataFrame, dict | None]:
        """回测窗口 = 所有已提供切片边界的外包络（含端点）。留空 = 全量。"""
        split = (dataset.get("date_split") or {})
        bounds = [split.get(k) for k in ("train_start", "test_start") if split.get(k)]
        bounds += [split.get(k) for k in ("train_end", "test_end") if split.get(k)]
        if not bounds:
            return prices, None
        start, end = min(bounds), max(bounds)
        idx = pd.to_datetime(prices.index)
        out = prices[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
        if out.empty:
            raise ValueError(
                f"date split window [{start}, {end}] contains no trading days; "
                f"price data covers {prices.index[0]}~{prices.index[-1]}"
            )
        return out, {"window_start": start, "window_end": end}

    # ------------------------------------------------------------------
    def backtest(self, params: dict, context: dict) -> dict:
        dataset = context["dataset"]
        prices = self._load_prices(dataset)
        prices, split_window = self._apply_date_split(prices, dataset)

        top_k = int(params.get("top_k", 0) or 0)
        cost_pct = float(params.get("cost_pct", 0.0) or 0.0)
        cash_ratio = float(params.get("initial_cash_ratio", 0.0) or 0.0)

        if top_k > 0:
            chosen = sorted(prices.columns)[:top_k]
            prices = prices[list(chosen)]

        rets = prices.pct_change().fillna(0.0)
        dates = list(prices.index)
        n_assets = prices.shape[1]
        equity_ratio = 1.0 - cash_ratio
        target = equity_ratio / n_assets

        gross: list[float] = []
        net: list[float] = []
        weights_rows: list[dict] = []
        cash_rows: list[float] = []
        turnover_rows: list[float] = []

        prev_effective: dict[str, float] | None = None   # 漂移后的权重
        prev_codes: list[str] | None = None

        for i, date in enumerate(dates):
            day_ret = rets.iloc[i]
            codes = list(prices.columns)
            if prev_effective is None or prev_codes != codes:
                # 建仓（或股票池变化）：从现金到目标
                eff = {c: target for c in codes}
                gross_r = float(np.mean([day_ret[c] for c in codes])) * equity_ratio
                turn = equity_ratio
            else:
                drifted = {
                    c: prev_effective.get(c, 0.0) * (1.0 + float(day_ret[c]))
                    for c in codes
                }
                total = sum(drifted.values())
                if total > 0:
                    drifted = {c: v / total * equity_ratio for c, v in drifted.items()}
                eff = {c: target for c in codes}
                gross_r = sum(prev_effective.get(c, 0.0) * float(day_ret[c]) for c in codes)
                turn = 0.5 * sum(abs(eff[c] - drifted.get(c, 0.0)) for c in codes)

            cost = cost_pct * turn * 2.0 if cost_pct > 0 else 0.0
            gross.append(float(gross_r))
            net.append(float(gross_r - cost))
            weights_rows.append({c: round(eff[c], 10) for c in codes})
            cash_rows.append(round(cash_ratio, 10))
            turnover_rows.append(float(turn))
            prev_effective = eff
            prev_codes = codes

        values = list(np.cumprod(1.0 + np.asarray(net)))

        # 指标模块由 plugin_runner 以 importlib 注入（仅依赖 numpy，跨环境可用）
        from finportfolio_metrics import compute_metrics  # noqa: PLC0415

        mets = compute_metrics(net, turnover_rows, cash_rows)
        protocol = {
            "execution_timing": "daily close, next-day weights applied to same-day close returns",
            "rebalance_freq": "daily",
            "cost_pct": cost_pct,
            "cost_model": "one-side notional on turnover (x2 round-trip on turn)",
            "universe_rule": "all dataset assets" if top_k == 0 else f"first {top_k} tickers lexicographically",
            "cash_ratio": cash_ratio,
        }
        if split_window:
            protocol["date_split_window"] = split_window
        base = {
            "backtest_mode": "unified_rebalance",
            "trading_protocol": protocol,
            "dates": dates,
            "daily_returns": gross,
            "net_daily_returns": net if cost_pct > 0 else None,
            "cost_included": False,
            "portfolio_values": values,
            "stock_weights": weights_rows,
            "cash_weights": cash_rows,
            "industry_weights": None,
            "turnover": turnover_rows,
            "metrics": mets,
            "artifacts": [],
            "notes": [
                "Equal Weight 1/N baseline with daily rebalance (unified protocol).",
                "metrics are computed on the net-of-cost series when cost_pct > 0, "
                "otherwise on gross returns.",
                *(
                    [f"backtest window restricted by user date split: {split_window}"]
                    if split_window else []
                ),
            ],
        }
        # 导出权重明细工件
        work = Path(context.get("work_dir", "."))
        weights_csv = work / "weights.csv"
        pd.DataFrame(weights_rows, index=dates).to_csv(weights_csv)
        base["artifacts"] = [{
            "name": "weights.csv",
            "path": str(weights_csv),
            "kind": "csv",
            "description": "daily equal-weight allocations",
        }]
        return base
