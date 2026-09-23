from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import zipfile

from app.backup import create_backup, restore_local_backup, verify_backup
from app.blob_store import BlobStore
from app import platform_db as db_schema
from app.platform_db import engine_for
from app.platform_store import Actor, PlatformStore
from app.pilot_intake import PilotIntakeStore


def supplier_document():
    return {
        "side": "supplier",
        "fields": {
            "profile.organization": "试点合作社", "profile.entityType": "合作社", "profile.address": "测试地址",
            "profile.contact": "测试联系人", "profile.recorder": "测试填报人", "profile.recordDate": "2026-09-07",
            "profile.source": "种植台账", "base.baseName": "测试基地", "base.plot": "P01", "base.origin": "重庆",
            "base.area": "12", "base.variety": "脐橙", "harvest.batch": "B-TEST-001", "harvest.date": "2026-09-07",
            "harvest.plots": "P01", "harvest.quantity": "2000", "harvest.unit": "kg", "harvest.operator": "测试负责人",
            "quality.grade": "一级", "quality.testStatus": "尚未检测", "consent.platformUse": True,
        },
        "declarations": {"fertilizers": "未使用", "pesticides": "未使用"},
        "rows": {}, "attachments": [],
    }


def test_invite_requires_verified_email_and_assigns_membership(tmp_path):
    store = PlatformStore(f"sqlite:///{tmp_path / 'platform.db'}")
    store.initialize()
    admin_uid = store.bootstrap_admin("admin@example.com")
    admin = store.principal(admin_uid)
    org = admin["organizations"][0]["id"]
    token = store.invite(Actor(admin["user"]["id"], org), "buyer@example.com", "member")
    uid = store.dev_authenticate("buyer@example.com")
    store.accept_invitation(uid, token)
    store.dev_authenticate("buyer@example.com")
    principal = store.principal(uid)
    assert principal["organizations"][0]["id"] == org
    assert principal["organizations"][0]["role"] == "member"
    assert any(row["event"] == "dev_login_succeeded" for row in store.audit_log(Actor(admin_uid, org)))


def test_pilot_intake_is_tenant_scoped_and_review_is_version_bound(tmp_path):
    store = PlatformStore(f"sqlite:///{tmp_path / 'platform.db'}")
    store.initialize()
    admin_uid = store.bootstrap_admin("admin@example.com")
    admin = store.principal(admin_uid)
    org = admin["organizations"][0]["id"]
    token = store.invite(Actor(admin["user"]["id"], org), "supplier@example.com")
    uid = store.dev_authenticate("supplier@example.com")
    store.accept_invitation(uid, token)
    actor = Actor(uid, org)
    intake = PilotIntakeStore(store, actor, BlobStore(tmp_path / "files"))
    saved = intake.save(uid, org, supplier_document())["document"]
    assert saved["status"] == "draft"
    submitted = intake.save(uid, org, saved, submit=True)["document"]
    assert submitted["status"] == "submitted"
    assert intake.list(uid, org)[0]["id"] == submitted["id"]
    admin_intake = PilotIntakeStore(store, Actor(admin["user"]["id"], org), BlobStore(tmp_path / "files"))
    admin_intake.review(submitted["id"], submitted["revision"], "approved", "资料已核对")
    exported = __import__("json").loads(admin_intake.export_all())
    assert exported["records"][0]["id"] == submitted["id"]
    with __import__("pytest").raises(ValueError, match="无权"):
        intake.review(submitted["id"], submitted["revision"], "approved", "不应允许")


def test_blob_store_rejects_path_escape(tmp_path):
    store = BlobStore(tmp_path)
    raw = b"%PDF-1.7\n%%EOF"
    saved = store.put("org_" + "a" * 32, "report.pdf", raw)
    assert store.read(saved) == raw
    with __import__("pytest").raises(ValueError):
        store.read({"key": "org_" + "a" * 32 + "/../escape.pdf", "size": 1, "sha256": "x"})


def test_oidc_requires_verified_email_and_accepts_string_true(tmp_path):
    store = PlatformStore(f"sqlite:///{tmp_path / 'platform.db'}")
    store.initialize()
    with __import__("pytest").raises(ValueError, match="验证邮箱"):
        store.authenticate({"email": "person@example.com", "email_verified": False, "iss": "https://issuer", "sub": "p1"})
    uid = store.authenticate({"email": "person@example.com", "email_verified": "true", "iss": "https://issuer", "sub": "p1"})
    assert store.principal(uid)["user"]["email"] == "person@example.com"
    with __import__("pytest").raises(ValueError, match="其他身份"):
        store.authenticate({"email": "person@example.com", "email_verified": True, "iss": "https://issuer", "sub": "other"})


def test_invitation_expiry_reuse_and_reviewer_permissions(tmp_path):
    store = PlatformStore(f"sqlite:///{tmp_path / 'platform.db'}")
    store.initialize()
    admin_uid = store.bootstrap_admin("admin@example.com")
    org = store.principal(admin_uid)["organizations"][0]["id"]
    admin = Actor(admin_uid, org)
    reviewer_token = store.invite(admin, "reviewer@example.com", role="reviewer")
    reviewer_uid = store.dev_authenticate("reviewer@example.com")
    store.accept_invitation(reviewer_uid, reviewer_token)
    with __import__("pytest").raises(ValueError, match="无权"):
        store.invite(Actor(reviewer_uid, org), "other@example.com")
    with __import__("pytest").raises(ValueError, match="已使用"):
        store.accept_invitation(reviewer_uid, reviewer_token)
    expired = store.invite(admin, "expired@example.com")
    with store.engine.begin() as connection:
        connection.execute(db_schema.invitations.update().values(
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()))
    expired_uid = store.dev_authenticate("expired@example.com")
    with __import__("pytest").raises(ValueError, match="无效、已使用"):
        store.accept_invitation(expired_uid, expired)


def test_invitation_is_bound_to_email_and_login_is_audited(tmp_path):
    store = PlatformStore(f"sqlite:///{tmp_path / 'platform.db'}")
    store.initialize()
    admin_uid = store.bootstrap_admin("admin@example.com")
    org = store.principal(admin_uid)["organizations"][0]["id"]
    token = store.invite(Actor(admin_uid, org), "invited@example.com")
    wrong_uid = store.dev_authenticate("wrong@example.com")
    with __import__("pytest").raises(ValueError, match="邮箱不符"):
        store.accept_invitation(wrong_uid, token)
    claims = {"email": "verified@example.com", "email_verified": "false", "iss": "issuer", "sub": "1"}
    with __import__("pytest").raises(ValueError, match="验证邮箱"):
        store.authenticate(claims)
    verified_uid = store.authenticate({**claims, "email": "verified@example.com", "email_verified": True})
    events = store.audit_log(Actor(admin_uid, org))
    assert any(row["event"] == "login_succeeded" and row["actor"] == verified_uid for row in events)


def test_membership_roles_and_tenant_isolation(tmp_path):
    store = PlatformStore(f"sqlite:///{tmp_path / 'platform.db'}")
    store.initialize()
    admin_uid = store.bootstrap_admin("admin@example.com")
    org1 = store.principal(admin_uid)["organizations"][0]["id"]
    org2 = store.create_organization(Actor(admin_uid), "第二试点企业")
    token = store.invite(Actor(admin_uid, org1), "member@example.com")
    member_uid = store.dev_authenticate("member@example.com")
    store.accept_invitation(member_uid, token)
    with store.engine.connect() as connection:
        with __import__("pytest").raises(ValueError):
            store.authorize(connection, Actor(member_uid, org2))
    with __import__("pytest").raises(ValueError, match="无权"):
        store.set_membership(Actor(member_uid, org1), admin_uid, "owner", True)
    assert org1 != org2


def test_backup_verify_and_restore_round_trip(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    attachments = runtime / "attachments"
    db_path = runtime / "pilot.db"
    store = PlatformStore(f"sqlite:///{db_path}")
    store.initialize()
    admin_uid = store.bootstrap_admin("admin@example.com")
    attachment = attachments / "org_demo" / "sample.pdf"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"%PDF-test")
    (runtime / "settings.json").write_text('{"pilot": true}', encoding="utf-8")
    monkeypatch.setenv("CITRUS_BLOB_BACKEND", "local")
    archive = tmp_path / "backups" / "pilot.zip"
    create_backup(archive, db_url=f"sqlite:///{db_path}", runtime=runtime, blobs=attachments)
    manifest = verify_backup(archive)
    assert manifest["format"] == 2
    assert any(item["area"] == "attachments" for item in manifest["files"])
    restored = restore_local_backup(archive, tmp_path / "restore")
    assert (restored / "database" / "pilot.db").is_file()
    assert (restored / "attachments" / "org_demo" / "sample.pdf").read_bytes() == b"%PDF-test"
    with __import__("pytest").raises(ValueError, match="非空"):
        restore_local_backup(archive, restored)


def test_backup_rejects_zip_path_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    manifest = {
        "format": 2,
        "database_url_backend": "sqlite",
        "database_file": "database/pilot.db",
        "files": [{"area": "runtime", "path": "../escape.txt", "size": 1, "sha256": "x"}],
    }
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("database/pilot.db", b"x")
    with __import__("pytest").raises(ValueError, match="无效路径"):
        verify_backup(archive)
