from pathlib import Path
import sys
import types

import pytest

from agent.llm_client import DeepSeekAPIError
from app.intake_pipeline import build_task_context, run_intake_pipeline
from app.reporting import service
from app.reporting import web_search


def sample_document():
    return {
        "id": "ic_" + "a" * 32,
        "status": "submitted",
        "revision": 3,
        "task_id": "task_fixed_batch",
        "side": "supplier",
        "fields": {
            "profile.organization": "测试合作社",
            "base.origin": "广西南宁武鸣",
            "base.variety": "沃柑",
            "harvest.batch": "B-0903-001",
            "harvest.quantity": "20",
            "harvest.unit": "吨",
            "quality.brix": "12.8",
            "quality.testStatus": "已有检测资料",
            "product.name": "NFC果汁",
        },
        "rows": {"tests": [{"conclusion": "合格"}]},
    }


def test_task_context_does_not_change_with_revision():
    first = build_task_context("ic_batch", 1)
    later = build_task_context("ic_batch", 9)
    assert first["task_id"] == later["task_id"]
    assert later["revision"] == "9"


def test_report_requires_real_llm(monkeypatch, tmp_path):
    document = sample_document()
    analysis = run_intake_pipeline(document, document["id"], 3, document["task_id"])
    monkeypatch.setattr(service, "get_deepseek_api_key", lambda: "")
    with pytest.raises(DeepSeekAPIError, match="API Key"):
        service.generate_project_report(
            task_id=document["task_id"], record_id=document["id"], document=document,
            analysis=analysis, output_dir=tmp_path,
            web_searcher=lambda queries: {"evidence": [], "errors": [], "queries": queries, "status": "completed"},
        )


def test_report_style_checker_rejects_internal_explanations():
    markdown = """# 项目报告

## 项目摘要
这是由大模型撰写的项目摘要。[1] 系统清洗后的加权数据质量分为 90/100，但不代表可直接投资。

## 结论和立项建议
项目工艺路线确定为 NFC 果汁路线，建议按计划推进建设。

## 待人工复核项
- 待补充建设地点
"""
    issues = service._report_style_issues(markdown)
    for phrase in ("大模型", "系统清洗", "加权数据质量", "不代表", "待人工复核", "待补充"):
        assert phrase in "".join(issues)


def test_report_combines_web_evidence_llm_and_word_export(monkeypatch, tmp_path):
    document = sample_document()
    analysis = run_intake_pipeline(document, document["id"], 3, document["task_id"])
    captured = {}

    def fake_llm(facts, analysis_input, profile, sources):
        captured["facts"] = facts
        captured["sources"] = sources
        captured["profile"] = profile
        captured["web_status"] = analysis_input["web_research"]["status"]
        return "# 项目报告\n\n## 项目摘要\n" + ("项目建设方案具备完整的事实依据和可执行的实施路径。" * 100)

    fake_export = types.ModuleType("app.reporting.docx_export")
    def write_docx(markdown, output_path, **kwargs):
        Path(output_path).write_bytes(b"PK-test-docx")
        return Path(output_path)
    fake_export.markdown_to_docx = write_docx
    monkeypatch.setitem(sys.modules, "app.reporting.docx_export", fake_export)

    result = service.generate_project_report(
        task_id=document["task_id"], record_id=document["id"], document=document,
        analysis=analysis, output_dir=tmp_path, llm_writer=fake_llm,
        profile={"title": "测试项目报告", "templateData": "base64-must-not-enter-prompt", "markdown": "old report"},
        web_searcher=lambda queries: {
            "evidence": [{"title": "官方产业资料", "url": "https://example.gov.cn/report", "snippet": "武鸣沃柑产业资料", "source_type": "internet"}],
            "errors": [], "queries": queries, "status": "completed",
        },
    )
    assert result["status"] == "completed"
    assert result["llm_used"] is True
    assert result["generation_mode"] == "injected_llm"
    assert captured["facts"]["variety"] == "沃柑"
    assert captured["sources"][0]["source_type"] == "internet"
    assert captured["web_status"] == "completed"
    assert captured["profile"]["reportType"] == "项目报告"
    assert "templateData" not in captured["profile"] and "markdown" not in captured["profile"]
    assert Path(result["docx_path"]).read_bytes() == b"PK-test-docx"


def test_web_search_tries_the_next_provider_after_a_failure(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "configured-for-test")
    monkeypatch.setattr(web_search, "_tavily_search", lambda *args: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(web_search, "_ddg_search", lambda *args: (_ for _ in ()).throw(TimeoutError("slow")))
    monkeypatch.setattr(web_search, "_bing_rss_search", lambda query, limit: [{
        "title": "官方资料", "url": "https://example.gov.cn/a", "snippet": "摘要",
        "query": query, "source_type": "internet",
    }])
    result = web_search.search_web(["武鸣 沃柑 产业"], 3)
    assert result["status"] == "completed"
    assert result["evidence"][0]["title"] == "官方资料"
    assert len(result["errors"]) == 2
