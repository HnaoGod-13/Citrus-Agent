from copy import deepcopy
from dataclasses import dataclass

import pytest
from streamlit.testing.v1 import AppTest

from app import batch_research


@pytest.mark.parametrize("text,passed,status", [
    ("农残检测通过", True, "passed"),
    ("农残检测未通过", False, "failed"),
    ("农残尚未检测", None, "missing"),
    ("农残报告已上传", None, "result_missing"),
    ("已完成检测", None, "missing"),
])
def test_batch_mapping_does_not_turn_report_presence_into_pass(text, passed, status):
    source = {"batch": {"batch": "B-1", "quantity_kg": 35000, "brix": 0, "safety_tests": [text]}}
    batch = batch_research.workflow_batch(source)
    assert batch["batch_id"] == "B-1"
    assert batch["weight_kg"] == 35000
    assert batch["brix"] == 0
    assert batch["pesticide"] is passed
    assert batch["pesticide_status"] == status
    assert batch["heavy_metal"] is None


def test_generation_calls_evidence_workflow_with_batch_goal_and_selected_mode(monkeypatch):
    source = {"batch": {"batch": "B-2", "target_product": "NFC 柑橘汁", "variety": "脐橙"},
              "task_context": {"record_id": "record-1", "revision": "2"}}
    received = {}
    evidence = [{"document_id": "paper-1", "chunk_id": "chunk-1", "title": "Source paper", "chunk_text": "Original evidence"}]

    @dataclass
    class Score:
        direction: str = "NFC 果汁"

    def run(batch, observation, **kwargs):
        received.update(batch=batch, **kwargs)
        kwargs["progress_callback"]("actual retrieval progress")
        return {"scores": [Score()], "agent_steps": [], "quality_risks": [], "evidence": evidence,
                "deep_retrieval_stats": {"database_available": True, "retrieval_complete": True}}

    monkeypatch.setattr(batch_research.workflow, "run_demo_agent", run)
    progress = []
    result = batch_research.generate_batch_research(source, page="process", retrieval_mode="deep", progress_callback=progress.append)
    assert received["batch"]["batch_id"] == "B-2"
    assert "NFC 柑橘汁" in received["analysis_question"]
    assert received["retrieval_mode"] == "deep"
    assert progress == ["actual retrieval progress"]
    assert result["evidence"] == evidence
    assert result["scores"][0]["direction"] == "NFC 果汁"
    assert result["task_context"] == source["task_context"]
    assert "1 篇文献、1 条证据" in result["research_status"]


@pytest.mark.parametrize("stats", [
    {"database_available": False}, {"retrieval_complete": False},
    {"timed_out": True}, {"retrieval_error": "Search failed"},
])
def test_incomplete_retrieval_is_never_reported_as_complete(stats):
    summary, warning = batch_research.retrieval_summary({"deep_retrieval_stats": stats, "evidence": [{"title": "Partial result"}]})
    assert warning
    assert "已检索本地文献库" not in summary


def test_no_hits_and_changed_record_revision():
    summary, warning = batch_research.retrieval_summary({"evidence": []})
    assert warning and "未找到可用依据" in summary
    source = {"batch": {"batch": "B-1"}, "task_context": {"record_id": "r1", "revision": 1}}
    changed = deepcopy(source)
    changed["task_context"]["revision"] = 2
    assert batch_research.input_key(source) != batch_research.input_key(changed)


PAGE_APP = '''
import streamlit as st
from unittest.mock import patch
from app.ui import product_pages
from app import batch_research

def generate(source, **kwargs):
    st.session_state.calls = st.session_state.get("calls", 0) + 1
    if st.session_state.get("fail_research"):
        raise RuntimeError("unavailable")
    kwargs["progress_callback"]("正在执行真实检索")
    return {
        "batch": source["batch"], "cleaning": source["cleaning"],
        "scores": [{"direction": "基于文献的路线", "match_level": "优先", "evidence_support": "有限（1篇直接相关文献）", "data_confidence": "中", "score": 70}],
        "processing_plan": {"route": "基于文献的路线", "stages": [{"name": "有依据的工序"}]},
        "parameterized_plan": {"rows": [{"step": "杀菌", "parameter_status": "暂无可靠参数", "source_ids": []}]},
        "evidence": [{"title": "实际文献 A", "chunk_text": "可回查的原文", "document_id": "A", "chunk_id": "A-1"}],
        "agent_steps": [{"name": "检索", "status": "完成", "observation": "纳入实际文献 A"}],
        "research_input_key": batch_research.input_key(source),
    }

with patch.object(batch_research, "generate_batch_research", side_effect=generate):
    product_pages.render_product_page(PAGE)
'''


@pytest.mark.parametrize("page", ["decision", "process"])
def test_example_and_saved_batch_buttons_run_research_and_rerun_uses_cached_result(page):
    app = AppTest.from_string(PAGE_APP.replace("PAGE)", repr(page) + ")"), default_timeout=30).run()
    app.button(key=f"{page}_example_nfc").click().run()
    assert not app.exception
    assert app.session_state["calls"] == 1
    assert "本次文献依据" in [item.value for item in app.subheader]
    assert "可回查的原文" in [item.value for item in app.text]
    app.run()
    assert app.session_state["calls"] == 1
    # The sample cards above are the single entry point; the old duplicate
    # wide generation button is intentionally absent on both pages.
    assert not any(button.key == f"{page}_generate" for button in app.button)
    app.button(key=f"{page}_example_nfc").click().run()
    assert app.session_state["calls"] == 2
    # A different saved revision must require analysis before showing results.
    model = deepcopy(app.session_state["industry_ui_model"])
    model["analysis"]["task_context"]["revision"] = "2"
    app.session_state["industry_ui_model"] = model
    app.run()
    assert not app.exception
    assert "本次文献依据" not in [item.value for item in app.subheader]
    app.button(key=f"{page}_example_nfc").click().run()
    assert app.session_state["calls"] == 3


def test_failed_generation_is_not_marked_done_and_can_retry():
    app = AppTest.from_string(PAGE_APP.replace("PAGE)", "'decision')"), default_timeout=30).run()
    app.session_state["fail_research"] = True
    app.button(key="decision_example_nfc").click().run()
    assert not app.exception
    assert app.session_state["decision_generated"] is False
    assert app.error
    assert "本次文献依据" not in [item.value for item in app.subheader]
    app.session_state["fail_research"] = False
    app.button(key="decision_example_nfc").click().run()
    assert not app.exception
    assert app.session_state["decision_generated"] is True
