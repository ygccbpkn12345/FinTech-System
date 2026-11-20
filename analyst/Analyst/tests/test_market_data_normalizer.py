from __future__ import annotations

import pandas as pd

from services.market_data_normalizer import normalize_market_frame


def test_empty_numeric_cells_do_not_break_market_data_normalization():
    raw = pd.DataFrame(
        [
            ["2026-08-08", "10", "11", "9", "10.5", ""],
            ["2026-08-09", "", "", "", "", ""],
            ["2026-08-10", "10.5", "12", "10", "11.5", "1200"],
        ],
        columns=["date", "open", "high", "low", "close", "volume"],
    )

    normalized = normalize_market_frame(raw)

    assert normalized["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-08-08",
        "2026-08-10",
    ]
    assert normalized["volume"].tolist() == [0.0, 1200.0]
    assert normalized["close"].tolist() == [10.5, 11.5]
