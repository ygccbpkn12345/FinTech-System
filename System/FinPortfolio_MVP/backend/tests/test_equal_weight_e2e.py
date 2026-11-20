"""Equal Weight 插件端到端测试：API → 子进程 → 真实回测 → 标准结果。

数据为 conftest 生成的高确定性合成行情（rng=7）—— 这是机制验证测试，
不是论文实验；结果断言的是回测代数关系而非编造的绩效数字。
"""
import math
import time


def _wait_done(client, experiment_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/tasks/{experiment_id}/status").json()
        if st["state"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return st
        time.sleep(0.4)
    raise TimeoutError(f"task {experiment_id} not finished: {st}")


def test_equal_weight_end_to_end(client, price_dataset):
    r = client.post("/api/experiments", json={
        "algorithm_id": "equal_weight",
        "dataset_id": price_dataset["dataset_id"],
        "capability": "backtest",
        "params": {"cost_pct": 0.001},
        "name": "e2e equal weight (synthetic fixture)",
    })
    assert r.status_code == 200, r.text
    exp = r.json()
    assert exp["status"] in ("PENDING", "RUNNING")

    st = _wait_done(client, exp["experiment_id"])
    assert st["state"] == "SUCCEEDED", client.get(
        f"/api/tasks/{exp['experiment_id']}/logs?tail=80").json()["log"]

    # 任务日志是真实子进程输出
    logs = client.get(f"/api/tasks/{exp['experiment_id']}/logs").json()["log"]
    assert "task" in logs

    result = client.get(f"/api/results/{exp['experiment_id']}").json()
    assert result["algorithm_id"] == "equal_weight"
    assert result["dataset_id"] == "synthetic_test_prices"
    assert result["backtest_mode"] == "unified_rebalance"
    assert result["cost_included"] is False
    assert result["net_daily_returns"] is not None   # cost_pct>0 → 有扣费序列

    n = len(result["dates"])
    assert n == 120
    assert len(result["stock_weights"]) == n
    assert len(result["cash_weights"]) == n
    assert len(result["portfolio_values"]) == n

    # 等权代数关系：5 只股票每日等权 1/5
    w0 = result["stock_weights"][0]
    assert len(w0) == 5
    assert all(math.isclose(v, 0.2, rel_tol=1e-6) for v in w0.values())

    # 扣费不高于毛收益
    for gross, net in zip(result["daily_returns"], result["net_daily_returns"]):
        assert net <= gross + 1e-12

    # 首日建仓换手 = 投资比例
    assert math.isclose(result["turnover"][0], 1.0, rel_tol=1e-6)

    # 指标单位与假设显式存在
    m = result["metrics"]
    assert m["trading_days_per_year"] == 252
    assert m["risk_free_rate"] == 0.0
    assert "annualized_return" in m and "sharpe_ratio" in m and "max_drawdown" in m
    assert result["metric_assumptions"]["trading_days_per_year"] == 252

    # 工件落盘
    assert any(a["name"] == "weights.csv" for a in result["artifacts"])

    # 实验列表与概览可见
    listing = client.get("/api/experiments").json()
    assert any(e["experiment_id"] == exp["experiment_id"] for e in listing)
    overview = client.get("/api/system/overview").json()
    assert overview["experiments_succeeded"] >= 1


def test_equal_weight_top_k_and_zero_cost(client, price_dataset):
    r = client.post("/api/experiments", json={
        "algorithm_id": "equal_weight",
        "dataset_id": price_dataset["dataset_id"],
        "capability": "backtest",
        "params": {"top_k": 2, "cost_pct": 0.0},
    })
    assert r.status_code == 200, r.text
    exp = r.json()
    st = _wait_done(client, exp["experiment_id"])
    assert st["state"] == "SUCCEEDED"
    result = client.get(f"/api/results/{exp['experiment_id']}").json()
    assert len(result["stock_weights"][0]) == 2
    assert result.get("net_daily_returns") is None    # 零费率 → 无独立扣费序列
    # 前两只字典序代码
    assert set(result["stock_weights"][0]) == {"AAA", "BBB"}


def test_plugin_adapter_direct(price_dataset, tmp_root):
    """绕过 API 直接调用 plugin_runner 子进程（验证执行协议本身）。"""
    import json
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    runner = project_root / "backend" / "app" / "workers" / "plugin_runner.py"
    out = tmp_root / "direct_runner_test"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment_id": "exp_directtest",
        "plugin_dir": str(tmp_root / "plugins" / "equal_weight"),
        "adapter_file": "adapter.py",
        "capability": "backtest",
        "params": {"top_k": 0, "cost_pct": 0.0, "initial_cash_ratio": 0.0},
        "work_dir": str(out),
        "output_dir": str(out),
        "dataset": price_dataset,
        "manifest": {"id": "equal_weight", "version": "1.0"},
    }
    payload_file = out / "payload.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(runner), str(payload_file)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert len(data["dates"]) == 120
    assert data["algorithm_id"] == "equal_weight"
