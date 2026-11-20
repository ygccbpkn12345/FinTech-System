from services.data_fetch_service import build_fetch_result


def test_full_fetch_result_is_ok_and_includes_refreshed_status():
    modules = {
        name: {"status": "ok", "count": 3}
        for name in ("market", "news", "balanceSheet", "incomeStatement", "cashFlowStatement")
    }
    status = {"available": True, "hasNewsData": True, "hasFundamentalData": True}

    result = build_fetch_result("600519", "2026-08-11", 100, modules, status)

    assert result["status"] == "ok"
    assert result["dataStatus"] is status
    assert result["failedModules"] == []


def test_one_eastmoney_failure_returns_partial_with_module_name():
    modules = {
        "market": {"status": "ok", "count": 100},
        "news": {"status": "error", "message": "timeout", "count": 0},
        "balanceSheet": {"status": "ok", "count": 3},
        "incomeStatement": {"status": "ok", "count": 3},
        "cashFlowStatement": {"status": "ok", "count": 3},
    }

    result = build_fetch_result("600519", "2026-08-11", 100, modules, {"available": False})

    assert result["status"] == "partial"
    assert result["failedModules"] == ["news"]
    assert "news" in result["message"]


def test_fetch_result_echoes_requested_date_range():
    result = build_fetch_result(
        "600519",
        "2026-08-08",
        20,
        {"market": {"status": "ok", "count": 20}},
        {"available": True},
        start_date="2026-08-01",
        end_date="2026-08-10",
    )

    assert result["startDate"] == "2026-08-01"
    assert result["endDate"] == "2026-08-10"
