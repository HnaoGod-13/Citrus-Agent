"""Portable SQLAlchemy schema for the invited enterprise pilot (schema v1)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (Boolean, Column, ForeignKey, Integer, MetaData, String,
                        Table, Text, UniqueConstraint, create_engine, event)
from sqlalchemy.engine import make_url

metadata = MetaData()

schema_versions = Table("schema_versions", metadata,
    Column("version", Integer, primary_key=True))
users = Table("platform_users", metadata,
    Column("id", String(64), primary_key=True), Column("email", String(254), unique=True, nullable=False),
    Column("issuer", Text, nullable=True), Column("subject", String(512), nullable=True),
    Column("name", String(200), nullable=False), Column("active", Boolean, nullable=False),
    Column("platform_admin", Boolean, nullable=False), Column("created_at", String(40), nullable=False),
    UniqueConstraint("issuer", "subject"))
organizations = Table("organizations", metadata,
    Column("id", String(64), primary_key=True), Column("name", String(200), nullable=False),
    Column("active", Boolean, nullable=False), Column("created_at", String(40), nullable=False))
memberships = Table("memberships", metadata,
    Column("user_id", ForeignKey("platform_users.id"), primary_key=True),
    Column("organization_id", ForeignKey("organizations.id"), primary_key=True),
    Column("role", String(24), nullable=False), Column("active", Boolean, nullable=False),
    Column("created_at", String(40), nullable=False))
invitations = Table("invitations", metadata,
    Column("id", String(64), primary_key=True), Column("email", String(254), nullable=False),
    Column("organization_id", ForeignKey("organizations.id"), nullable=False),
    Column("role", String(24), nullable=False), Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", String(40), nullable=False), Column("created_by", ForeignKey("platform_users.id")),
    Column("accepted_at", String(40), nullable=False), Column("revoked", Boolean, nullable=False),
    Column("created_at", String(40), nullable=False))
records = Table("pilot_records", metadata,
    Column("id", String(64), primary_key=True),
    Column("organization_id", ForeignKey("organizations.id"), nullable=False, index=True),
    Column("created_by", ForeignKey("platform_users.id"), nullable=False),
    Column("updated_by", ForeignKey("platform_users.id"), nullable=False),
    Column("side", String(20), nullable=False), Column("title", String(500), nullable=False),
    Column("status", String(24), nullable=False), Column("revision", Integer, nullable=False),
    Column("payload", Text, nullable=False), Column("task_id", String(64), nullable=False),
    Column("review_note", Text, nullable=False), Column("reviewed_by", String(64), nullable=False),
    Column("reviewed_revision", Integer, nullable=True),
    Column("created_at", String(40), nullable=False), Column("updated_at", String(40), nullable=False))
versions = Table("record_versions", metadata,
    Column("record_id", ForeignKey("pilot_records.id"), primary_key=True),
    Column("revision", Integer, primary_key=True), Column("payload", Text, nullable=False),
    Column("status", String(24), nullable=False), Column("actor", String(64), nullable=False),
    Column("created_at", String(40), nullable=False))
audit_events = Table("platform_audit_events", metadata,
    Column("id", String(64), primary_key=True), Column("actor", String(64), nullable=False),
    Column("organization_id", String(64), nullable=False, index=True),
    Column("event", String(64), nullable=False), Column("entity_id", String(64), nullable=False),
    Column("detail", Text, nullable=False), Column("created_at", String(40), nullable=False))


def runtime_dir() -> Path:
    return Path(os.getenv("CITRUS_RUNTIME_DIR") or Path(__file__).resolve().parents[1] / ".runtime").expanduser()


def database_url() -> str:
    value = os.getenv("CITRUS_DATABASE_URL", "").strip()
    if value:
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    runtime_dir().mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + (runtime_dir() / "pilot.db").as_posix()


@lru_cache(maxsize=8)
def engine_for(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,
        connect_args={"timeout": 20, "check_same_thread": False} if url.startswith("sqlite") else {})
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def configure(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def initialize(engine) -> None:
    """Explicit provisioning step; web requests never create/alter tables."""
    metadata.create_all(engine)
    with engine.begin() as db:
        if db.execute(schema_versions.select()).first() is None:
            db.execute(schema_versions.insert().values(version=1))
