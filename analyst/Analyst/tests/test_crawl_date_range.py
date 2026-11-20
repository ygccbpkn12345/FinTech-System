from datetime import date

import pytest

from services.crawl_date_range import validate_crawl_date_range


def test_valid_range_returns_iso_dates():
    assert validate_crawl_date_range("2026-01-01", "2026-08-10", today=date(2026, 8, 11)) == (
        "2026-01-01",
        "2026-08-10",
    )


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (None, "2026-08-10", "开始日期"),
        ("2026-01-01", None, "结束日期"),
        ("2026/01/01", "2026-08-10", "YYYY-MM-DD"),
        ("2026-08-10", "2026-01-01", "不能晚于"),
        ("2026-01-01", "2026-08-12", "未来日期"),
    ],
)
def test_invalid_range_is_rejected(start, end, message):
    with pytest.raises(ValueError, match=message):
        validate_crawl_date_range(start, end, today=date(2026, 8, 11))
