"""OIDC authentication and explicitly local development access for the pilot."""
from __future__ import annotations

import os
from typing import Any
import streamlit as st
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from app.platform_store import PlatformStore, normalize_email


def _truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"} if value else default


def production() -> bool:
    return os.getenv("CITRUS_ENV", "development").strip().lower() == "production"


def auth_required() -> bool:
    return production() or _truthy("CITRUS_AUTH_REQUIRED", False)


def dev_auth_enabled() -> bool:
    return os.getenv("CITRUS_ENV", "development").strip().lower() == "development" and _truthy("CITRUS_DEV_AUTH_ENABLED")


def auth_provider() -> str | None:
    # None selects the default [auth] provider in secrets.toml.
    return os.getenv("CITRUS_AUTH_PROVIDER", "").strip() or None


def production_configuration_errors() -> list[str]:
    if not production():
        return []
    errors = []
    if _truthy("CITRUS_DEV_AUTH_ENABLED"):
        errors.append("生产环境必须关闭本地试点登录。")
    try:
        postgres = make_url(os.getenv("CITRUS_DATABASE_URL", "")).get_backend_name() == "postgresql"
    except Exception:
        postgres = False
    if not postgres:
        errors.append("生产环境需要配置 PostgreSQL 数据库。")
    if os.getenv("CITRUS_BLOB_BACKEND", "local") != "s3" or not os.getenv("CITRUS_S3_BUCKET"):
        errors.append("生产环境需要配置私有对象存储。")
    if not os.getenv("CITRUS_CLAMAV_HOST"):
        errors.append("生产环境需要配置文件扫描服务。")
    return errors


def store() -> PlatformStore:
    # Provisioning belongs to scripts/init_platform.py, never a web request.
    return PlatformStore()


def current_principal() -> dict[str, Any] | None:
    value = st.session_state.get("platform_principal")
    return value if isinstance(value, dict) else None


def current_email() -> str:
    return str(((current_principal() or {}).get("user") or {}).get("email") or "")


def is_platform_admin(principal: dict[str, Any] | None = None) -> bool:
    return bool(((principal or current_principal() or {}).get("user") or {}).get("platform_admin"))


def can_access_admin(principal: dict[str, Any] | None = None) -> bool:
    principal = principal or current_principal() or {}
    return is_platform_admin(principal) or any(
        row.get("role") in {"owner", "admin", "reviewer"} for row in principal.get("organizations", [])
    )


def _clear_business_state() -> None:
    keep = {"platform_principal", "platform_email", "platform_auth_mode", "platform_login_marker",
            "active_organization_id", "account_organization_selector", "platform_active_scope"}
    for key in list(st.session_state):
        if key not in keep:
            del st.session_state[key]
    for key in ("ctx", "record_id", "uid", "sid"):
        st.query_params.pop(key, None)


def _logout() -> None:
    oidc = st.session_state.get("platform_auth_mode") == "oidc"
    for key in list(st.session_state):
        del st.session_state[key]
    st.query_params.clear()
    if oidc:
        st.logout()
    st.rerun()


def _invite_form(email: str) -> None:
    with st.form("platform_invitation_form"):
        st.caption(f"仅接受发送给 {email} 的企业邀请。")
        token = st.text_input("邀请代码", type="password", key="platform_invite_token")
        submitted = st.form_submit_button("接受企业邀请")
    if submitted:
        try:
            platform = store()
            uid = (current_principal() or {}).get("user", {}).get("id", "")
            org = platform.accept_invitation(uid, token)
            st.session_state.platform_principal = platform.principal(uid)
            st.session_state.active_organization_id = org
            # On the next rerun select the newly joined enterprise.
            st.session_state.pop("account_organization_selector", None)
            st.query_params.pop("invite", None)
            st.rerun()
        except ValueError as error:
            st.error(str(error))
        except SQLAlchemyError:
            st.error("暂时无法接受邀请，请稍后重试。")


def local_login(email: str, token: str = "") -> dict:
    """A repeat login never requires redeeming an already-used invitation."""
    if not dev_auth_enabled():
        raise ValueError("本地试点登录未启用。")
    platform = store()
    uid = platform.dev_authenticate(normalize_email(email))
    if token.strip():
        platform.accept_invitation(uid, token)
    return platform.principal(uid)


def _gate() -> bool:
    if production_configuration_errors():
        st.error("试点服务配置尚未完成，请联系管理员。")
        return False
    try:
        user = st.user
        claims = dict(user) if bool(getattr(user, "is_logged_in", False)) else None
    except Exception:
        claims = None
    principal = None
    if claims:
        marker = tuple(str(claims.get(k) or "") for k in ("iss", "sub", "iat", "exp"))
        platform = store()
        uid = platform.authenticate(claims, record_login=st.session_state.get("platform_login_marker") != marker)
        principal = platform.principal(uid)
        st.session_state.platform_login_marker = marker
        st.session_state.platform_auth_mode = "oidc"
    elif dev_auth_enabled() and st.session_state.get("platform_auth_mode") == "development" and current_principal():
        principal = store().principal(current_principal()["user"]["id"])
    else:
        st.session_state.pop("platform_principal", None)
    if principal:
        st.session_state.platform_principal = principal
        st.session_state.platform_email = principal["user"]["email"]
        if principal.get("organizations") or is_platform_admin(principal):
            return True
        st.title("加入柑橘产业链试点")
        _invite_form(principal["user"]["email"])
        if st.button("退出账号", key="platform_gate_logout"):
            _logout()
        return False
    if not auth_required():
        return True
    st.title("柑橘产业链 Agent")
    st.write("这是邀请制试点，请使用受邀邮箱登录。")
    if st.button("使用邮箱登录", type="primary", key="platform_oidc_login"):
        try:
            st.login(auth_provider())
        except Exception:
            st.error("登录服务暂不可用，请联系管理员检查登录配置。")
    if dev_auth_enabled():
        with st.expander("本地试点登录", expanded=True):
            st.caption("仅用于本机验收，不会发送验证邮件。")
            email = st.text_input("试点邮箱", key="platform_dev_email")
            token = st.text_input("首次加入时填写邀请代码", type="password", key="platform_dev_token")
            if st.button("进入本地试点", key="platform_dev_login"):
                principal = local_login(email, token)
                st.session_state.platform_principal = principal
                st.session_state.platform_email = principal["user"]["email"]
                st.session_state.platform_auth_mode = "development"
                st.rerun()
    return False


def render_auth_gate() -> bool:
    try:
        return _gate()
    except ValueError as error:
        st.error(str(error))
    except SQLAlchemyError:
        st.error("账户服务暂不可用，请联系管理员检查初始化和数据库连接。")
    if st.button("返回登录", key="platform_retry_login"):
        _logout()
    return False


def render_account_controls() -> None:
    principal = current_principal()
    if not principal:
        return
    user = principal["user"]
    organizations = principal.get("organizations") or []
    with st.sidebar:
        st.caption(f"当前账号：{user['email']}")
        if organizations:
            ids = [row["id"] for row in organizations]
            labels = {row["id"]: row["name"] + " · " + row["id"][-6:] for row in organizations}
            current = st.session_state.get("active_organization_id")
            index = ids.index(current) if current in ids else 0
            chosen = st.selectbox("当前企业", ids, index=index, format_func=labels.get, key="account_organization_selector")
            st.session_state.active_organization_id = chosen
            scope = (user["id"], chosen)
            if st.session_state.get("platform_active_scope") != scope:
                _clear_business_state()
                st.session_state.platform_active_scope = scope
        with st.expander("加入另一家企业"):
            _invite_form(user["email"])
        if st.button("退出账号", key="platform_logout"):
            _logout()


__all__ = ["auth_required", "can_access_admin", "current_email", "current_principal",
           "dev_auth_enabled", "is_platform_admin", "render_account_controls", "render_auth_gate", "store"]
