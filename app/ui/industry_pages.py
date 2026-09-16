"""Industry canvas with private intake persistence and session-scoped other tools.

Intake records and attachments use the server-established scope. Marketplace
publication and counterparty contact are not performed by this component.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
from copy import deepcopy

import streamlit as st
from app.intake_schema import intake_schema
from app.intake_store import IntakeStore
from app.intake_pipeline import run_intake_pipeline
from app.report_enrichment import enrich_report_context

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
                result["analysis"] = run_intake_pipeline(document, str(document.get("id") or ""), document.get("revision") or 1)
                result["analysis"]["report_enrichment"] = enrich_report_context(document)
        elif operation in ("load", "link"):
            document = store.load(*scope, action.get("id"))
            if operation == "link" and document["side"] != "supplier":
                raise ValueError("请选择供应端采集记录。")
            result = dict(ok=True, document=document, message="已带入原料来源，请补齐到货验收信息。") if operation == "link" else dict(ok=True, document=document, message="已打开保存的采集记录。", analysis=run_intake_pipeline(document, str(document.get("id") or ""), document.get("revision") or 1))
            if operation == "load":
                result["analysis"]["report_enrichment"] = enrich_report_context(document)
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
            if result.get("analysis"):
                analysis = result["analysis"]
                model["analysis"] = analysis
                model["taskContext"] = analysis.get("task_context", {})
                model["activeIntakeReport"] = document
                st.session_state.industry_task_context = dict(analysis.get("task_context") or {})
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


def render_industry_workspace() -> None:
    scope = _scope()
    previous_scope = st.session_state.get("intake_scope")
    if previous_scope is not None and previous_scope != scope:
        for key in ("industry_ui_model", "intake_result", "intake_last_request"):
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
        },
        on_snapshot_change=_save_snapshot,
        on_intake_action_change=_intake_action,
        height="content",
        width="stretch",
    )


__all__ = ["current_industry_view", "render_industry_workspace"]
