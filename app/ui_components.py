from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Iterable


STYLE_FILES = (
    "theme.css",
    "layout.css",
    "sidebar.css",
    "composer.css",
    "cards.css",
    "report.css",
    "responsive.css",
)


def load_style_bundle(style_dir: Path) -> str:
    """Load the ordered style modules used by the Streamlit shell."""
    return "\n\n".join(
        (style_dir / filename).read_text(encoding="utf-8")
        for filename in STYLE_FILES
    )


def _text(value: Any, fallback: str = "") -> str:
    rendered = str(value or "").strip()
    return rendered or fallback


def _escape(value: Any, fallback: str = "") -> str:
    return html.escape(_text(value, fallback))


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def current_task_label(messages: Iterable[dict[str, Any]], limit: int = 24) -> str:
    for message in reversed(list(messages)):
        if message.get("role") != "user":
            continue
        content = _text(message.get("content"))
        if content:
            first_line = re.sub(r"\s+", " ", content).strip()
            return first_line if len(first_line) <= limit else first_line[:limit].rstrip() + "…"
    return "新任务"


def recent_task_labels(
    messages: Iterable[dict[str, Any]],
    *,
    limit: int = 4,
    title_limit: int = 22,
) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for message in reversed(list(messages)):
        if message.get("role") != "user":
            continue
        content = re.sub(r"\s+", " ", _text(message.get("content"))).strip()
        if not content or content in seen:
            continue
        seen.add(content)
        labels.append(content if len(content) <= title_limit else content[:title_limit].rstrip() + "…")
        if len(labels) >= limit:
            break
    return labels


def topbar_html(
    *,
    task_name: str,
    literature_ready: bool,
    text_model_ready: bool,
    vision_model_ready: bool,
) -> str:
    def status(label: str, ready: bool) -> str:
        state = "is-ready" if ready else "is-muted"
        state_text = "已就绪" if ready else "未配置"
        return (
            f'<span class="topbar-status {state}">'
            '<span class="status-dot" aria-hidden="true"></span>'
            f'<span>{html.escape(label)}</span><span class="status-state">{state_text}</span>'
            "</span>"
        )

    return f"""
    <header class="app-topbar" aria-label="应用状态栏">
        <div class="topbar-context">
            <div class="brand-glyph" aria-hidden="true"><span>C</span></div>
            <div class="topbar-copy">
                <div class="topbar-product">Citrus Decision</div>
                <div class="topbar-task">{_escape(task_name, "新任务")}</div>
            </div>
        </div>
        <div class="topbar-statuses">
            {status("文献库", literature_ready)}
            {status("DeepSeek", text_model_ready)}
            {status("视觉模型", vision_model_ready)}
        </div>
    </header>
    """


def sidebar_brand_html() -> str:
    return """
    <div class="sidebar-brand-block">
        <div class="brand-glyph sidebar-brand-glyph" aria-hidden="true"><span>C</span></div>
        <div>
            <div class="sidebar-brand-title">柑橘产业决策</div>
            <div class="sidebar-brand-subtitle">ENTERPRISE AGENT</div>
        </div>
    </div>
    """


def sidebar_navigation_html(
    *,
    recent_tasks: Iterable[str],
    literature_ready: bool,
) -> str:
    recent = list(recent_tasks)
    if recent:
        recent_markup = "".join(
            '<a class="recent-task" href="#conversation-start">'
            '<span class="recent-task-dot" aria-hidden="true"></span>'
            f"<span>{html.escape(label)}</span></a>"
            for label in recent
        )
    else:
        recent_markup = '<div class="sidebar-empty">暂无最近任务</div>'

    literature_state = "已连接" if literature_ready else "未连接"
    resource_state = "is-ready" if literature_ready else "is-muted"
    return f"""
    <nav class="sidebar-navigation" aria-label="工作台导航">
        <section class="sidebar-nav-section">
            <div class="sidebar-nav-heading">工作台</div>
            <a class="sidebar-nav-item is-active" href="#conversation-start">
                <span class="nav-icon" aria-hidden="true">⌁</span><span>批次分析</span>
            </a>
            <a class="sidebar-nav-item" href="#processing-plan">
                <span class="nav-icon" aria-hidden="true">↳</span><span>加工方案</span>
            </a>
            <a class="sidebar-nav-item" href="#risk-evidence">
                <span class="nav-icon" aria-hidden="true">◇</span><span>风险复核</span>
            </a>
            <a class="sidebar-nav-item" href="#recent-tasks">
                <span class="nav-icon" aria-hidden="true">◷</span><span>历史记录</span>
            </a>
        </section>

        <section class="sidebar-nav-section">
            <div class="sidebar-nav-heading">数据资源</div>
            <a class="sidebar-nav-item" href="#evidence-sources">
                <span class="nav-icon" aria-hidden="true">▤</span><span>文献库</span>
                <span class="nav-resource-state {resource_state}">{literature_state}</span>
            </a>
        </section>

        <section class="sidebar-nav-section" id="recent-tasks">
            <div class="sidebar-nav-heading">最近任务</div>
            <div class="recent-task-list">{recent_markup}</div>
        </section>
    </nav>
    """


def sidebar_system_status_html(
    *,
    text_model: str,
    text_model_ready: bool,
    vision_model: str,
    vision_model_ready: bool,
) -> str:
    def row(label: str, model: str, ready: bool) -> str:
        state = "is-ready" if ready else "is-muted"
        state_text = "可用" if ready else "待配置"
        return f"""
        <div class="sidebar-system-row">
            <div>
                <div class="sidebar-system-label">{html.escape(label)}</div>
                <div class="sidebar-system-model" title="{html.escape(model)}">{html.escape(model)}</div>
            </div>
            <span class="sidebar-system-state {state}">{state_text}</span>
        </div>
        """

    return f"""
    <div class="sidebar-system-panel">
        <div class="sidebar-nav-heading">系统状态</div>
        {row("文本模型", text_model, text_model_ready)}
        {row("视觉模型", vision_model, vision_model_ready)}
    </div>
    """


TASK_ICONS = (
    '<path d="M4 12h16M12 4v16"/><circle cx="12" cy="12" r="8"/>',
    '<path d="M5 19V9m7 10V5m7 14v-7"/><path d="M3 19h18"/>',
    '<path d="M5 16c5-1 8-4 11-10 2 5 1 10-4 12-3 1-5 0-7-2Z"/><path d="M5 16c2-2 5-4 9-6"/>',
    '<path d="M12 3 4 7v5c0 5 3 8 8 9 5-1 8-4 8-9V7l-8-4Z"/><path d="m9 12 2 2 4-4"/>',
)


def task_card_html(index: int, *, title: str, description: str) -> str:
    icon = TASK_ICONS[index % len(TASK_ICONS)]
    return f"""
    <div class="task-card-copy">
        <div class="task-card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{icon}</svg>
        </div>
        <div class="task-card-title">{_escape(title)}</div>
        <div class="task-card-description">{_escape(description)}</div>
    </div>
    """


def assistant_identity_html(*, detail: str = "") -> str:
    detail_markup = f'<div class="assistant-detail">{_escape(detail)}</div>' if detail else ""
    return f"""
    <div class="assistant-identity">
        <div class="assistant-mark" aria-hidden="true">C</div>
        <div>
            <div class="assistant-name">柑橘决策助手</div>
            {detail_markup}
        </div>
    </div>
    """


def agent_progress_html(events: Iterable[str], *, mode: str = "analysis") -> str:
    event_list = [_text(event) for event in events if _text(event)]
    if not event_list:
        event_list = ["正在启动任务"]
    rows: list[str] = []
    for index, label in enumerate(event_list):
        is_current = index == len(event_list) - 1
        state = "active" if is_current else "complete"
        icon = "●" if is_current else "✓"
        state_text = "进行中" if is_current else "已完成"
        rows.append(
            f'<div class="progress-step is-{state}">'
            f'<span class="progress-step-icon" aria-hidden="true">{icon}</span>'
            f'<span class="progress-step-label">{html.escape(label)}</span>'
            f'<span class="progress-step-state">{state_text}</span>'
            "</div>"
        )

    title = {
        "analysis": "正在分析该批次",
        "vision": "正在分析上传图片",
        "research": "正在检索与组织回答",
    }.get(mode, "任务正在执行")
    return f"""
    <section class="agent-progress-panel" role="status" aria-live="polite">
        <div class="progress-panel-head">
            <div>
                <div class="progress-panel-title">{title}</div>
                <div class="progress-panel-current">{_escape(event_list[-1])}</div>
            </div>
            <span class="progress-running-badge"><span></span>运行中</span>
        </div>
        <div class="progress-step-list">{''.join(rows)}</div>
        <div class="progress-panel-foot">执行状态会随真实工具步骤更新；运行期间可使用页面右上角停止控件。</div>
    </section>
    """


def decision_summary_html(
    result: dict[str, Any],
    processing_plan: dict[str, Any],
    *,
    anchor_suffix: str = "",
) -> str:
    scores = _list(result.get("scores"))
    top = scores[0] if scores else None
    direction = _escape(_item_value(top, "direction", "暂无推荐结论"))
    match_level = _escape(_item_value(top, "match_level", "待评估"))
    evidence_support = _text(_item_value(top, "evidence_support"))
    confidence = _text(_item_value(top, "data_confidence"))
    reasons = [
        _text(item)
        for item in _list(_item_value(top, "reasons", []))
        if _text(item)
    ][:5]
    missing = [_text(item) for item in _list(processing_plan.get("missing_data")) if _text(item)][:5]
    risks = _list(result.get("quality_risks"))
    next_actions = [
        _text(item)
        for item in _list(result.get("next_actions"))
        if _text(item)
    ][:5]

    metadata = []
    product_form = _text(processing_plan.get("product_form"))
    if product_form:
        metadata.append(
            f'<span><strong>产品形态</strong>{html.escape(product_form)}</span>'
        )
    if evidence_support:
        metadata.append(f'<span><strong>文献支持</strong>{html.escape(evidence_support)}</span>')
    if confidence:
        metadata.append(f'<span><strong>数据置信度</strong>{html.escape(confidence)}</span>')

    def bullets(items: list[str], empty_text: str) -> str:
        if not items:
            return f'<div class="summary-empty">{html.escape(empty_text)}</div>'
        return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"

    risk_items = [
        _text(item)
        for item in _list(_item_value(top, "risk_notes", []))
        if _text(item)
    ]
    for risk in risks[:4]:
        level = _text(_item_value(risk, "level", "提示"))
        name = _text(_item_value(risk, "item", "质控项"))
        suggestion = _text(_item_value(risk, "suggestion"))
        rendered = f"[{level}] {name}"
        if suggestion:
            rendered += f"：{suggestion}"
        if rendered not in risk_items:
            risk_items.append(rendered)

    return f"""
    <section class="decision-summary" id="decision-summary{html.escape(anchor_suffix)}">
        <div class="section-eyebrow">决策摘要</div>
        <div class="decision-summary-head">
            <div>
                <div class="decision-summary-label">推荐加工方向</div>
                <h2>{direction}</h2>
            </div>
            <span class="recommendation-level">推荐度：{match_level}</span>
        </div>
        <div class="decision-metadata">{''.join(metadata)}</div>
        <div class="decision-summary-grid">
            <div class="summary-block">
                <h3>主要依据</h3>
                {bullets(reasons, "现有结果未记录推荐依据。")}
            </div>
            <div class="summary-block">
                <h3>需要进一步确认</h3>
                {bullets(missing, "当前未记录额外待确认项。")}
            </div>
        </div>
        {f'<div class="summary-risk"><h3>风险与边界</h3>{bullets(risk_items, "暂未触发结构化风险项。")}</div>' if risk_items else ''}
        {f'<div class="summary-risk"><h3>后续操作</h3>{bullets(next_actions, "")}</div>' if next_actions else ''}
    </section>
    """


def processing_plan_html(plan: dict[str, Any], *, anchor_suffix: str = "") -> str:
    flow = [_text(item) for item in _list(plan.get("flow")) if _text(item)]
    stages = _list(plan.get("stages"))
    flow_markup = "".join(
        f'<span class="process-flow-step">{html.escape(step)}</span>'
        + ('<span class="process-flow-arrow" aria-hidden="true">→</span>' if index < len(flow) - 1 else "")
        for index, step in enumerate(flow)
    )

    stage_markup: list[str] = []
    for index, stage in enumerate(stages, 1):
        raw_name = _text(_item_value(stage, "name"), f"{index:02d} 加工步骤")
        match = re.match(r"^(\d{1,2})\s*(.*)$", raw_name)
        number = match.group(1).zfill(2) if match else f"{index:02d}"
        name = match.group(2).strip() if match and match.group(2).strip() else raw_name
        steps = " → ".join(_text(item) for item in _list(_item_value(stage, "steps", [])) if _text(item))
        detail_rows = []
        for label, value in (
            ("对应工序", steps),
            ("操作要求", _text(_item_value(stage, "operation"))),
            ("质量控制", _text(_item_value(stage, "control"))),
            ("记录要求", _text(_item_value(stage, "record"))),
        ):
            if value:
                detail_rows.append(
                    f'<div class="process-detail-row"><dt>{label}</dt><dd>{html.escape(value)}</dd></div>'
                )
        open_attr = " open" if index <= 2 else ""
        stage_markup.append(
            f'<details class="process-stage"{open_attr}>'
            '<summary>'
            f'<span class="process-stage-number">{number}</span>'
            f'<span class="process-stage-name">{html.escape(name)}</span>'
            '<span class="process-stage-toggle" aria-hidden="true"></span>'
            "</summary>"
            f'<dl class="process-stage-details">{"".join(detail_rows)}</dl>'
            "</details>"
        )

    status = _text(plan.get("status"))
    product_form = _text(plan.get("product_form"), _text(plan.get("direction"), "加工方案"))
    note_rows: list[str] = []
    for label, raw_value in (
        ("方案依据", plan.get("basis")),
        ("待小试参数", plan.get("pilot_parameters")),
        ("成品放行复核", plan.get("release_checks")),
        ("待确认信息", plan.get("missing_data")),
        ("证据依据", plan.get("evidence_basis")),
        ("风险控制", plan.get("risk_controls")),
    ):
        values = _list(raw_value)
        rendered = "；".join(_text(item) for item in values if _text(item))
        if not rendered:
            rendered = _text(raw_value) if not values else ""
        if rendered:
            note_rows.append(
                f'<div class="process-plan-note"><dt>{label}</dt>'
                f'<dd>{html.escape(rendered)}</dd></div>'
            )
    return f"""
    <section class="processing-plan" id="processing-plan{html.escape(anchor_suffix)}">
        <div class="section-header">
            <div>
                <div class="section-eyebrow">加工流程</div>
                <h2>{html.escape(product_form)}</h2>
            </div>
            {f'<span class="plan-status">{html.escape(status)}</span>' if status else ''}
        </div>
        {f'<div class="process-flow" aria-label="总体加工步骤">{flow_markup}</div>' if flow_markup else ''}
        <div class="process-stage-list">{''.join(stage_markup)}</div>
        {f'<dl class="process-plan-notes">{"".join(note_rows)}</dl>' if note_rows else ''}
    </section>
    """


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    return f"{number:g}"


def evidence_panel_html(
    payload: dict[str, Any],
    *,
    anchor_suffix: str = "",
) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    batch = payload.get("batch") if isinstance(payload.get("batch"), dict) else result.get("batch") or {}
    facts: list[tuple[str, str]] = []
    for key, label, suffix in (
        ("batch_id", "批次", ""),
        ("origin", "产地", ""),
        ("variety", "品种", ""),
        ("weight_kg", "重量", " kg"),
        ("brix", "糖度", " °Brix"),
        ("acidity", "酸度", "%"),
        ("moisture", "水分", "%"),
        ("customer_type", "客户", ""),
    ):
        value = batch.get(key) if isinstance(batch, dict) else None
        if value in (None, ""):
            continue
        rendered = _format_number(value) if isinstance(value, (int, float)) else _text(value)
        facts.append((label, rendered + suffix))

    fact_markup = "".join(
        f'<div class="evidence-fact"><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>'
        for label, value in facts
    )
    if not fact_markup:
        fact_markup = '<div class="panel-empty">暂无结构化批次数据</div>'

    evidence = _list(result.get("evidence"))
    source_keys = {
        _text(
            item.get("document_id")
            or item.get("doi")
            or item.get("source_file")
            or item.get("title")
            or item.get("source")
        )
        for item in evidence
        if isinstance(item, dict)
        and _text(
            item.get("document_id")
            or item.get("doi")
            or item.get("source_file")
            or item.get("title")
            or item.get("source")
        )
    }
    parameter_groups = _list(result.get("parameter_groups"))
    agent_steps = _list(result.get("agent_steps"))
    risks = _list(result.get("quality_risks"))
    conflicts = sum(1 for item in parameter_groups if isinstance(item, dict) and item.get("conflict"))

    resources: list[tuple[str, str]] = []
    if source_keys:
        resources.append(("文献来源", f"{len(source_keys)} 个"))
    elif evidence:
        resources.append(("证据片段", f"{len(evidence)} 条"))
    if parameter_groups:
        resources.append(("参数证据", f"{len(parameter_groups)} 组"))
    if agent_steps:
        resources.append(("工具步骤", f"{len(agent_steps)} 项"))
    resource_anchors = {
        "文献来源": f"#evidence-detail{anchor_suffix}",
        "证据片段": f"#evidence-detail{anchor_suffix}",
        "参数证据": f"#parameter-evidence{anchor_suffix}",
        "工具步骤": f"#task-record{anchor_suffix}",
    }
    resource_markup = "".join(
        f'<a class="evidence-metric" href="{resource_anchors.get(label, f"#decision-summary{anchor_suffix}")}">'
        f"<span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></a>"
        for label, value in resources
    ) or '<div class="panel-empty">暂无证据统计</div>'

    vision_result = payload.get("vision_result") if isinstance(payload.get("vision_result"), dict) else {}
    vision_status = _text(result.get("vision_status"))
    statuses: list[tuple[str, str, str]] = []
    if vision_result or vision_status in {"completed", "success"}:
        statuses.append(("图像识别", "已完成", "success"))
    elif vision_status == "failed":
        statuses.append(("图像识别", "失败", "danger"))
    elif vision_status == "missing_bytes":
        statuses.append(("图像识别", "未执行", "muted"))
    if evidence:
        statuses.append(("文献检索", "已完成", "success"))
    if parameter_groups:
        parameter_state = f"{conflicts} 组待复核" if conflicts else "已形成证据组"
        statuses.append(("参数校验", parameter_state, "warning" if conflicts else "success"))
    if risks:
        statuses.append(("风险复核", f"{len(risks)} 项", "warning"))
    status_markup = "".join(
        f'<div class="analysis-status-row"><span>{html.escape(label)}</span>'
        f'<strong class="is-{state}"><i aria-hidden="true"></i>{html.escape(value)}</strong></div>'
        for label, value, state in statuses
    ) or '<div class="panel-empty">分析状态将在任务完成后显示</div>'

    return f"""
    <aside class="evidence-panel" id="evidence-sources{html.escape(anchor_suffix)}">
        <section>
            <div class="evidence-panel-title">批次信息</div>
            <dl class="evidence-facts">{fact_markup}</dl>
        </section>
        <section>
            <div class="evidence-panel-title">证据来源</div>
            <div class="evidence-metrics">{resource_markup}</div>
        </section>
        <section>
            <div class="evidence-panel-title">分析状态</div>
            <div class="analysis-status-list">{status_markup}</div>
        </section>
    </aside>
    """
