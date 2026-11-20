import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from config import DEFAULT_CONFIG
from services import analysis_runner


@pytest.mark.parametrize("data_source", ["local_file", "baostock", "tushare"])
def test_analysis_keeps_full_data_root_after_price_download(tmp_path, monkeypatch, data_source):
    data_dir = tmp_path / "configured-data"
    result_dir = tmp_path / "configured-results"
    dates = ["2026-01-21", "2026-01-22", "2026-01-23"]
    frame = pd.DataFrame({
        "date": dates, "open": [10, 11, 12], "high": [11, 12, 13],
        "low": [9, 10, 11], "close": [10, 11, 12], "volume": [100, 110, 120],
    })
    technical = data_dir / "technical_indicators" / "000063.csv"
    technical.parent.mkdir(parents=True)
    frame.to_csv(technical, index=False)
    for folder in ["news", "fundamentals/Balance Sheet", "fundamentals/Income Statement", "fundamentals/Cash Flow Statement"]:
        path = data_dir / folder / "000063.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("existing local data", encoding="utf-8")
    result_dir.mkdir()
    result_file = result_dir / "000063.csv"
    pd.DataFrame({"date": dates, "pct_change": [1, 2, 3]}).to_csv(result_file, index=False)
    original_technical = technical.read_bytes()
    original_result = result_file.read_bytes()

    # Return two days of downloaded prices; retain the local future outcome for reflection.
    class BaostockRows:
        error_code = "0"
        error_msg = "success"

        def __init__(self):
            self.rows = iter(frame.iloc[:2].astype(str).values.tolist())

        def next(self):
            self.row = next(self.rows, None)
            return self.row is not None

        def get_row_data(self):
            return self.row

    monkeypatch.setitem(sys.modules, "baostock", SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0"), logout=lambda: None,
        query_history_k_data_plus=lambda *args, **kwargs: BaostockRows(),
    ))
    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(
        set_token=lambda token: None,
        pro_api=lambda: SimpleNamespace(daily=lambda **kwargs: frame.iloc[:2].copy()),
    ))
    snapshot = {
        **DEFAULT_CONFIG, "data_dir": str(data_dir), "result": str(result_dir),
        "data_cache": str(tmp_path / "cache"), "api_key": "test-key",
        "tushare_token": "test-token", "data_source": data_source,
    }
    seen = {}

    class Runner:
        def __init__(self, config, symbol, **kwargs):
            seen.update(config=config, symbol=symbol)

        def run_main(self, *args, **kwargs):
            seen["data_root"] = analysis_runner.utils.DATA_DIR
            seen["result_root"] = analysis_runner.utils.RESULT_DIR
            return {}, lambda state: state

    monkeypatch.setattr(analysis_runner, "TextGradTraderRunner", Runner)
    monkeypatch.setattr(analysis_runner, "map_final_state_to_frontend", lambda *args, **kwargs: {})
    analysis_runner.run_full_analysis(
        "000063", "2026-01-22", data_source=data_source,
        runtime_config=snapshot, defer_postprocessing=True,
    )

    assert seen["symbol"] == "000063"
    assert seen["data_root"] == str(data_dir.resolve())
    assert seen["result_root"] == str(result_dir.resolve())
    assert technical.read_bytes() == original_technical
    assert result_file.read_bytes() == original_result
    if data_source != "local_file":
        assert (data_dir / "temp" / "000063.csv").is_file()
        assert (data_dir / "temp_result" / "000063.csv").is_file()
