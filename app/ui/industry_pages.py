"""Industry canvas with private intake persistence and session-scoped other tools.

Intake records and attachments use the server-established scope. Marketplace
publication and counterparty contact are not performed by this component.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
import base64
import binascii
import tempfile
from copy import deepcopy

import streamlit as st
from app.intake_schema import intake_schema
from app.intake_store import IntakeStore
from app.intake_pipeline import build_task_context, run_intake_pipeline
from app.report_enrichment import enrich_report_context
from app.reporting import generate_project_report
from agent import workflow as agent_workflow
from agent.llm_client import DeepSeekAPIError

_ASSETS = Path(__file__).parent / "industry_workspace"


def current_industry_view() -> str:
    allowed = {"data", "market", "visuals", "reports"}
    legacy = {"production": "data", "supply": "market", "demand": "market", "match": "market"}
    query = st.query_params.get("industry", "")
    if isinstance(query, list):
        query = query[0] if query else ""
    query = str(query).strip().lower()
    query = legacy.get(query, query)
    saved = legacy.get(st.session_state.get("industry_workspace_view", "data"), st.session_state.get("industry_workspace_view", "data"))
    selected = query if query in allowed else saved if saved in allowed else "data"
    st.session_state.industry_workspace_view = selected
    return selected


def _save_snapshot() -> None:
    snapshot = st.session_state.get("industry_workspace_canvas", {}).get("snapshot")
    if isinstance(snapshot, dict):
        st.session_state.industry_ui_model = snapshot
        context = snapshot.get("taskContext") or snapshot.get("task_context")
        if isinstance(context, dict):
            st.session_state.industry_task_context = dict(context)


def _intake_store():
    from agent.memory_config import MEMORY_DB_PATH
    return IntakeStore(Path(MEMORY_DB_PATH).with_name("industry_intake.db"))


def _scope():
    return (str(st.session_state.get("memory_user_id") or ""),
            str(st.session_state.get("memory_project_id") or ""))


def _enrich_report(document: dict) -> dict:
    """Use the packaged literature index when building a report context."""
    try:
        from agent import rag as agent_rag

        return enrich_report_context(document, searcher=agent_rag.search_knowledge)
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return enrich_report_context(document)


def _document_task_context(document: dict) -> dict:
    """Return the batch identity without running any draft analysis."""
    task_id = str(document.get("task_id") or "").strip()
    if not task_id:
        return {}
    return build_task_context(
        str(document.get("id") or ""),
        document.get("revision") or 1,
        task_id,
    )


def restore_active_context(record_id: str = "") -> bool:
    """Restore the selected saved batch before the sidebar is rendered."""
    requested = str(record_id or st.session_state.get("industry_active_record_id") or "").strip()
    scope = _scope()
    if not requested or not all(scope):
        return False
    current = st.session_state.get("industry_task_context") or {}
    if str(current.get("record_id") or "") == requested:
        return True
    try:
        document = _intake_store().load(*scope, requested)
        analysis = None
        if document.get("status") == "submitted":
            analysis = run_intake_pipeline(
                document,
                str(document.get("id") or requested),
                document.get("revision") or 1,
                document.get("task_id") or None,
            )
            analysis["report_enrichment"] = _enrich_report(document)
    except (ValueError, TypeError, KeyError, sqlite3.Error, OSError):
        return False
    model = deepcopy(st.session_state.get("industry_ui_model", {}))
    model.update(activeIntakeReport=document)
    context = (analysis or {}).get("task_context") or _document_task_context(document)
    if analysis:
        model["analysis"] = analysis
    else:
        model.pop("analysis", None)
    if context:
        model["taskContext"] = context
    else:
        model.pop("taskContext", None)
    collection = model.setdefault("collection", {})
    collection.setdefault("documents", {})[document["side"]] = document
    collection["side"] = document["side"]
    collection["panel"] = "form"
    collection.setdefault("steps", {})[document["side"]] = 0
    collection.setdefault("dirty", {})[document["side"]] = False
    st.session_state.industry_ui_model = model
    st.session_state.industry_task_context = dict(context)
    st.session_state.industry_active_record_id = requested
    return True


def _intake_action():
    action = st.session_state.get("industry_workspace_canvas", {}).get("intake_action")
    if not isinstance(action, dict) or not isinstance(action.get("requestId"), str):
        return
    if action["requestId"] == st.session_state.get("intake_last_request"):
        return
    st.session_state.intake_last_request = action["requestId"]
    operation = action.get("operation")
    try:
        store, scope = _intake_store(), _scope()
        if operation in ("save", "submit"):
            result = store.save(*scope, action.get("document"), submit=operation == "submit")
            if result.get("ok") and result.get("document"):
                document = result["document"]
                # Drafts are persisted only.  All cleaning, route decisions and
                # research begin after the user explicitly submits the record.
                if operation == "submit":
                    result["analysis"] = run_intake_pipeline(
                        document,
                        str(document.get("id") or ""),
                        document.get("revision") or 1,
                        document.get("task_id") or None,
                    )
                    result["analysis"]["report_enrichment"] = _enrich_report(document)
                result["taskContext"] = (
                    (result.get("analysis") or {}).get("task_context")
                    or _document_task_context(document)
                )
                st.session_state.industry_active_record_id = str(document.get("id") or "")
                st.query_params["record_id"] = st.session_state.industry_active_record_id
        elif operation in ("load", "link"):
            document = store.load(*scope, action.get("id"))
            if operation == "link" and document["side"] != "supplier":
                raise ValueError("请选择供应端采集记录。")
            result = dict(ok=True, document=document, message="已带入原料来源，请补齐到货验收信息。") if operation == "link" else dict(ok=True, document=document, message="已打开保存的采集记录。")
            if operation == "load":
                if document.get("status") == "submitted":
                    result["analysis"] = run_intake_pipeline(
                        document,
                        str(document.get("id") or ""),
                        document.get("revision") or 1,
                        document.get("task_id") or None,
                    )
                    result["analysis"]["report_enrichment"] = _enrich_report(document)
                result["taskContext"] = (
                    (result.get("analysis") or {}).get("task_context")
                    or _document_task_context(document)
                )
                st.session_state.industry_active_record_id = str(document.get("id") or "")
                st.query_params["record_id"] = st.session_state.industry_active_record_id
        else:
            raise ValueError("不支持此采集操作。")
    except (ValueError, TypeError, KeyError, sqlite3.Error, OSError) as error:
        # Keep validation feedback useful but never disclose database paths.
        result = dict(ok=False, message=str(error) if isinstance(error, ValueError) else "采集记录暂未保存成功，请导出备份并稍后重试。")
    st.session_state.intake_result = dict(result, requestId=action["requestId"], operation=operation)
    # Persist acknowledged state too: a component remount must not replay an old
    # save response over subsequent unsaved field edits.
    model = deepcopy(st.session_state.get("industry_ui_model", {}))
    collection = model.get("collection")
    if isinstance(collection, dict):
        collection.update(handledRequestId=action["requestId"], pending=False,
                          message=result["message"], errors=result.get("audit", {}).get("errors", []))
        if result.get("ok") and result.get("document") and operation != "link":
            document = result["document"]
            collection.setdefault("documents", {})[document["side"]] = document
            collection.setdefault("dirty", {})[document["side"]] = False
            collection["side"] = document["side"]
            model["activeIntakeReport"] = document
            if result.get("analysis"):
                analysis = result["analysis"]
                model["analysis"] = analysis
            else:
                model.pop("analysis", None)
            context = result.get("taskContext") or {}
            if context:
                model["taskContext"] = context
            else:
                model.pop("taskContext", None)
            st.session_state.industry_task_context = dict(context)
            collection.pop("undo", None)
            if operation == "load":
                collection["panel"] = "form"
                collection.setdefault("steps", {})[document["side"]] = 0
        if not result.get("ok") and collection["errors"]:
            collection["panel"] = "check"
        # Linking is applied by the browser; do not mark it handled prematurely.
        if operation == "link":
            collection.pop("handledRequestId", None)
    st.session_state.industry_ui_model = model


def _report_action():
    action = st.session_state.get("industry_workspace_canvas", {}).get("report_action")
    if not isinstance(action, dict) or not isinstance(action.get("requestId"), str):
        return
    if action["requestId"] == st.session_state.get("report_last_request"):
        return
    st.session_state.report_last_request = action["requestId"]
    result: dict = {"ok": False, "requestId": action["requestId"]}
    template_path = None
    try:
        snapshot = action.get("snapshot") or {}
        context = action.get("taskContext") or snapshot.get("taskContext") or {}
        record_id = str(
            action.get("recordId")
            or context.get("record_id")
            or (snapshot.get("activeIntakeReport") or {}).get("id")
            or ""
        )
        if not record_id:
            raise ValueError("请先正式提交采集记录，系统才会开始分析并生成项目报告。")
        document = _intake_store().load(*_scope(), record_id)
        if document.get("status") != "submitted":
            raise ValueError("当前记录仍是草稿。请先正式提交，再生成项目报告。")
        analysis = run_intake_pipeline(
            document,
            record_id,
            document.get("revision") or 1,
            document.get("task_id") or None,
        )
        analysis["report_enrichment"] = _enrich_report(document)
        server_context = analysis.get("task_context") or {}
        report = action.get("report") or snapshot.get("report") or {}
        template_data = str(report.get("templateData") or "")
        template_name = str(report.get("templateFile") or "")
        if template_data and template_name.lower().endswith(".docx"):
            if len(template_data) > 8 * 1024 * 1024:
                raise ValueError("Word 模板过大，请将文件控制在 6MB 以内。")
            raw_template = base64.b64decode(template_data, validate=True)
            if len(raw_template) > 6 * 1024 * 1024 or not raw_template.startswith(b"PK"):
                raise ValueError("Word 模板无效，或文件超过 6MB。")
            suffix = Path(template_name).suffix or ".docx"
            with tempfile.NamedTemporaryFile(prefix="citrus_template_", suffix=suffix, delete=False) as handle:
                handle.write(raw_template)
                template_path = handle.name
        generated = generate_project_report(
            task_id=str(server_context.get("task_id") or ""),
            record_id=record_id,
            document=document,
            analysis=analysis,
            profile=report,
            template_path=template_path,
            output_dir=agent_workflow.REPORT_DIR,
        )
        result = {"ok": True, "requestId": action["requestId"], **generated}
    except (ValueError, DeepSeekAPIError, binascii.Error) as error:
        result["message"] = str(error)
    except Exception:
        result["message"] = "报告生成暂时失败，请稍后重试。"
    finally:
        if template_path:
            try:
                Path(template_path).unlink(missing_ok=True)
            except OSError:
                pass
    st.session_state.report_result = result
    model = deepcopy(st.session_state.get("industry_ui_model", {}))
    model["reportResult"] = result
    report = model.setdefault("report", {})
    if result.get("ok"):
        report.update(generated=True, generatedAt=result.get("created_at", ""), reportId=result.get("report_id", ""), generationMode=result.get("generation_mode", ""), sources=result.get("sources", []), markdown=result.get("markdown", ""))
    else:
        report["generated"] = False
    model["reportActionHandled"] = action["requestId"]
    st.session_state.industry_ui_model = model


def render_industry_workspace() -> None:
    scope = _scope()
    previous_scope = st.session_state.get("intake_scope")
    if previous_scope is not None and previous_scope != scope:
        for key in (
            "industry_ui_model", "industry_task_context", "industry_active_record_id",
            "intake_result", "intake_last_request", "report_result", "report_last_request",
        ):
            st.session_state.pop(key, None)
    st.session_state.intake_scope = scope
    records, analytics = [], {}
    if all(scope):
        try:
            store = _intake_store()
            records = store.list(*scope)
            analytics = store.analytics(*scope)
        except (ValueError, OSError, sqlite3.Error):
            st.warning("暂时无法读取已保存的采集记录。请稍后重试，当前填写内容仍可导出备份。")
    # Register in the active runtime, including a fresh AppTest or hot reload.
    # Registering an identical definition is idempotent in Streamlit 1.61.
    canvas = st.components.v2.component(
        "citrus_industry_workspace_v3",
        html='<div class="iw" data-industry-canvas="v3"></div>',
        css=(_ASSETS / "workspace.css").read_text(encoding="utf-8"),
        js="\n".join((
            (_ASSETS / "intake.js").read_text(encoding="utf-8"),
            (_ASSETS / "analytics.js").read_text(encoding="utf-8"),
            (_ASSETS / "workspace.js").read_text(encoding="utf-8"),
        )),
        isolate_styles=True,
    )
    canvas(
        key="industry_workspace_canvas",
        data={
            "view": current_industry_view(),
            "model": st.session_state.get("industry_ui_model", {}),
            "photo": "app/static/industry/supply-reference.png",
            "intakeSchema": intake_schema(),
            "intakeScope": hashlib.sha256(repr(scope).encode()).hexdigest()[:20],
            "intakeRecords": records,
            "intakeAnalytics": analytics,
            "intakeResult": st.session_state.get("intake_result"),
            "reportResult": st.session_state.get("report_result"),
        },
        on_snapshot_change=_save_snapshot,
        on_intake_action_change=_intake_action,
        on_report_action_change=_report_action,
        height="content",
        width="stretch",
    )


__all__ = ["current_industry_view", "render_industry_workspace", "restore_active_context"]
