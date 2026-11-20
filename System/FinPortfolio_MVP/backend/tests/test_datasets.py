"""数据集登记 / 校验 / 兼容性检查测试。"""
import pytest

from app.services.dataset_service import DatasetError, DatasetService


def _write_prices(path, n_days=30, tics=("A", "B")):
    import pandas as pd
    rows = []
    dates = pd.bdate_range("2024-01-02", periods=n_days)
    for tic in tics:
        for i, d in enumerate(dates):
            rows.append({"date": d.strftime("%Y-%m-%d"), "tic": tic,
                         "close": 100 + i + hash(tic) % 7})
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_register_and_auto_stats(tmp_path):
    svc = DatasetService(tmp_path / "ds")
    src = _write_prices(tmp_path / "src" / "prices.csv")
    meta = svc.register(
        name="Test Prices", market="TEST",
        files={"prices": "prices.csv"},
        available_modalities=["prices"],
        storage_mode="reference",
        source_dir=str(tmp_path / "src"),
    )
    assert meta["assets"] == ["A", "B"]
    assert meta["date_range"]["start"] == "2024-01-02"
    assert meta["date_range"]["days"] == 30
    assert "close" in meta["feature_schema"]
    assert svc.list_datasets()[0]["dataset_id"] == meta["dataset_id"]


def test_register_missing_file_rejected(tmp_path):
    svc = DatasetService(tmp_path / "ds")
    with pytest.raises(DatasetError):
        svc.register(
            name="Bad", market="X",
            files={"prices": "nope.csv"},
            available_modalities=["prices"],
            storage_mode="reference",
            source_dir=str(tmp_path),
        )


def test_validate_reports_missing_and_dates(tmp_path):
    svc = DatasetService(tmp_path / "ds")
    src = _write_prices(tmp_path / "src" / "prices.csv")
    meta = svc.register(
        name="V", market="TEST",
        files={"prices": "prices.csv"},
        available_modalities=["prices"],
        storage_mode="reference",
        source_dir=str(tmp_path / "src"),
    )
    report = svc.validate(meta["dataset_id"])
    assert report["valid"] is True
    fr = report["file_reports"]["prices"]
    assert fr["date_range"]["unique_days"] == 30

    # 删除文件后再校验 → 如实报告
    src.unlink()
    report = svc.validate(meta["dataset_id"])
    assert report["valid"] is False
    assert any("missing file" in p for p in report["problems"])


def test_compatibility_with_equal_weight(real_registry, tmp_path):
    svc = DatasetService(tmp_path / "ds")
    _write_prices(tmp_path / "src" / "prices.csv")
    svc.register(
        name="C", market="TEST",
        files={"prices": "prices.csv"},
        available_modalities=["prices"],
        storage_mode="reference",
        source_dir=str(tmp_path / "src"),
    )
    eq = real_registry.get("equal_weight")
    asacpl = real_registry.get("asacpl")
    hmmp = real_registry.get("hmmp")

    ds_id = svc.list_datasets()[0]["dataset_id"]
    assert svc.check_compatibility(eq, ds_id)["compatible"] is True

    c_asacpl = svc.check_compatibility(asacpl, ds_id)
    assert c_asacpl["compatible"] is False
    assert any("modality" in w for w in c_asacpl["warnings"])

    c_hmmp = svc.check_compatibility(hmmp, ds_id)
    assert c_hmmp["compatible"] is False

    # 完整 ASACPL 数据集（含协方差/特征）对 asacpl 兼容
    import pandas as pd
    src2 = tmp_path / "src2"
    src2.mkdir()
    _write_prices(src2 / "02_train_CNN.csv", tics=("A", "B"))
    _write_prices(src2 / "02_test_CNN.csv", tics=("A", "B"))
    for f in ("02_train_CNN.csv", "02_test_CNN.csv"):
        df = pd.read_csv(src2 / f)
        df["cov_list"] = "[0.0 0.0 0.0 0.0]"
        for k in "1234":
            df[f"f{k}"] = 0.1
        df.to_csv(src2 / f, index=False)
    meta2 = svc.register(
        name="ASACPL-like", market="SP500",
        files={"train_prices": "02_train_CNN.csv", "test_prices": "02_test_CNN.csv"},
        available_modalities=["prices", "covariance", "tech_indicators"],
        storage_mode="reference",
        source_dir=str(src2),
    )
    assert svc.check_compatibility(asacpl, meta2["dataset_id"])["compatible"] is True
    # market 不匹配时给出警告但保持兼容性结论明确
    meta3 = svc.register(
        name="ASACPL-like-SSE", market="SSE50",
        files={"train_prices": "02_train_CNN.csv", "test_prices": "02_test_CNN.csv"},
        available_modalities=["prices", "covariance", "tech_indicators"],
        storage_mode="reference",
        source_dir=str(src2),
    )
    check = svc.check_compatibility(asacpl, meta3["dataset_id"])
    assert check["compatible"] is True


def test_upload_register_copy_mode(client, tmp_path):
    import pandas as pd
    src = tmp_path / "up"
    _write_prices(src / "prices.csv")
    resp = client.post("/api/datasets", json={
        "name": "Uploaded",
        "market": "TEST",
        "files": {"prices": "prices.csv"},
        "available_modalities": ["prices"],
        "storage_mode": "copy",
        "source_dir": str(src),
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()
    assert meta["storage_mode"] == "copy"
    from pathlib import Path
    assert (Path(meta["storage_path"]) / "prices.csv").is_file()
