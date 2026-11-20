import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api_server
from services.market_data_crawler import MarketDataCrawlerService, normalize_fetch_request
from services.tools.market_data_crawler import MarketDataCrawlerTool


class FakeCrawler:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "status": "ok",
            "message": "行情数据已更新",
            "modules": {"market": {"status": "ok"}},
            "failedModules": [],
        }

    def fetch(self, arguments):
        self.calls.append(arguments)
        return self.result


def test_api_and_tool_share_normalized_crawler_arguments(monkeypatch):
    fake = FakeCrawler()
    monkeypatch.setattr(api_server, "market_data_crawler", fake)
    client = TestClient(api_server.app)

    response = client.post(
        "/api/data/fetch",
        json={
            "symbol": "000063",
            "startDate": "2024-01-02",
            "endDate": "2024-01-03",
            "dataSource": "baostock",
        },
    )
    assert response.status_code == 200

    MarketDataCrawlerTool(crawler=fake).execute(
        {
            "stockCode": "000063",
            "startDate": "2024-01-02",
            "endDate": "2024-01-03",
            "dataSource": "baostock",
        },
        None,
    )

    expected = {
        "symbol": "000063",
        "start_date": "2024-01-02",
        "end_date": "2024-01-03",
        "data_source": "baostock",
    }
    assert fake.calls == [expected, expected]


def test_normalize_fetch_request_rejects_missing_symbol():
    with pytest.raises(ValueError, match="股票代码"):
        normalize_fetch_request({"startDate": "2024-01-02"})


def test_normalize_fetch_request_keeps_crawl_url_when_supplied():
    normalized = normalize_fetch_request(
        {
            "stockCode": "000063",
            "startDate": "2024-01-02",
            "endDate": "2024-01-03",
            "crawlUrl": "https://finance.eastmoney.com/",
        }
    )

    assert normalized["crawl_url"] == "https://finance.eastmoney.com/"
    assert normalized["data_source"] == "baostock"


def test_tool_requires_stock_code():
    tool = MarketDataCrawlerTool(crawler=FakeCrawler())

    assert tool.missing_parameters({}) == ["stockCode"]
    assert tool.missing_parameters({"stockCode": "000063"}) == []


def test_tool_maps_crawler_status_to_tool_result():
    completed = MarketDataCrawlerTool(crawler=FakeCrawler()).execute(
        {"stockCode": "000063", "startDate": "2024-01-02", "endDate": "2024-01-03"},
        None,
    )
    assert completed.status == "completed"
    assert "行情数据已更新" in completed.summary

    partial = MarketDataCrawlerTool(
        crawler=FakeCrawler(
            {
                "status": "partial",
                "message": "部分数据获取失败: news",
                "failedModules": ["news"],
                "modules": {"market": {"status": "ok"}, "news": {"status": "error"}},
            }
        )
    ).execute(
        {"stockCode": "000063", "startDate": "2024-01-02", "endDate": "2024-01-03"},
        None,
    )
    assert partial.status == "partial"
    assert partial.data["failedModules"] == ["news"]

    failed = MarketDataCrawlerTool(
        crawler=FakeCrawler({"status": "error", "message": "Tushare 需要 token"})
    ).execute(
        {"stockCode": "000063", "startDate": "2024-01-02", "endDate": "2024-01-03"},
        None,
    )
    assert failed.status == "failed"
    assert "token" in failed.summary


def build_service(tmp_path, loader):
    return MarketDataCrawlerService(
        frame_loader=loader,
        eastmoney_fetcher=lambda *args: {},
        data_dir=tmp_path / "data",
        result_dir=tmp_path / "result",
        status_provider=lambda symbol: {"symbol": symbol, "available": False},
    )


def test_service_saves_market_and_result_files(tmp_path):
    frame = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "open": [1, 2],
            "high": [1, 2],
            "low": [1, 2],
            "close": [10, 11],
            "volume": [100, 200],
        }
    )
    calls = {}

    def loader(symbol, start, end, data_source, token):
        calls["arguments"] = (symbol, start, end, data_source, token)
        return frame

    service = build_service(tmp_path, loader)
    result = service.fetch(
        {
            "symbol": "000063",
            "start_date": "2024-01-02",
            "end_date": "2024-01-03",
            "data_source": "baostock",
        }
    )

    assert result["status"] == "ok"
    assert result["count"] == 2
    assert result["latestDate"] == "2024-01-03"
    assert calls["arguments"] == (
        "000063",
        "2024-01-02",
        "2024-01-03",
        "baostock",
        None,
    )
    assert (tmp_path / "data" / "technical_indicators" / "000063.csv").is_file()
    assert (tmp_path / "result" / "000063.csv").is_file()


def test_service_rejects_inverted_date_range(tmp_path):
    service = build_service(tmp_path, loader=lambda *args: None)

    result = service.fetch(
        {
            "symbol": "000063",
            "start_date": "2024-02-02",
            "end_date": "2024-01-02",
            "data_source": "baostock",
        }
    )

    assert result == {
        "status": "error",
        "message": "爬取开始日期不能晚于结束日期",
    }


def test_service_turns_loader_failure_into_error_result(tmp_path):
    def loader(*_args):
        raise ValueError("Baostock 未获取到 000063 的数据")

    service = build_service(tmp_path, loader)

    result = service.fetch(
        {
            "symbol": "000063",
            "start_date": "2024-01-02",
            "end_date": "2024-01-03",
            "data_source": "baostock",
        }
    )

    assert result["status"] == "error"
    assert "未获取到" in result["message"]
