"""Industry workspace surfaces for the Citrus AI demo.

The industry layer lives inside the original Workspace page.  It intentionally
keeps the product rail owned by ``components.py`` and only adds the four
business views in the page canvas: production records, supply, demand and
matching.  The values are synthetic demo data until a real business source is
connected.
"""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from app.ui import components as ui_components


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _init_state() -> None:
    st.session_state.setdefault(
        "industry_batch",
        {
            "batch_id": "GX-WG-20260903-01",
            "origin": "广西桂林",
            "variety": "沃柑",
            "weight": "20",
            "brix": "12.8",
            "supplier": "桂林示例果园",
            "fertilizer": "中农绿能",
            "process_note": "已完成采后分选，检测报告待补",
        },
    )
    st.session_state.setdefault(
        "industry_request",
        {
            "buyer": "示例果汁加工企业",
            "product": "NFC 果汁",
            "quantity": "15",
            "brix_min": "12",
            "delivery": "2026-09-10",
            "notes": "需要可追溯批次与农残报告",
        },
    )
    st.session_state.setdefault("industry_batch_saved", False)
    st.session_state.setdefault("industry_request_saved", False)
    st.session_state.setdefault("industry_connection_requested", False)


def _status(text: str, tone: str = "neutral") -> str:
    return f'<span class="industry-status {html.escape(tone)}">{_esc(text)}</span>'


def _heading(eyebrow: str, title: str, description: str = "") -> None:
    description_html = (
        f'<p class="industry-section-description">{_esc(description)}</p>'
        if description
        else ""
    )
    st.markdown(
        f"""
        <div class="industry-section-heading industry-mock-heading">
            <div class="industry-section-eyebrow">{_esc(eyebrow)}</div>
            <h2>{_esc(title)}</h2>
            {description_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric_cards(items: list[tuple[str, str, str]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, note) in zip(columns, items):
        with column:
            st.markdown(
                f"""
                <div class="industry-mock-metric">
                    <div class="industry-mock-metric-label">{_esc(label)}</div>
                    <div class="industry-mock-metric-value">{_esc(value)}</div>
                    <div class="industry-mock-metric-note">{_esc(note)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _panel(title: str, english: str = "") -> None:
    english_html = f'<small>{_esc(english)}</small>' if english else ""
    st.markdown(
        f'<div class="industry-mock-panel-head"><div><h3>{_esc(title)}</h3>{english_html}</div></div>',
        unsafe_allow_html=True,
    )
def current_industry_view() -> str:
    """Return the industry page selected from the original left sidebar."""
    allowed = {"production", "supply", "demand", "match"}
    try:
        query_value = st.query_params.get("industry", "")
    except Exception:
        query_value = ""
    if isinstance(query_value, list):
        query_value = query_value[0] if query_value else ""
    query_view = str(query_value or "").strip().lower()
    state_view = str(st.session_state.get("industry_workspace_view") or "").strip().lower()
    selected = query_view if query_view in allowed else state_view if state_view in allowed else "production"
    st.session_state.industry_workspace_view = selected
    return selected


def _render_production() -> None:
    _heading(
        "05 · PROCESSING CAPABILITY",
        "加工能力与生产记录",
        "把加工参数、设备档期和历史批次放在同一张生产工作面上，方便供应端快速判断是否能接单。",
    )
    _metric_cards(
        [
            ("当前产线", "鲜果分选线 A", "运行中 · 85% 负荷"),
            ("可排产时间", "09-12 08:00", "最近可用档期"),
            ("近 30 天批次", "24 批", "完成 21 批"),
            ("平均良率", "92.6%", "较上月 +3.4%"),
        ]
    )

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown(
            """
            <section class="industry-mock-panel industry-production-records">
            <div class="industry-mock-panel-head"><div><h3>生产记录</h3><small>Production records</small></div></div>
            <div class="industry-record-table">
                <div class="industry-record-row industry-record-header"><span>批次</span><span>产品路线</span><span>入线时间</span><span>状态</span></div>
                <div class="industry-record-row"><strong>GX-WG-20260903-01</strong><span>鲜果分选</span><span>09-03 08:20</span><span>已完成</span></div>
                <div class="industry-record-row"><strong>JX-NC-20260902-04</strong><span>NFC 果汁</span><span>09-02 13:10</span><span>已完成</span></div>
                <div class="industry-record-row"><strong>GD-CZ-20260901-02</strong><span>果皮精油</span><span>09-01 09:40</span><span>待复核</span></div>
                <div class="industry-record-row"><strong>GX-OR-20260831-07</strong><span>鲜果分选</span><span>08-31 10:05</span><span>已完成</span></div>
            </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

    with right:
        st.markdown(
            """
            <section class="industry-mock-panel industry-schedule-panel">
            <div class="industry-mock-panel-head"><div><h3>设备档期</h3><small>Equipment schedule</small></div></div>
            <div class="industry-schedule-date"><span>09 月 08 日 · 周二</span><b>已排 72%</b></div>
            <div class="industry-timeline">
                <div class="industry-timeline-item is-done"><span class="industry-time">08:00</span><div><strong>鲜果分选线 A</strong><small>沃柑 · GX-WG-01</small></div></div>
                <div class="industry-timeline-item is-current"><span class="industry-time">13:30</span><div><strong>榨汁线 B</strong><small>预留 15 吨 · NFC 果汁</small></div></div>
                <div class="industry-timeline-item"><span class="industry-time">17:00</span><div><strong>清洗包装线 C</strong><small>可预约 · 余量 4 小时</small></div></div>
            </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <section class="industry-mock-panel industry-parameter-panel">
        <div class="industry-mock-panel-head"><div><h3>生产参数审核</h3><small>Parameter review</small></div></div>
        <div class="industry-parameter-grid">
            <div><span>清洗水温</span><strong>18–22 ℃</strong><em>已记录</em></div>
            <div><span>分选规格</span><strong>果径 60–75 mm</strong><em>已记录</em></div>
            <div><span>榨汁温度</span><strong>≤ 8 ℃</strong><em class="is-pending">待确认</em></div>
            <div><span>冷库湿度</span><strong>85–90% RH</strong><em>已记录</em></div>
        </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("补充本批次加工信息", expanded=False):
        batch = st.session_state.industry_batch
        with st.form("industry_production_form", clear_on_submit=False):
            cols = st.columns(3)
            with cols[0]:
                batch_id = st.text_input("批次编号", value=batch["batch_id"], key="production_batch_id")
            with cols[1]:
                process_line = st.selectbox("加工路线", ["鲜果分选", "NFC 果汁", "果皮精油", "陈皮原料"], key="production_line")
            with cols[2]:
                process_status = st.selectbox("记录状态", ["已完成", "进行中", "待复核"], key="production_status")
            note = st.text_area("加工备注", value=batch["process_note"], key="production_note", height=76)
            submitted = st.form_submit_button("保存生产记录", width="stretch")
        if submitted:
            st.session_state.industry_batch["batch_id"] = batch_id.strip() or batch["batch_id"]
            st.session_state.industry_batch["process_note"] = note.strip()
            st.session_state.industry_batch_saved = True
            st.success(f"生产记录已保存：{process_line} · {process_status}。")


def _supply_card(batch_id: str, title: str, quantity: str, brix: str, status: str, tone: str, image_tone: str) -> None:
    st.markdown(
        f"""
        <article class="industry-supply-mock-card">
            <div class="industry-supply-image {image_tone}"><span>{ui_components.icon_svg('citrus', 30)}</span><small>批次图片</small></div>
            <div class="industry-supply-card-body">
                <div class="industry-supply-card-head"><span class="industry-card-id">{_esc(batch_id)}</span>{_status(status, tone)}</div>
                <h3>{_esc(title)}</h3>
                <div class="industry-supply-facts"><span><small>可供量</small><b>{_esc(quantity)}</b></span><span><small>糖度</small><b>{_esc(brix)}</b></span></div>
                <div class="industry-supply-card-foot"><span>产地与投入品可见</span><span>查看详情&nbsp; →</span></div>
            </div>
        </article>
        """,
        unsafe_allow_html=True,
    )


def _render_supply() -> None:
    _heading(
        "06 · SUPPLY CENTER",
        "供应中心",
        "供应端按统一字段发布可供批次；图片、产地、基础指标与投入品信息均可设置授权范围。",
    )
    filter_cols = st.columns([1, 1, 1.6])
    with filter_cols[0]:
        selected_variety = st.selectbox("品种", ["全部品种", "沃柑", "脐橙", "茶枝柑"], key="supply_variety")
    with filter_cols[1]:
        selected_status = st.selectbox("供应状态", ["全部状态", "已核验", "已上传", "待补检测"], key="supply_status")
    with filter_cols[2]:
        st.markdown('<div class="industry-filter-hint">共 12 个公开批次 · 更新时间 09-03 14:20</div>', unsafe_allow_html=True)

    supplies = [
        ("GX-WG-20260903-01", "广西桂林 · 沃柑", "沃柑", "20 吨", "12.8 °Brix", "已上传", "pending", "is-green"),
        ("JX-NC-20260902-04", "江西赣南 · 脐橙", "脐橙", "12 吨", "12.2 °Brix", "已核验", "ready", "is-orange"),
        ("GD-CZ-20260901-02", "广东新会 · 茶枝柑", "茶枝柑", "8 吨", "10.5 °Brix", "待补检测", "pending", "is-brown"),
    ]
    visible_supplies = [
        item for item in supplies
        if (selected_variety == "全部品种" or item[2] == selected_variety)
        and (selected_status == "全部状态" or item[5] == selected_status)
    ]
    if visible_supplies:
        row = st.columns(3)
        for column, item in zip(row, visible_supplies):
            batch_id, title, _variety, quantity, brix, status, tone, image_tone = item
            with column:
                _supply_card(batch_id, title, quantity, brix, status, tone, image_tone)
    else:
        st.info("当前筛选条件下暂无公开供应批次。")

    _metric_cards(
        [
            ("公开批次", "12", "近 7 天 +4"),
            ("可供原料", "42 吨", "沃柑占 48%"),
            ("已核验", "08 批", "基础资料完整"),
        ]
    )
    st.markdown(
        '<div class="industry-privacy-note"><span class="industry-privacy-icon">' + ui_components.icon_svg("shield", 18) + '</span><div><strong>信息授权提示</strong><p>联系方式、报价与合同信息默认隐藏；只有在双方发起对接并完成授权后才会开放。</p></div></div>',
        unsafe_allow_html=True,
    )


def _render_demand() -> None:
    request = st.session_state.industry_request
    _heading(
        "07 · DEMAND CENTER",
        "需求中心",
        "采购方填写生产原料、品质和交付条件，Agent 会把必须条件与偏好条件分开呈现。",
    )
    left, right = st.columns([1.05, 0.95])
    with left:
        with st.container(key="industry_demand_form_panel"):
            _panel("发布采购需求", "Create a demand")
            with st.form("industry_demand_form", clear_on_submit=False):
                buyer = st.text_input("采购企业", value=request["buyer"], key="demand_buyer")
                product = st.selectbox("生产原料 / 目标产品", ["NFC 果汁", "果皮精油", "陈皮原料", "果胶中间体"], index=0, key="demand_product")
                cols = st.columns(2)
                with cols[0]:
                    quantity = st.text_input("需求量（吨）", value=request["quantity"], key="demand_quantity")
                with cols[1]:
                    brix_min = st.text_input("糖度下限（°Brix）", value=request["brix_min"], key="demand_brix")
                cols = st.columns(2)
                with cols[0]:
                    delivery = st.text_input("期望到货日", value=request["delivery"], key="demand_delivery")
                with cols[1]:
                    st.checkbox("必须提供检测报告", value=True, key="demand_report")
                notes = st.text_area("补充说明", value=request["notes"], key="demand_notes", height=86)
                submitted = st.form_submit_button("保存需求草稿", width="stretch")
        if submitted:
            if not buyer.strip() or not quantity.strip():
                st.warning("采购企业和需求量是必填项。")
            else:
                st.session_state.industry_request = {
                    "buyer": buyer.strip(), "product": product, "quantity": quantity.strip(),
                    "brix_min": brix_min.strip(), "delivery": delivery.strip(), "notes": notes.strip(),
                }
                request.update(st.session_state.industry_request)
                st.session_state.industry_request_saved = True
                st.success("需求草稿已保存，可进入匹配结果查看候选批次。")
    with right:
        st.markdown(
            f"""
            <section class="industry-mock-panel industry-demand-preview">
            <div class="industry-mock-panel-head"><div><h3>需求预览</h3><small>Demand preview</small></div></div>
            <div class="industry-demand-preview-block"><span>采购方</span><strong>{_esc(request['buyer'])}</strong></div>
            <div class="industry-demand-preview-block"><span>目标路线</span><strong>{_esc(request['product'])}</strong></div>
            <div class="industry-demand-group"><div class="industry-demand-group-title">必须条件 · Must have</div><div class="industry-chip-row"><span>{_esc(request['quantity'])} 吨</span><span>糖度 ≥ {_esc(request['brix_min'])} °Brix</span><span>{_esc(request['delivery'])} 前到货</span><span>可追溯批次</span></div></div>
            <div class="industry-demand-group"><div class="industry-demand-group-title">偏好条件 · Nice to have</div><div class="industry-chip-row is-soft"><span>先样品后报价</span><span>可持续供货</span><span>投入品信息完整</span></div></div>
            <div class="industry-demand-note">Agent 将按必须条件筛选，再解释每一个候选的满足项和待补项。</div>
            </section>
            """,
            unsafe_allow_html=True,
        )


def _render_match() -> None:
    request = st.session_state.industry_request
    _heading(
        "08 · MATCH RESULTS",
        "匹配结果",
        "先按硬性条件筛选，再展示证据缺口和推荐理由；匹配结果不替代企业质检和最终验收。",
    )
    st.markdown(
        f"""
        <div class="industry-match-summary"><div><span>当前需求</span><strong>{_esc(request['buyer'])} · {_esc(request['product'])}</strong></div><div><span>需求量</span><strong>{_esc(request['quantity'])} 吨</strong></div><div><span>交付</span><strong>{_esc(request['delivery'])} 前</strong></div><div><span>候选</span><strong>3 个批次</strong></div></div>
        """,
        unsafe_allow_html=True,
    )
    candidates = [
        ("01", "JX-NC-20260902-04", "赣南示例合作社", "96", "推荐对接", "ready", "糖度、数量、交期和基础报告均满足。", ["满足", "满足", "满足", "满足"]),
        ("02", "GX-WG-20260903-01", "桂林示例果园", "78", "待补材料", "pending", "农残报告尚未上传，建议先补齐材料再排产。", ["满足", "满足", "满足", "待补"]),
        ("03", "GD-CZ-20260901-02", "新会示例果园", "54", "不推荐", "blocked", "数量不足且糖度低于当前需求下限。", ["不足", "不符", "满足", "待补"]),
    ]
    for rank, batch_id, supplier, score, state, tone, reason, checks in candidates:
        check_html = "".join(f'<span class="industry-condition {"is-good" if check == "满足" else "is-bad" if check == "不符" else "is-warn"}">{_esc(label)}：{_esc(check)}</span>' for label, check in zip(["数量", "糖度", "交期", "报告"], checks))
        st.markdown(
            f"""
            <article class="industry-match-card"><div class="industry-match-number">{_esc(rank)}</div><div class="industry-match-card-main"><div class="industry-match-card-title"><div><strong>{_esc(batch_id)}</strong><span>{_esc(supplier)}</span></div>{_status(state, tone)}</div><div class="industry-condition-grid">{check_html}</div><p class="industry-match-reason"><b>推荐理由</b>{_esc(reason)}</p></div><div class="industry-match-score"><strong>{_esc(score)}</strong><small>匹配度</small></div></article>
            """,
            unsafe_allow_html=True,
        )

    if st.button("申请对接推荐批次", key="industry_start_connection", width="stretch"):
        st.session_state.industry_connection_requested = True
        st.success("已生成对接申请草稿；双方授权后可继续样品测试与报价沟通。")


def render_industry_workspace() -> None:
    """Render the additive business layer inside the existing Workspace page."""
    _init_state()
    renderer = {
        "production": _render_production,
        "supply": _render_supply,
        "demand": _render_demand,
        "match": _render_match,
    }[current_industry_view()]
    renderer()


__all__ = ["current_industry_view", "render_industry_workspace"]
