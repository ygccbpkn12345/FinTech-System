from __future__ import annotations

from datetime import date, datetime


def validate_crawl_date_range(
    start_date: str | None,
    end_date: str | None,
    *,
    today: date | None = None,
) -> tuple[str, str]:
    if not start_date:
        raise ValueError("请选择爬取开始日期")
    if not end_date:
        raise ValueError("请选择爬取结束日期")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("爬取日期格式必须为 YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("爬取开始日期不能晚于结束日期")
    if end > (today or date.today()):
        raise ValueError("爬取结束日期不能是未来日期")
    return start.isoformat(), end.isoformat()
