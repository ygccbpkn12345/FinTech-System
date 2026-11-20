"""论文真实结果 CSV 导入 → StandardPortfolioResult。

移植自原 MVP backend/app.py（returns_frame / normalize_weights / metrics），
并按新架构升级：
- HMMP 最终权重按「行业资金权重 × 行业内条件权重」组合计算（任务书第八节），
  CASH 列进入 cash_weights；
- ASACPL actions 导出（按位置序列化列表）在未提供 ticker 顺序时标注
  asset_label_mode=position_index，并在 notes 中明确提示；
- 回测模式固定 paper_original：收益来自论文自身的交易环境，口径以原实现为准。

已核实的原代码口径（不得虚构）：
- ASACPL env_new.py step(): portfolio_return = sum((close_t/close_{t-1} - 1) * w)，
  transaction_cost_pct 仅存储未参与收益计算 → cost_included=False；
- HMMP B_PortfolioEnv.py 无交易费用扣减 → cost_included=False。
"""
from __future__ import annotations

import ast
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..core import metrics as metrics_mod
from ..core.result_schema import validate_result_dict


class ImportError_(Exception):
    pass


def returns_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ImportError_("empty returns file")
    cols = {str(c).lower(): c for c in df.columns}
    date_col = next((cols[x] for x in ["date", "datetime", "time", "timestamp"] if x in cols), None)
    ret_col = next(
        (cols[x] for x in ["return", "daily_return", "daily_returns", "portfolio_return"] if x in cols),
        None,
    )
    if ret_col is None:
        raise ImportError_("no daily returns column found (need Return / daily_return, decimal)")
    if date_col is None:
        raise ImportError_("no Date column found")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "return": pd.to_numeric(df[ret_col], errors="coerce"),
        }
    ).dropna()
    if out.empty:
        raise ImportError_("no valid dated returns")
    if out["date"].duplicated().any():
        raise ImportError_("duplicate dates in returns; select one split/window")
    if (out["return"] <= -1).any():
        raise ImportError_("returns <= -100% are invalid for compounding")
    out = out.sort_values("date")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def _parse_weights_wide(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """date + 每资产一列 的宽表权重。"""
    cols = {str(c).lower(): c for c in df.columns}
    dcol = cols.get("date")
    if dcol is None:
        return None
    frame = df.copy()
    frame[dcol] = pd.to_datetime(frame[dcol], errors="coerce").dt.strftime("%Y-%m-%d")
    frame = frame.dropna(subset=[dcol]).sort_values(dcol)
    value_cols = [c for c in df.columns if c != dcol]
    if not value_cols:
        return None
    for c in value_cols:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    return frame.set_index(dcol)[value_cols]


def _asacpl_weights(df: pd.DataFrame) -> tuple[list[dict], str, list[str]]:
    """ASACPL 04_a3c_test_weights_CNN.csv：date + actions(序列化 list)。"""
    cols = {str(c).lower(): c for c in df.columns}
    dcol = cols.get("date")
    acol = cols.get("actions")
    if dcol is None or acol is None:
        raise ImportError_("ASACPL weights csv must have 'date' and 'actions' columns")
    rows: list[dict] = []
    frame = df.sort_values(dcol)
    for _, row in frame.iterrows():
        raw = row[acol]
        try:
            vals = ast.literal_eval(raw) if isinstance(raw, str) else raw
            vals = list(vals)
        except (ValueError, TypeError, SyntaxError) as e:
            raise ImportError_(f"cannot parse actions '{raw}': {e}")
        weights = {f"Asset_{i+1}": float(v) for i, v in enumerate(vals)}
        rows.append(weights)
    return rows, "position_index", [
        "ASACPL actions export does not carry ticker labels; assets shown as positions. "
        "Provide the dataset's ticker order via dataset_id to map real codes."
    ]


def _hmmp_compose(
    industry_df: pd.DataFrame, intra_df: Optional[pd.DataFrame]
) -> tuple[list[dict], list[float], list[dict], list[str]]:
    """HMMP：行业权重(含 CASH) × 行业内条件权重 → 最终权重。"""
    notes = [
        "HMMP final stock weight = industry capital weight x intra-industry conditional weight; "
        "CASH column recorded as cash weight."
    ]
    wide = _parse_weights_wide(industry_df)
    if wide is None:
        raise ImportError_("industry weights csv must be a wide table with a Date column")
    if "cash" in wide.columns.str.lower().tolist():
        cash_col = [c for c in wide.columns if str(c).lower() == "cash"][0]
    else:
        cash_col = None
    ind_cols = [c for c in wide.columns if c != cash_col]

    intra_map: dict[tuple[str, Any], dict[Any, float]] = {}
    if intra_df is not None and not intra_df.empty:
        cols = {str(c).lower(): c for c in intra_df.columns}
        dcol = cols.get("date")
        icol = cols.get("industry_id")
        scol = cols.get("stockcode") or cols.get("stock_code") or cols.get("tic")
        wcol = cols.get("intraweight") or cols.get("intra_weight") or cols.get("weight")
        if not (dcol and icol and scol and wcol):
            raise ImportError_(
                "stock intra weights csv needs Date, Industry_id, StockCode, IntraWeight"
            )
        tmp = intra_df.copy()
        tmp[dcol] = pd.to_datetime(tmp[dcol], errors="coerce").dt.strftime("%Y-%m-%d")
        for _, row in tmp.iterrows():
            key = (row[dcol], str(row[icol]))
            intra_map.setdefault(key, {})[str(row[scol])] = float(row[wcol])

    stock_rows: list[dict] = []
    cash_rows: list[float] = []
    industry_rows: list[dict] = []
    for date, row in wide.iterrows():
        cash = float(row.get(cash_col, 0.0)) if cash_col else 0.0
        cash = 0.0 if pd.isna(cash) else cash
        stock_w: dict[str, float] = {}
        industry_w: dict[str, float] = {}
        for c in ind_cols:
            iw = float(row[c]) if pd.notna(row[c]) else 0.0
            industry_w[str(c)] = iw
            for scode, iwgt in intra_map.get((date, str(c)), {}).items():
                stock_w[scode] = iw * iwgt
        # 无明细时允许仅行业层
        stock_rows.append(stock_w)
        cash_rows.append(cash)
        industry_rows.append(industry_w)
    if not any(stock_rows):
        notes.append("no intra-industry weights supplied; stock_weights left empty by date")
    return stock_rows, cash_rows, industry_rows, notes


def import_result(
    algorithm_id: str,
    algorithm_name: str,
    algorithm_version: str,
    returns_df: pd.DataFrame,
    weights_kind: Optional[str],
    industry_df: Optional[pd.DataFrame],
    intra_df: Optional[pd.DataFrame],
    dataset_id: str,
    dataset_name: str,
    name: str,
    experiments_dir: Path,
    source_note: str,
) -> dict:
    rf = returns_frame(returns_df)
    dates = rf["date"].tolist()
    daily = rf["return"].astype(float).tolist()

    stock_weights: list[dict] = [dict() for _ in dates]
    cash_weights = [0.0] * len(dates)
    industry_weights: Optional[list[dict]] = None
    label_mode = "ticker"
    notes = [
        "imported from paper-original CSV outputs; backtest_mode=paper_original",
        "returns are gross of transaction costs in the provided paper code "
        "(ASACPL env stores transaction_cost_pct but does not deduct it; HMMP env has no cost term)",
        source_note,
    ]

    if weights_kind == "asacpl":
        stock_weights, label_mode, extra = _asacpl_weights(intra_df)  # intra_df=weights csv
        notes.extend(extra)
        cash_weights = [0.0] * len(stock_weights)
        if len(stock_weights) != len(dates):
            m = min(len(stock_weights), len(dates))
            notes.append(
                f"weights rows {len(stock_weights)} != returns rows {len(dates)}; truncated to {m}"
            )
            dates, daily = dates[:m], daily[:m]
            stock_weights, cash_weights = stock_weights[:m], cash_weights[:m]
    elif weights_kind == "hmmp":
        stock_weights, cash_weights, industry_weights, extra = _hmmp_compose(
            industry_df, intra_df
        )
        notes.extend(extra)
        m = len(dates)
        for series in (stock_weights, cash_weights, industry_weights):
            if len(series) != m:
                m = min(m, len(series))
        if m != len(dates):
            notes.append(f"weight series truncated to {m} rows to match dates")
            dates, daily = dates[:m], daily[:m]
            stock_weights = stock_weights[:m]
            cash_weights = cash_weights[:m]
            industry_weights = industry_weights[:m]

    turnover = metrics_mod.turnover_series(stock_weights, cash_weights)
    values = metrics_mod.wealth_series(daily)
    mets = metrics_mod.compute_metrics(daily, turnover, cash_weights)

    experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
    exp_dir = experiments_dir / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    # 保存原始导入文件副本，保证结果可追溯
    imports_dir = exp_dir / "imported"
    imports_dir.mkdir(exist_ok=True)

    result = validate_result_dict({
        "experiment_id": experiment_id,
        "algorithm_id": algorithm_id,
        "algorithm_version": algorithm_version,
        "dataset_id": dataset_id,
        "dataset_version": "1",
        "configuration": {"imported": True},
        "backtest_mode": "paper_original",
        "trading_protocol": {
            "execution_timing": "paper original environment",
            "cost_pct": None,
            "rebalance_freq": "paper original",
        },
        "dates": dates,
        "daily_returns": daily,
        "net_daily_returns": None,
        "cost_included": False,
        "portfolio_values": values,
        "stock_weights": stock_weights,
        "cash_weights": cash_weights,
        "industry_weights": industry_weights,
        "turnover": turnover,
        "metrics": mets,
        "artifacts": [],
        "notes": notes,
        "asset_label_mode": label_mode,
        "weights_available": weights_kind is not None,
    })

    result_path = exp_dir / "result.json"
    result_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    keep = (
        "days", "annualized_return", "annualized_volatility", "sharpe_ratio",
        "sortino_ratio", "max_drawdown", "calmar_ratio", "cumulative_return",
        "avg_turnover", "avg_cash_ratio",
    )
    meta = {
        "experiment_id": experiment_id,
        "name": name,
        "kind": "import",
        "algorithm_id": algorithm_id,
        "algorithm_name": algorithm_name,
        "algorithm_version": algorithm_version,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "capability": "import",
        "backtest_mode": "paper_original",
        "status": "SUCCEEDED",
        "error": None,
        "created_at": time.time(),
        "finished_at": time.time(),
        "task_id": None,
        "params": {},
        "notes": notes,
        "artifacts": [{"name": "imported", "path": str(imports_dir), "kind": "dir"}],
        "result_summary": {k: mets[k] for k in keep if k in mets},
        "import_source": source_note,
    }
    (exp_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def save_import_copy(imports_dir: Path, filename: str, data: bytes) -> None:
    imports_dir.joinpath(filename).write_bytes(data)
