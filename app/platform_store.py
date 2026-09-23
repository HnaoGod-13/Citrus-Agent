"""Server-side account, membership and invitation authorization.

Only verified claims from the configured OIDC provider may call authenticate.
Every business operation rechecks the actor and membership in the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import secrets
from uuid import uuid4

from sqlalchemy import and_, select, update
from app import platform_db as t


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def identifier(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


def normalize_email(value: str) -> str:
    value = str(value or "").strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("请输入有效邮箱地址。")
    return value


def hash_invitation(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Actor:
    user_id: str
    organization_id: str = ""


class PlatformStore:
    def __init__(self, url: str | None = None):
        self.engine = t.engine_for(url or t.database_url())

    def initialize(self):
        t.initialize(self.engine)

    @staticmethod
    def audit(db, actor: Actor, event: str, entity: str = "", **detail):
        db.execute(t.audit_events.insert().values(id=identifier("evt"), actor=actor.user_id,
            organization_id=actor.organization_id, event=event, entity_id=entity,
            detail=json.dumps(detail, ensure_ascii=False), created_at=now()))

    @staticmethod
    def authorize(db, actor: Actor, roles=(), *, platform=False):
        user = db.execute(select(t.users).where(t.users.c.id == actor.user_id)).mappings().first()
        if not user or not user["active"]:
            raise ValueError("账号未登录或已停用。")
        if platform:
            if not user["platform_admin"]:
                raise ValueError("此操作需要平台管理员权限。")
            return {**user, "role": "platform_admin"}
        org = db.execute(select(t.organizations).where(
            t.organizations.c.id == actor.organization_id, t.organizations.c.active.is_(True))).first()
        if not org:
            raise ValueError("企业不存在或已停用。")
        if user["platform_admin"]:
            return {**user, "role": "platform_admin"}
        member = db.execute(select(t.memberships).where(t.memberships.c.user_id == actor.user_id,
            t.memberships.c.organization_id == actor.organization_id,
            t.memberships.c.active.is_(True))).mappings().first()
        if not member or (roles and member["role"] not in roles):
            raise ValueError("当前账号无权执行此操作。")
        return {**user, "role": member["role"]}

    def bootstrap_admin(self, email: str):
        """Offline CLI only. Provision an email; its owner must still authenticate."""
        email = normalize_email(email)
        with self.engine.begin() as db:
            if db.execute(select(t.users.c.id).where(t.users.c.platform_admin.is_(True))).first():
                raise ValueError("已存在平台管理员；初始化不能重复提升权限。")
            existing = db.execute(select(t.users).where(t.users.c.email == email)).mappings().first()
            uid = existing["id"] if existing else identifier("user")
            if existing:
                db.execute(update(t.users).where(t.users.c.id == uid).values(platform_admin=True))
            else:
                db.execute(t.users.insert().values(id=uid, email=email, name="平台管理员",
                    active=True, platform_admin=True, created_at=now()))
            if not db.execute(select(t.organizations.c.id).where(t.organizations.c.active.is_(True))).first():
                oid = identifier("org")
                name = (os.getenv("CITRUS_DEFAULT_ORGANIZATION") or "柑橘产业链试点").strip()[:200]
                db.execute(t.organizations.insert().values(id=oid, name=name or "柑橘产业链试点",
                    active=True, created_at=now()))
            self.audit(db, Actor(uid), "admin_provisioned", uid)
            return uid

    def authenticate(self, claims: dict, *, record_login: bool = True):
        """Resolve a *verified* provider identity, never a user-supplied email."""
        verified = claims.get("email_verified")
        if verified is not True and not (isinstance(verified, str) and verified.strip().lower() == "true"):
            raise ValueError("请先在登录服务中验证邮箱。")
        email = normalize_email(claims.get("email", ""))
        issuer, subject = str(claims.get("iss") or ""), str(claims.get("sub") or "")
        if not issuer or not subject or len(subject) > 512:
            raise ValueError("登录服务没有返回完整身份信息。")
        if claims.get("exp") is not None:
            try:
                valid_expiry = float(claims["exp"]) > datetime.now(timezone.utc).timestamp()
            except (TypeError, ValueError):
                valid_expiry = False
            if not valid_expiry:
                raise ValueError("登录已过期，请退出后重新登录。")
        with self.engine.begin() as db:
            user = db.execute(select(t.users).where(t.users.c.email == email).with_for_update()).mappings().first()
            if user:
                if not user["active"]:
                    raise ValueError("账号已停用，请联系平台管理员。")
                if user["issuer"] and (user["issuer"], user["subject"]) != (issuer, subject):
                    raise ValueError("此邮箱已关联其他身份，请联系平台管理员。")
                if not user["issuer"]:
                    db.execute(update(t.users).where(t.users.c.id == user["id"]).values(issuer=issuer, subject=subject))
                db.execute(update(t.users).where(t.users.c.id == user["id"]).values(name=str(claims.get("name") or user["name"] or "")[:200]))
                if record_login:
                    memberships = db.execute(select(t.memberships.c.organization_id).where(
                        t.memberships.c.user_id == user["id"], t.memberships.c.active.is_(True))).scalars().all()
                    if memberships:
                        for organization_id in memberships:
                            self.audit(db, Actor(user["id"], organization_id), "login_succeeded", user["id"])
                    else:
                        self.audit(db, Actor(user["id"]), "login_succeeded", user["id"])
                return user["id"]
            # Verified but uninvited identities can only see the invitation gate.
            uid = identifier("user")
            db.execute(t.users.insert().values(id=uid, email=email, issuer=issuer, subject=subject,
                name=str(claims.get("name") or "")[:200], active=True, platform_admin=False, created_at=now()))
            self.audit(db, Actor(uid), "identity_verified", uid)
            self.audit(db, Actor(uid), "login_succeeded", uid)
            return uid

    def dev_authenticate(self, email: str, name: str = "本地试点用户"):
        """Create a local-only identity for tests; caller must gate this mode."""
        email = normalize_email(email)
        uid = "dev_" + hashlib.sha256(email.encode()).hexdigest()[:24]
        with self.engine.begin() as db:
            row = db.execute(select(t.users).where(t.users.c.email == email)).mappings().first()
            if row:
                if not row["active"]:
                    raise ValueError("账号已停用。")
                memberships = db.execute(select(t.memberships.c.organization_id).where(
                    t.memberships.c.user_id == row["id"], t.memberships.c.active.is_(True))).scalars().all()
                if memberships:
                    for organization_id in memberships:
                        self.audit(db, Actor(row["id"], organization_id), "dev_login_succeeded", row["id"])
                else:
                    self.audit(db, Actor(row["id"]), "dev_login_succeeded", row["id"])
                return row["id"]
            db.execute(t.users.insert().values(id=uid, email=email, issuer="dev", subject=uid,
                name=str(name or "")[:200], active=True, platform_admin=False, created_at=now()))
            self.audit(db, Actor(uid), "dev_identity_created", uid)
            self.audit(db, Actor(uid), "dev_login_succeeded", uid)
        return uid

    def principal(self, uid: str):
        with self.engine.connect() as db:
            user = db.execute(select(t.users).where(t.users.c.id == uid, t.users.c.active.is_(True))).mappings().first()
            if not user:
                raise ValueError("账号不存在或已停用。")
            query = select(t.organizations.c.id, t.organizations.c.name, t.memberships.c.role).join(
                t.memberships, t.organizations.c.id == t.memberships.c.organization_id).where(
                t.memberships.c.user_id == uid, t.memberships.c.active.is_(True), t.organizations.c.active.is_(True))
            orgs = [dict(row) for row in db.execute(query).mappings()]
            if user["platform_admin"]:
                orgs = [{**row, "role": "platform_admin"} for row in
                    db.execute(select(t.organizations.c.id, t.organizations.c.name).where(
                        t.organizations.c.active.is_(True))).mappings()]
            return {"user": dict(user), "organizations": orgs}

    def create_organization(self, actor: Actor, name: str):
        name = str(name).strip()
        if not name or len(name) > 200:
            raise ValueError("请填写200字以内的企业名称。")
        oid = identifier("org")
        with self.engine.begin() as db:
            self.authorize(db, actor, platform=True)
            # Names are display labels, never a basis for joining another enterprise.
            db.execute(t.organizations.insert().values(id=oid, name=name, active=True, created_at=now()))
            self.audit(db, Actor(actor.user_id, oid), "organization_created", oid)
        return oid

    def invite(self, actor: Actor, email: str, role="member", ttl_days=7):
        email = normalize_email(email)
        if role not in {"owner", "admin", "reviewer", "member"}:
            raise ValueError("邀请角色无效。")
        token, iid = secrets.token_urlsafe(32), identifier("inv")
        with self.engine.begin() as db:
            caller = self.authorize(db, actor, {"owner", "admin"})
            if role == "owner" and caller["role"] != "platform_admin":
                raise ValueError("仅平台管理员可指定企业负责人。")
            if role == "admin" and caller["role"] == "admin":
                raise ValueError("企业管理员权限由企业负责人管理。")
            db.execute(t.invitations.insert().values(id=iid, email=email,
                organization_id=actor.organization_id, role=role, token_hash=hash_invitation(token),
                expires_at=(datetime.now(timezone.utc) + timedelta(days=max(1, min(30, int(ttl_days))))).isoformat(timespec="microseconds"),
                created_by=actor.user_id, accepted_at="", revoked=False, created_at=now()))
            self.audit(db, actor, "invitation_created", iid, email=email, role=role)
        return token

    def accept_invitation(self, uid: str, token: str):
        if not isinstance(token, str) or not 32 <= len(token.strip()) <= 128:
            raise ValueError("邀请代码无效或已过期。")
        with self.engine.begin() as db:
            user = db.execute(select(t.users).where(t.users.c.id == uid, t.users.c.active.is_(True))).mappings().first()
            if not user or not user["issuer"]:
                raise ValueError("请先验证邮箱身份。")
            invitation = db.execute(select(t.invitations).where(
                t.invitations.c.token_hash == hash_invitation(token.strip()), t.invitations.c.email == user["email"],
                t.invitations.c.accepted_at == "", t.invitations.c.revoked.is_(False),
                t.invitations.c.expires_at > now()).with_for_update()).mappings().first()
            if not invitation:
                raise ValueError("邀请代码无效、已使用或与登录邮箱不符。")
            actor = Actor(uid, invitation["organization_id"])
            org = db.execute(select(t.organizations.c.id).where(t.organizations.c.id == actor.organization_id,
                t.organizations.c.active.is_(True))).first()
            if not org:
                raise ValueError("受邀企业已停用。")
            # Inviter must still be authorized when the code is redeemed.
            self.authorize(db, Actor(invitation["created_by"], actor.organization_id), {"owner", "admin"})
            member = db.execute(select(t.memberships).where(t.memberships.c.user_id == uid,
                t.memberships.c.organization_id == actor.organization_id)).first()
            if member:
                raise ValueError("此账号已有企业成员记录，请由管理员管理权限。")
            consumed = db.execute(update(t.invitations).where(t.invitations.c.id == invitation["id"],
                t.invitations.c.accepted_at == "", t.invitations.c.revoked.is_(False)).values(accepted_at=now()))
            if consumed.rowcount != 1:
                raise ValueError("邀请已被使用。")
            db.execute(t.memberships.insert().values(user_id=uid, organization_id=actor.organization_id,
                role=invitation["role"], active=True, created_at=now()))
            self.audit(db, actor, "invitation_accepted", invitation["id"])
        return actor.organization_id

    def members(self, actor: Actor):
        with self.engine.connect() as db:
            self.authorize(db, actor, {"owner", "admin", "reviewer"})
            return [dict(r) for r in db.execute(select(t.users.c.id, t.users.c.email, t.users.c.name,
                t.memberships.c.role, t.memberships.c.active).join(t.memberships).where(
                t.memberships.c.organization_id == actor.organization_id)).mappings()]

    def set_membership(self, actor: Actor, uid: str, role: str, active: bool):
        if role not in {"owner", "admin", "reviewer", "member"}:
            raise ValueError("成员角色无效。")
        with self.engine.begin() as db:
            caller = self.authorize(db, actor, {"owner", "admin"})
            member = db.execute(select(t.memberships).where(t.memberships.c.user_id == uid,
                t.memberships.c.organization_id == actor.organization_id).with_for_update()).mappings().first()
            if not member or uid == actor.user_id:
                raise ValueError("不能修改自己的权限，或成员不存在。")
            if (member["role"] == "owner" or role == "owner") and caller["role"] != "platform_admin":
                raise ValueError("企业负责人权限由平台管理员管理。")
            if caller["role"] == "admin" and (member["role"] == "admin" or role == "admin"):
                raise ValueError("企业管理员权限由企业负责人管理。")
            db.execute(update(t.memberships).where(t.memberships.c.user_id == uid,
                t.memberships.c.organization_id == actor.organization_id).values(role=role, active=bool(active)))
            self.audit(db, actor, "membership_changed", uid, role=role, active=bool(active))

    def invitations(self, actor: Actor):
        with self.engine.connect() as db:
            self.authorize(db, actor, {"owner", "admin", "reviewer"})
            return [dict(r) for r in db.execute(select(t.invitations.c.id, t.invitations.c.email,
                t.invitations.c.role, t.invitations.c.expires_at, t.invitations.c.accepted_at,
                t.invitations.c.revoked).where(t.invitations.c.organization_id == actor.organization_id)
                .order_by(t.invitations.c.created_at.desc()).limit(100)).mappings()]

    def revoke_invitation(self, actor: Actor, iid: str):
        with self.engine.begin() as db:
            self.authorize(db, actor, {"owner", "admin"})
            row = db.execute(update(t.invitations).where(t.invitations.c.id == iid,
                t.invitations.c.organization_id == actor.organization_id, t.invitations.c.accepted_at == "")
                .values(revoked=True))
            if row.rowcount != 1:
                raise ValueError("邀请不存在或已经使用。")
            self.audit(db, actor, "invitation_revoked", iid)

    def audit_log(self, actor: Actor):
        with self.engine.connect() as db:
            caller = self.authorize(db, actor, {"owner", "admin", "reviewer"})
            scope = t.audit_events.c.organization_id == actor.organization_id
            if caller["role"] == "platform_admin":
                scope = scope | (t.audit_events.c.organization_id == "")
            return [dict(r) for r in db.execute(select(t.audit_events).where(scope)
                .order_by(t.audit_events.c.created_at.desc()).limit(100)).mappings()]
