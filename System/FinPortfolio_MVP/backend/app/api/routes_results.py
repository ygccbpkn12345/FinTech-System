"""实验结果查询与策略对比 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..core.result_schema import StandardPortfolioResult
from ..services.experiment_service import ExperimentError

router = APIRouter(prefix="/api", tags=["results"])


def _svc(request: Request):
    return request.app.state.experiments


def _load(request: Request, experiment_id: str) -> StandardPortfolioResult:
    try:
        return _svc(request).get_result(experiment_id)
    except ExperimentError as e:
        raise HTTPException(404, str(e))


@router.get("/results/{experiment_id}")
def get_result(experiment_id: str, request: Request):
    result = _load(request, experiment_id)
    return result.model_dump(mode="json", exclude_none=True)


@router.get("/results/{experiment_id}/weights")
def get_weights(experiment_id: str, request: Request, tail_days: int = 60):
    """最近 tail_days 天的权重矩阵（含现金与行业）。"""
    result = _load(request, experiment_id)
    n = len(result.dates)
    start = max(0, n - tail_days)
    return {
        "experiment_id": experiment_id,
        "dates": result.dates[start:],
        "stock_weights": result.stock_weights[start:],
        "cash_weights": result.cash_weights[start:],
        "industry_weights": (result.industry_weights[start:]
                             if result.industry_weights is not None else None),
        "turnover": result.turnover[start:] if result.turnover is not None else None,
        "asset_label_mode": result.asset_label_mode,
    }


@router.get("/results/{experiment_id}/metrics")
def get_metrics(experiment_id: str, request: Request):
    result = _load(request, experiment_id)
    return {
        "experiment_id": experiment_id,
        "metrics": result.metrics,
        "metric_assumptions": result.metric_assumptions.model_dump(),
        "backtest_mode": result.backtest_mode,
        "trading_protocol": result.trading_protocol,
        "cost_included": result.cost_included,
        "notes": result.notes,
    }


@router.get("/results/{experiment_id}/selection")
def get_selection(experiment_id: str, request: Request):
    result = _load(request, experiment_id)
    if not result.stock_selection:
        raise HTTPException(
            404,
            "this result carries no stock_selection output "
            "(algorithm did not produce ranking data)",
        )
    return {
        "experiment_id": experiment_id,
        "selection": [s.model_dump() for s in result.stock_selection],
    }


@router.get("/results/{experiment_id}/curve")
def get_curve(experiment_id: str, request: Request):
    """净值 / 回撤 / 日收益曲线（轻量，供概览页）。"""
    result = _load(request, experiment_id)
    from ..core.metrics import drawdown_series
    dd = drawdown_series(result.net_daily_returns or result.daily_returns)
    return {
        "experiment_id": experiment_id,
        "dates": result.dates,
        "values": result.portfolio_values,
        "daily_returns": result.daily_returns,
        "drawdown": dd,
        "net_daily_returns": result.net_daily_returns,
    }


# ----------------------------------------------------------------------
# 策略对比（含口径一致性检查）
# ----------------------------------------------------------------------
@router.get("/compare")
def compare(request: Request, ids: str):
    exp_ids = [x.strip() for x in ids.split(",") if x.strip()]
    if not 1 <= len(exp_ids) <= 6:
        raise HTTPException(400, "compare 1-6 experiments")

    svc = _svc(request)
    experiments = []
    for eid in exp_ids:
        try:
            meta = svc.get_experiment(eid)
            result = svc.get_result(eid)
        except ExperimentError as e:
            raise HTTPException(404, str(e))
        experiments.append((meta, result))

    warnings: list[str] = []
    markets = {r.dataset_id for _, r in experiments}
    if len(markets) > 1:
        warnings.append(f"different datasets in comparison: {sorted(markets)}")

    spans = {(r.dates[0], r.dates[-1]) for _, r in experiments}
    if len(spans) > 1:
        warnings.append(
            "test windows differ: "
            + "; ".join(f"{a}~{b}" for a, b in sorted(spans))
        )

    universes = [set().union(*[set(w) for w in r.stock_weights]) or set()
                 for _, r in experiments]
    if len(experiments) > 1:
        base = universes[0]
        for u in universes[1:]:
            if u != base:
                warnings.append("stock universes differ across experiments")
                break

    modes = {r.backtest_mode for _, r in experiments}
    if len(modes) > 1:
        warnings.append(f"mixed backtest modes: {sorted(modes)}")

    protocols = {
        (r.trading_protocol or {}).get("cost_pct") for _, r in experiments
    }
    if len(protocols) > 1:
        warnings.append(f"transaction cost settings differ: {sorted(protocols, key=str)}")

    algorithms = {m.get("algorithm_id") for m, _ in experiments}
    if len(algorithms) > 1 and "ASACPL" in {a and a.upper() for a in algorithms} \
            and "hmmp" in {a and a.lower() for a in algorithms}:
        warnings.append(
            "ASACPL and HMMP use different markets/splits/protocols in their papers; "
            "this comparison is NOT a controlled fair benchmark"
        )

    return {
        "fair": not warnings,
        "warnings": warnings,
        "experiments": [
            {
                "experiment_id": m["experiment_id"],
                "name": m["name"],
                "algorithm_id": m["algorithm_id"],
                "algorithm_name": m["algorithm_name"],
                "dataset_id": m["dataset_id"],
                "backtest_mode": r.backtest_mode,
                "dates": r.dates,
                "portfolio_values": r.portfolio_values,
                "metrics": r.metrics,
                "metric_assumptions": r.metric_assumptions.model_dump(),
            }
            for m, r in experiments
        ],
    }
