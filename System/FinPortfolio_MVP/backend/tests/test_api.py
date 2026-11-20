"""FastAPI 接口测试（算法 / 数据集 / 实验元信息 / 任务查询）。"""
import time


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_algorithms_listed_dynamically(client):
    r = client.get("/api/algorithms")
    assert r.status_code == 200
    algos = {a["algorithm_id"]: a for a in r.json()}
    assert {"equal_weight", "asacpl", "hmmp"} <= set(algos)
    # 关键元数据齐备
    eq = algos["equal_weight"]
    assert eq["status"] == "READY"
    assert "backtest" in eq["capabilities"]
    assert eq["paper"]["title"]
    assert eq["framework"]


def test_algorithm_detail_and_config(client):
    r = client.get("/api/algorithms/equal_weight")
    assert r.status_code == 200
    detail = r.json()
    assert detail["algorithm_id"] == "equal_weight"
    assert detail["execution"]["adapter_file"] == "adapter.py"

    r = client.get("/api/algorithms/equal_weight/config")
    assert r.status_code == 200
    cfg = r.json()
    names = {p["name"] for p in cfg["parameters"]}
    assert {"top_k", "cost_pct"} <= names
    assert cfg["default_params"]["cost_pct"] == 0.0

    assert client.get("/api/algorithms/nope").status_code == 404


def test_registry_reload_endpoint(client):
    r = client.get("/api/algorithms/registry/reload")
    assert r.status_code == 200
    assert "equal_weight" in r.json()["registered"]


def test_datasets_crud(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    ids = {d["dataset_id"] for d in r.json()}
    assert "synthetic_test_prices" in ids

    r = client.get("/api/datasets/synthetic_test_prices")
    assert r.status_code == 200
    assert r.json()["market"] == "TEST"

    r = client.post("/api/datasets/synthetic_test_prices/validate")
    assert r.status_code == 200
    assert r.json()["valid"] is True

    assert client.get("/api/datasets/none").status_code == 404


def test_compatibility_endpoint(client):
    r = client.get("/api/datasets/synthetic_test_prices/compatibility/equal_weight")
    assert r.status_code == 200
    assert r.json()["compatible"] is True


def test_experiment_validation_errors(client):
    # 未知算法
    r = client.post("/api/experiments", json={
        "algorithm_id": "ghost", "dataset_id": "synthetic_test_prices",
        "capability": "backtest",
    })
    assert r.status_code == 400

    # 算法未声明的能力
    r = client.post("/api/experiments", json={
        "algorithm_id": "equal_weight", "dataset_id": "synthetic_test_prices",
        "capability": "train",
    })
    assert r.status_code == 400
    assert "does not declare capability" in r.json()["detail"]

    # 不兼容数据集（asacpl 需要 cov/特征模态）
    r = client.post("/api/experiments", json={
        "algorithm_id": "asacpl", "dataset_id": "synthetic_test_prices",
        "capability": "train",
    })
    assert r.status_code == 400
    assert "incompatible" in r.json()["detail"]

    # 未知/越界参数
    r = client.post("/api/experiments", json={
        "algorithm_id": "equal_weight", "dataset_id": "synthetic_test_prices",
        "capability": "backtest", "params": {"top_k": 99999},
    })
    assert r.status_code == 400
    assert "above max" in r.json()["detail"]


def test_experiment_404(client):
    assert client.get("/api/experiments/exp_nope").status_code == 404
    assert client.get("/api/tasks/exp_nope/status").status_code == 404
    assert client.get("/api/tasks/exp_nope/logs").status_code == 404
    assert client.get("/api/results/exp_nope").status_code == 404


def test_system_overview(client):
    r = client.get("/api/system/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["algorithms_registered"] >= 3
    assert "recent_experiments" in data
    assert "plugin_scan" in data


def test_upload_import_asacpl(client):
    """论文 CSV 上传导入（ASACPL 口径）→ StandardPortfolioResult。"""
    import io

    returns_csv = (
        "date,daily_return\n"
        "2024-01-02,0.01\n2024-01-03,-0.005\n2024-01-04,0.012\n"
    )
    weights_csv = (
        "date,actions\n"
        "2024-01-02,\"[0.5, 0.5]\"\n"
        "2024-01-03,\"[0.6, 0.4]\"\n"
        "2024-01-04,\"[0.4, 0.6]\"\n"
    )
    r = client.post(
        "/api/experiments/upload",
        data={"algorithm_id": "asacpl", "name": "t", "dataset_id": "d", "dataset_name": "d"},
        files={
            "returns": ("r.csv", io.BytesIO(returns_csv.encode()), "text/csv"),
            "weights": ("w.csv", io.BytesIO(weights_csv.encode()), "text/csv"),
        },
    )
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["status"] == "SUCCEEDED"
    assert meta["result_summary"]["days"] == 3

    rid = meta["experiment_id"]
    detail = client.get(f"/api/results/{rid}").json()
    assert detail["backtest_mode"] == "paper_original"
    assert detail["cost_included"] is False
    assert detail["asset_label_mode"] == "position_index"

    # 权重端点
    w = client.get(f"/api/results/{rid}/weights").json()
    assert len(w["stock_weights"]) == 3
    m = client.get(f"/api/results/{rid}/metrics").json()
    assert "sharpe_ratio" in m["metrics"]
    c = client.get(f"/api/results/{rid}/curve").json()
    assert len(c["values"]) == 3


def test_upload_import_hmmp_composes_weights(client):
    """HMMP 导入：行业权重 × 行业内条件权重 → 最终权重（任务书第八节）。"""
    import io

    returns_csv = "Date,Return\n2024-01-02,0.01\n2024-01-03,0.02\n"
    industry_csv = (
        "Date,0,1,CASH\n"
        "2024-01-02,0.6,0.3,0.1\n"
        "2024-01-03,0.5,0.4,0.1\n"
    )
    intra_csv = (
        "Date,Industry_id,StockCode,IntraWeight\n"
        "2024-01-02,0,600000,0.7\n2024-01-02,0,600036,0.3\n"
        "2024-01-02,1,000001,1.0\n"
        "2024-01-03,0,600000,0.5\n2024-01-03,0,600036,0.5\n"
        "2024-01-03,1,000001,1.0\n"
    )
    r = client.post(
        "/api/experiments/upload",
        data={"algorithm_id": "hmmp", "name": "hmmp t", "dataset_id": "d", "dataset_name": "d"},
        files={
            "returns": ("r.csv", io.BytesIO(returns_csv.encode()), "text/csv"),
            "industry": ("i.csv", io.BytesIO(industry_csv.encode()), "text/csv"),
            "intra": ("s.csv", io.BytesIO(intra_csv.encode()), "text/csv"),
        },
    )
    assert r.status_code == 200, r.text
    rid = r.json()["experiment_id"]
    detail = client.get(f"/api/results/{rid}").json()
    sw = detail["stock_weights"]
    # 行业 0 资金 0.6 × 条件 0.7 = 0.42
    assert abs(sw[0]["600000"] - 0.42) < 1e-9
    assert abs(sw[0]["600036"] - 0.18) < 1e-9
    assert abs(sw[0]["000001"] - 0.3) < 1e-9
    assert abs(detail["cash_weights"][0] - 0.1) < 1e-9
    assert detail["industry_weights"][0]["0"] == 0.6
    assert detail["algorithm_id"] == "hmmp"


def test_compare_endpoint_flags_unfair(client):
    """对比不同市场/窗口的实验时必须给出显著提示。"""
    import io

    def imp(name, dates, rets):
        csv = "date,daily_return\n" + "".join(
            f"{d},{r}\n" for d, r in zip(dates, rets)
        )
        r = client.post(
            "/api/experiments/upload",
            data={"algorithm_id": "equal_weight", "name": name,
                  "dataset_id": "d1", "dataset_name": "d"},
            files={"returns": ("r.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        return r.json()["experiment_id"]

    a = imp("a", ["2024-01-02", "2024-01-03"], [0.01, 0.01])
    b = imp("b", ["2023-01-02", "2023-01-03"], [0.02, -0.01])
    r = client.get("/api/compare", params={"ids": f"{a},{b}"})
    assert r.status_code == 200
    data = r.json()
    assert data["fair"] is False
    assert any("windows differ" in w for w in data["warnings"])

    r = client.get("/api/compare", params={"ids": f"{a},{a}"})
    assert r.status_code == 200
    assert r.json()["fair"] is True


def test_experiment_data_split_validation(client, price_dataset):
    """data_split：格式 / 顺序 / 重叠 / 数据集范围校验（全部 400）。"""
    base = {
        "algorithm_id": "equal_weight",
        "dataset_id": price_dataset["dataset_id"],
        "capability": "backtest",
    }

    # 非法日期格式
    r = client.post("/api/experiments", json={
        **base, "data_split": {"train_start": "2024/01/02"},
    })
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"]

    # 非法日期值
    r = client.post("/api/experiments", json={
        **base, "data_split": {"train_start": "2024-13-40"},
    })
    assert r.status_code == 400

    # 训练集内 start > end
    r = client.post("/api/experiments", json={
        **base,
        "data_split": {"train_start": "2024-03-01", "train_end": "2024-01-05"},
    })
    assert r.status_code == 400 and "train_start" in r.json()["detail"]

    # 训练/测试重叠
    r = client.post("/api/experiments", json={
        **base,
        "data_split": {
            "train_start": "2024-01-02", "train_end": "2024-03-01",
            "test_start": "2024-02-01", "test_end": "2024-04-01",
        },
    })
    assert r.status_code == 400 and "overlap" in r.json()["detail"]

    # 超出数据集范围（fixture 数据 2024-01-02 起 120 个交易日）
    r = client.post("/api/experiments", json={
        **base, "data_split": {"train_start": "2023-01-01"},
    })
    assert r.status_code == 400 and "outside dataset range" in r.json()["detail"]


def test_experiment_data_split_applied(client, price_dataset):
    """合法 data_split → EW 回测窗口截取为外包络，结果 dates 落在窗口内。"""
    import time

    split = {
        "train_start": "2024-01-02", "train_end": "2024-02-28",
        "test_start": "2024-03-01", "test_end": "2024-04-30",
    }
    r = client.post("/api/experiments", json={
        "algorithm_id": "equal_weight",
        "dataset_id": price_dataset["dataset_id"],
        "capability": "backtest",
        "data_split": split,
    })
    assert r.status_code == 200, r.text
    exp = r.json()
    assert exp["data_split"] == split

    deadline = time.time() + 90
    state = None
    while time.time() < deadline:
        state = client.get(f"/api/tasks/{exp['experiment_id']}/status").json()
        if state["state"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.4)
    assert state["state"] == "SUCCEEDED", state

    res = client.get(f"/api/results/{exp['experiment_id']}").json()
    assert res["dates"], "result should contain dates"
    assert res["dates"][0] >= "2024-01-02"
    assert res["dates"][-1] <= "2024-04-30"
    assert res["trading_protocol"]["date_split_window"] == {
        "window_start": "2024-01-02", "window_end": "2024-04-30",
    }
