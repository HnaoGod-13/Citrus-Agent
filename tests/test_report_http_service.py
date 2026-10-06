from pathlib import Path

import pytest

from app.reporting import http_service


def test_build_generate_kwargs_maps_public_envelope(tmp_path):
    payload = {
        "request_id": "req-1",
        "project": {"title": "柑橘加工项目", "region": "广西南宁"},
        "facts": {"origin": "广西南宁", "variety": "沃柑", "target_product": "NFC果汁"},
        "route": {"label": "鲜果榨汁", "alternatives": [{"label": "浓缩汁"}]},
        "process": {"stages": ["分选", "榨汁"], "quality_controls": ["微生物控制"]},
        "sources": [{"title": "官方资料", "url": "https://example.gov.cn/a", "snippet": "产业资料"}],
        "report_profile": {"purpose": "项目申报", "template": "项目报告"},
    }
    kwargs = http_service.build_generate_kwargs(payload, output_dir=tmp_path)
    assert kwargs["task_id"] == "req-1"
    assert kwargs["record_id"].startswith("record_")
    assert kwargs["analysis"]["cleaning"]["normalized"]["variety"] == "沃柑"
    assert kwargs["analysis"]["recommended_route"]["label"] == "鲜果榨汁"
    assert kwargs["analysis"]["processing_plan"]["stages"] == ["分选", "榨汁"]
    assert kwargs["analysis"]["report_enrichment"]["evidence"][0]["source_type"] == "local"
    assert kwargs["profile"]["purpose"] == "项目申报"
    assert kwargs["output_dir"] == tmp_path


def test_build_generate_kwargs_requires_facts():
    with pytest.raises(http_service.ReportRequestError, match="facts"):
        http_service.build_generate_kwargs({"project": {"title": "缺少事实"}})


def test_generate_from_payload_delegates_to_core(monkeypatch, tmp_path):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "markdown": "# 报告"}

    monkeypatch.setattr(http_service, "generate_project_report", fake_generate)
    result = http_service.generate_from_payload(
        {"facts": {"origin": "广西南宁"}, "project": {"title": "测试项目"}},
        output_dir=tmp_path,
    )
    assert result["status"] == "completed"
    assert captured["analysis"]["cleaning"]["normalized"]["origin"] == "广西南宁"
    assert captured["profile"]["title"] == "测试项目"


def test_health_endpoint_shape():
    assert http_service.MAX_BODY_BYTES == 2 * 1024 * 1024
