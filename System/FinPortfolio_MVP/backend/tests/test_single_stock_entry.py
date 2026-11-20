import math
import time
from datetime import date, timedelta


def test_single_stock_entry_compares_same_window_after_costs(client, tmp_path):
    # A later row must never enter the experiment. The staged purchase pays less.
    start = date(2024, 1, 1)
    end = start + timedelta(days=19)
    cutoff = end + timedelta(days=1)
    dataset_csv = tmp_path / "entry.csv"
    rows = ["date,tic,open,high,low,close,volume"]
    for i in range(21):
        dt = start + timedelta(days=i)
        open_price = 5 if i == 5 else 10
        close_price = 1000 if i == 20 else 10
        rows.append(f"{dt},000063,{open_price},10,5,{close_price},100")
    dataset_csv.write_text("\n".join(rows), encoding="utf-8")
    dataset = client.post("/api/datasets", json={
        "name": "Single stock entry test", "market": "CN",
        "source_dir": str(tmp_path), "files": {"prices": dataset_csv.name},
        "available_modalities": ["prices"],
    })
    assert dataset.status_code == 200, dataset.text
    dataset_id = dataset.json()["dataset_id"]
    coverage = client.get(f"/api/datasets/{dataset_id}/price-coverage", params={
        "symbol": "000063", "before": str(cutoff),
    })
    assert coverage.status_code == 200
    assert coverage.json()["sessions"] == 20

    for mode, gross_final in (("single", 1), ("staged", 1.25)):
        run = client.post("/api/experiments", json={
            "algorithm_id": "single_stock_entry",
            "dataset_id": dataset.json()["dataset_id"], "capability": "backtest",
            "params": {
                "symbol": "000063", "cutoff_date": str(cutoff), "entry_mode": mode,
                "position_ratio": 0.5, "cost_pct": 0.001,
            },
        })
        assert run.status_code == 200, run.text
        experiment_id = run.json()["experiment_id"]
        for _ in range(200):
            meta = client.get(f"/api/experiments/{experiment_id}").json()
            if meta.get("status") not in {"PENDING", "RUNNING"}:
                break
            time.sleep(0.1)
        assert meta.get("status") == "SUCCEEDED", meta
        result = client.get(f"/api/results/{experiment_id}").json()
        assert result["dates"] == [str(start + timedelta(days=i)) for i in range(20)]
        assert result["cash_weights"][-1] == 1
        assert result["stock_weights"][-1] == {}
        assert math.isclose(result["cash_weights"][0], 0.5 if mode == "single" else 0.75, abs_tol=0.001)
        assert math.isclose(math.prod(1 + r for r in result["daily_returns"]), gross_final)
        expected = 0.5 + (gross_final - 0.5) * (1 - 0.001) / (1 + 0.001)
        assert math.isclose(result["portfolio_values"][-1], expected)
        assert math.isclose(result["metrics"]["cumulative_return"], expected - 1)
        curve = client.get(f"/api/results/{experiment_id}/curve").json()
        assert math.isclose(min(curve["drawdown"]), result["metrics"]["max_drawdown"])
        fills = result["trading_protocol"]["fills"]
        assert [fill["date"] for fill in fills] == (
            [str(start), str(end)] if mode == "single"
            else [str(start), str(start + timedelta(days=5)), str(end)]
        )

