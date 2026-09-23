"""Server-authorized enterprise administration, review and export."""
from __future__ import annotations

import base64
import json
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError
from app.auth import can_access_admin, current_principal, is_platform_admin, store
from app.intake_schema import intake_schema
from app.platform_store import Actor
from app.pilot_intake import PilotIntakeStore

ROLES = {"member": "填报成员", "reviewer": "资料审核员", "admin": "企业管理员", "owner": "企业负责人"}
STATUSES = {"draft": "草稿", "submitted": "待审核", "needs_changes": "退回补充", "approved": "审核通过",
            "rejected": "审核不通过", "archived": "已归档"}


def _record_details(intake, actor, records):
    if not records:
        st.info("当前企业还没有可查看的资料。成员的未提交草稿仅本人可见。")
        return
    st.dataframe([{"主体 / 批次": row["title"], "状态": STATUSES.get(row["status"], row["status"]),
                   "版本": row["revision"], "更新时间": row["updated_at"], "审核意见": row["review_note"]}
                  for row in records], hide_index=True, width="stretch")
    by_id = {row["id"]: row for row in records}
    rid = st.selectbox("查看资料", list(by_id), format_func=lambda key: f"{by_id[key]['title']} · {key[-8:]}",
                       key=f"admin_record_{actor.organization_id}")
    row = by_id[rid]
    document = intake.load(actor.user_id, actor.organization_id, rid)
    st.caption(f"记录编号：{rid} · 版本 {row['revision']} · {STATUSES[row['status']]}")
    if document.get("review_note"):
        st.info("审核意见：" + document["review_note"])
    fields = document.get("fields") or {}
    for step in intake_schema()["sides"][document["side"]]["steps"]:
        with st.expander(step["title"]):
            for group in step["groups"]:
                st.write(group["title"])
                if group.get("repeat"):
                    declaration = document.get("declarations", {}).get(group["key"])
                    if declaration:
                        st.caption(declaration)
                    rows = document.get("rows", {}).get(group["key"], [])
                    if rows:
                        st.dataframe([{f["label"]: r.get(f["key"], "") for f in group["fields"]} for r in rows], hide_index=True)
                    else:
                        st.caption("未登记明细")
                else:
                    st.dataframe([{"项目": f["label"], "填报内容": str(fields.get(group["key"] + "." + f["key"], ""))}
                                  for f in group["fields"]], hide_index=True)
    for index, attachment in enumerate(document.get("attachments", [])):
        st.download_button("下载附件：" + attachment["name"], base64.b64decode(attachment["content"]),
                           file_name=attachment["name"], key=f"admin_attachment_{rid}_{index}")
    if st.button("生成资料导出文件", key=f"admin_prepare_export_{rid}"):
        st.session_state.admin_export = {"scope": (actor.user_id, actor.organization_id, rid, row["revision"], row["status"]),
                                         "data": intake.export(rid)}
    export = st.session_state.get("admin_export", {})
    if export.get("scope") == (actor.user_id, actor.organization_id, rid, row["revision"], row["status"]):
        st.download_button("下载完整资料（含附件）", data=export["data"], file_name=f"{rid}.json",
                           mime="application/json", key=f"admin_export_{rid}")
    if st.checkbox("查看历史版本", key=f"admin_history_{rid}"):
        for version in intake.history(rid):
            with st.expander(f"版本 {version['revision']} · {version['created_at']}"):
                st.json(json.loads(version["payload"]))
    if row["status"] == "submitted":
        with st.form(f"admin_review_{rid}"):
            decision = st.selectbox("审核决定", ["approved", "needs_changes", "rejected"], format_func=STATUSES.get)
            note = st.text_area("审核意见", placeholder="请说明通过条件或需要补充的内容。")
            if st.form_submit_button("保存审核决定"):
                intake.review(rid, row["revision"], decision, note)
                st.rerun()
    elif row["status"] in {"approved", "rejected"}:
        if st.button("归档这份资料", key=f"admin_archive_{rid}"):
            intake.archive(rid, row["revision"])
            st.rerun()


def _render():
    principal = current_principal() or {}
    if not can_access_admin(principal):
        return
    platform = store()
    uid = principal["user"]["id"]
    st.subheader("平台管理后台")
    if is_platform_admin(principal):
        with st.expander("新建企业"):
            with st.form("admin_organization_form"):
                name = st.text_input("企业名称")
                if st.form_submit_button("创建企业"):
                    platform.create_organization(Actor(uid), name)
                    st.session_state.platform_principal = platform.principal(uid)
                    st.rerun()
    orgs = principal.get("organizations") or []
    selected = next((row for row in orgs if row["id"] == st.session_state.get("active_organization_id")), None)
    if not selected:
        st.info("请在侧栏选择要管理的企业。")
        return
    if selected["role"] not in {"platform_admin", "owner", "admin", "reviewer"}:
        st.info("当前企业没有管理权限，请在侧栏切换到你有权管理的企业。")
        return
    st.caption("当前管理企业：" + selected["name"])
    actor = Actor(uid, selected["id"])
    intake = PilotIntakeStore(platform, actor)
    can_manage = selected["role"] in {"platform_admin", "owner", "admin"}
    allowed_roles = ["member", "reviewer"]
    if selected["role"] in {"platform_admin", "owner"}:
        allowed_roles += ["admin"]
    if is_platform_admin(principal):
        allowed_roles += ["owner"]
    tabs = st.tabs(["成员管理", "企业邀请", "资料审核与导出", "操作记录"])
    with tabs[0]:
        members = platform.members(actor)
        st.metric("企业成员", len(members))
        st.dataframe([{"邮箱": r["email"], "角色": ROLES[r["role"]], "启用": r["active"]} for r in members], hide_index=True)
        editable = [r for r in members if r["id"] != uid and r["role"] in allowed_roles]
        if can_manage and editable:
            lookup = {r["id"]: r for r in editable}
            with st.form("admin_member_form"):
                member_uid = st.selectbox("要调整的成员", list(lookup), format_func=lambda key: lookup[key]["email"])
                role = st.selectbox("调整后的角色", allowed_roles, format_func=ROLES.get)
                active = st.checkbox("保持成员启用", value=True)
                if st.form_submit_button("更新成员权限"):
                    platform.set_membership(actor, member_uid, role, active)
                    st.rerun()
    with tabs[1]:
        if can_manage:
            st.write("邀请代码仅生成时可复制，请通过企业认可的渠道发送给对应邮箱。")
            with st.form("admin_invite_form"):
                email = st.text_input("受邀邮箱")
                role = st.selectbox("企业角色", allowed_roles, format_func=ROLES.get)
                if st.form_submit_button("生成邀请代码"):
                    token = platform.invite(actor, email, role=role)
                    st.session_state.admin_latest_invite = {"email": email, "token": token, "org": actor.organization_id}
            latest = st.session_state.get("admin_latest_invite", {})
            if latest.get("org") == actor.organization_id:
                st.code(latest["token"], language="text")
                st.caption(f"仅允许邮箱 {latest['email']} 接受；7 天内有效，使用一次后失效。")
        else:
            st.info("审核员可以查看邀请记录；邀请与成员权限由管理员管理。")
        invitations = platform.invitations(actor)
        st.dataframe(invitations, hide_index=True, width="stretch")
        pending = {r["id"]: r for r in invitations if not r["accepted_at"] and not r["revoked"]}
        if can_manage and pending:
            iid = st.selectbox("撤回未使用的邀请", list(pending), format_func=lambda key: pending[key]["email"] + " · " + key[-6:])
            if st.button("撤回所选邀请"):
                platform.revoke_invitation(actor, iid)
                st.session_state.pop("admin_latest_invite", None)
                st.rerun()
    with tabs[2]:
        records = intake.list(uid, actor.organization_id)
        st.metric("待审核资料", sum(r["status"] == "submitted" for r in records))
        if st.button("准备导出当前企业全部资料", key=f"admin_prepare_export_all_{actor.organization_id}"):
            try:
                st.session_state.admin_org_export = {
                    "organization": actor.organization_id, "data": intake.export_all(),
                }
            except (ValueError, OSError):
                st.warning("当前企业资料暂时无法导出，请稍后重试。")
        org_export = st.session_state.get("admin_org_export", {})
        if org_export.get("organization") == actor.organization_id:
            st.download_button("下载当前企业全部资料", data=org_export["data"],
                               file_name=f"{actor.organization_id}-records.json", mime="application/json",
                               key=f"admin_export_all_{actor.organization_id}")
        _record_details(intake, actor, records)
    with tabs[3]:
        st.caption("平台管理员还可查看登录事件；操作记录最多显示最近 100 条。")
        st.dataframe(platform.audit_log(actor), hide_index=True, width="stretch")


def render_platform_admin() -> None:
    try:
        _render()
    except (ValueError, OSError) as error:
        st.error(str(error))
    except SQLAlchemyError:
        st.error("暂时无法访问企业资料，请稍后重试或联系管理员。")


__all__ = ["render_platform_admin"]
