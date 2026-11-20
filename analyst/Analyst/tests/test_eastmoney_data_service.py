import pandas as pd
import pytest

from services.eastmoney_data_service import (
    EastmoneyDataService,
    EastmoneyResponseError,
    eastmoney_security_code,
    normalize_financial_payload,
    normalize_news_payload,
)


class FakeResponse:
    def __init__(self, payload, *, jsonp=False):
        self._payload = payload
        self.text = f"callback({__import__('json').dumps(payload, ensure_ascii=False)})" if jsonp else ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params", {})))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_eastmoney_security_code_supports_shanghai_and_shenzhen():
    assert eastmoney_security_code("600519") == "600519.SH"
    assert eastmoney_security_code("000063") == "000063.SZ"
    assert eastmoney_security_code("300750.SZ") == "300750.SZ"


def test_news_payload_maps_existing_analyzer_columns_and_strips_highlights():
    payload = {
        "result": {
            "cmsArticleWebOld": [
                {
                    "date": "2026-08-11 09:30:00",
                    "title": "<em>贵州茅台</em>发布公告",
                    "content": "公司<em>业绩</em>增长",
                    "mediaName": "东方财富网",
                    "code": "202608111234",
                }
            ]
        }
    }

    frame = normalize_news_payload(payload, "600519")

    assert list(frame.columns) == ["Publish Time", "Title", "keyword", "source", "Content"]
    assert frame.iloc[0].to_dict() == {
        "Publish Time": pd.Timestamp("2026-08-11 09:30:00"),
        "Title": "贵州茅台发布公告",
        "keyword": "600519",
        "source": "东方财富网",
        "Content": "公司业绩增长",
    }


def test_empty_news_payload_is_rejected():
    with pytest.raises(EastmoneyResponseError, match="新闻.*为空"):
        normalize_news_payload({"result": {"cmsArticleWebOld": []}}, "600519")


def test_financial_payload_preserves_columns_and_keeps_latest_update_per_report():
    payload = {
        "success": True,
        "result": {
            "data": [
                {
                    "SECURITY_CODE": "600519",
                    "REPORT_DATE": "2026-03-31 00:00:00",
                    "UPDATE_DATE": "2026-04-20 00:00:00",
                    "TOTAL_ASSETS": "100",
                },
                {
                    "SECURITY_CODE": "600519",
                    "REPORT_DATE": "2026-03-31 00:00:00",
                    "UPDATE_DATE": "2026-04-25 00:00:00",
                    "TOTAL_ASSETS": "101",
                },
                {
                    "SECURITY_CODE": "600519",
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "UPDATE_DATE": "2026-04-01 00:00:00",
                    "TOTAL_ASSETS": "90",
                },
            ]
        },
    }

    frame = normalize_financial_payload(payload, "资产负债表")

    assert list(frame["REPORT_DATE"].dt.strftime("%Y-%m-%d")) == ["2026-03-31", "2025-12-31"]
    assert frame.iloc[0]["TOTAL_ASSETS"] == "101"


def test_financial_payload_rejects_missing_report_date():
    with pytest.raises(EastmoneyResponseError, match="REPORT_DATE"):
        normalize_financial_payload(
            {"success": True, "result": {"data": [{"SECURITY_CODE": "600519"}]}},
            "利润表",
        )


def test_fetch_news_reads_multiple_pages_and_merges_existing_file(tmp_path):
    old = pd.DataFrame(
        [{"Publish Time": "2026-08-10", "Title": "旧闻", "keyword": "600519", "source": "旧来源", "Content": "旧内容"}]
    )
    target = tmp_path / "news" / "600519.csv"
    target.parent.mkdir(parents=True)
    old.to_csv(target, index=False)
    page_1 = {"result": {"cmsArticleWebOld": [{"date": "2026-08-11", "title": "新消息", "content": "内容", "mediaName": "东财", "code": "1"}]}}
    page_2 = {"result": {"cmsArticleWebOld": []}}
    client = FakeClient([FakeResponse(page_1, jsonp=True), FakeResponse(page_2, jsonp=True)])

    result = EastmoneyDataService(client=client, data_dir=tmp_path, max_news_pages=5).fetch_news("600519")

    saved = pd.read_csv(target)
    assert result["status"] == "ok"
    assert result["count"] == 2
    assert set(saved["Title"]) == {"旧闻", "新消息"}
    assert len(client.calls) == 2


def test_fetch_all_isolates_one_statement_failure(tmp_path):
    news = {"result": {"cmsArticleWebOld": [{"date": "2026-08-11", "title": "新闻", "content": "内容", "mediaName": "东财"}]}}
    news_end = {"result": {"cmsArticleWebOld": []}}
    statement = {"success": True, "result": {"data": [{"SECURITY_CODE": "600519", "REPORT_DATE": "2026-03-31", "UPDATE_DATE": "2026-04-25"}]}}
    client = FakeClient([
        FakeResponse(news, jsonp=True), FakeResponse(news_end, jsonp=True),
        FakeResponse(statement), RuntimeError("income unavailable"), FakeResponse(statement),
    ])

    modules = EastmoneyDataService(client=client, data_dir=tmp_path, retries=0).fetch_all("600519")

    assert modules["news"]["status"] == "ok"
    assert modules["balanceSheet"]["status"] == "ok"
    assert modules["incomeStatement"]["status"] == "error"
    assert modules["cashFlowStatement"]["status"] == "ok"
    assert (tmp_path / "fundamentals" / "Balance Sheet" / "600519.csv").is_file()
    assert not (tmp_path / "fundamentals" / "Income Statement" / "600519.csv").exists()


def test_statement_request_only_uses_supported_report_date_sort(tmp_path):
    statement = {"success": True, "result": {"data": [{"SECURITY_CODE": "600519", "REPORT_DATE": "2026-03-31", "UPDATE_DATE": "2026-04-25"}]}}
    client = FakeClient([FakeResponse(statement)])

    EastmoneyDataService(client=client, data_dir=tmp_path).fetch_statement("600519", "balanceSheet")

    assert client.calls[0][1]["sortColumns"] == "REPORT_DATE"
    assert client.calls[0][1]["sortTypes"] == "-1"


def test_news_payload_filters_requested_date_range():
    payload = {"result": {"cmsArticleWebOld": [
        {"date": "2026-08-01", "title": "范围内", "content": "A", "mediaName": "东财"},
        {"date": "2026-07-31", "title": "范围前", "content": "B", "mediaName": "东财"},
        {"date": "2026-08-11", "title": "范围后", "content": "C", "mediaName": "东财"},
    ]}}

    frame = normalize_news_payload(payload, "600519", "2026-08-01", "2026-08-10")

    assert frame["Title"].tolist() == ["范围内"]


def test_financial_payload_excludes_reports_announced_after_end_date():
    payload = {"success": True, "result": {"data": [
        {"SECURITY_CODE": "600519", "REPORT_DATE": "2026-06-30", "NOTICE_DATE": "2026-08-20", "UPDATE_DATE": "2026-08-20"},
        {"SECURITY_CODE": "600519", "REPORT_DATE": "2026-03-31", "NOTICE_DATE": "2026-04-25", "UPDATE_DATE": "2026-04-25"},
    ]}}

    frame = normalize_financial_payload(payload, "资产负债表", end_date="2026-08-10")

    assert frame["REPORT_DATE"].dt.strftime("%Y-%m-%d").tolist() == ["2026-03-31"]


def test_financial_payload_rejects_when_no_report_was_visible_by_end_date():
    payload = {"success": True, "result": {"data": [
        {"SECURITY_CODE": "600519", "REPORT_DATE": "2026-06-30", "NOTICE_DATE": "2026-08-20"},
    ]}}

    with pytest.raises(EastmoneyResponseError, match="截止.*无可用数据"):
        normalize_financial_payload(payload, "利润表", end_date="2026-08-10")
