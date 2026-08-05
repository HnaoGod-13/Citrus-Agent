from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .memory_config import (
    ALLOWED_MEMORY_TYPES,
    CONTEXT_TOKEN_BUDGETS,
    MEMORY_DB_PATH,
    MEMORY_LONG_TERM_TOP_K,
    MEMORY_MAX_CONTENT_CHARS,
    MEMORY_MIN_RELEVANCE,
    MEMORY_RECENT_TOKEN_LIMIT,
    MEMORY_SAMPLE_TOP_K,
    MEMORY_SUMMARY_TOKEN_LIMIT,
    MEMORY_SUMMARY_TRIGGER_TOKENS,
    MEMORY_TOOL_RESULT_CHARS,
)
from .rag import LITERATURE_DB_PATH, database_stats


ROOT = Path(__file__).resolve().parents[1]
LITERATURE_PATH = ROOT / "data" / "literature" / "chunks.jsonl"
MESSAGE_STORAGE_VERSION = 2
WORKING_MEMORY_FIELDS = {
    "current_goal",
    "current_stage",
    "domain",
    "entities",
    "constraints",
    "confirmed_decisions",
    "completed_steps",
    "pending_steps",
    "required_inputs",
    "recent_tool_results",
    "referenced_files",
}
LIST_WORKING_FIELDS = {
    "constraints",
    "confirmed_decisions",
    "completed_steps",
    "pending_steps",
    "required_inputs",
    "recent_tool_results",
    "referenced_files",
}
DOMAIN_TERMS = {
    "柑橘", "陈皮", "甜橙", "脐橙", "茶枝柑", "砂糖橘", "沃柑", "橙汁", "果汁", "果肉",
    "果皮", "果胶", "精油", "黄酮", "种子", "副产物", "病害", "霉变", "农残", "重金属",
    "微生物", "黄曲霉", "加工", "质控", "文献", "样本", "实验", "产地", "品种",
}
SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|access[_-]?token|secret|password|passwd|authorization)",
    flags=re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{10,}"),
    re.compile(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*[^\s,;]{6,}"),
]
GREETING_PATTERN = re.compile(r"^(你好|您好|谢谢|多谢|辛苦了|好的|收到|再见)[！!。,.，\s]*$")


class MemoryManagerError(RuntimeError):
    pass


class MemoryValidationError(MemoryManagerError):
    pass


class MemoryIsolationError(MemoryManagerError):
    pass


class MemoryStorageError(MemoryManagerError):
    pass


class _ClosingSQLiteConnection(sqlite3.Connection):
    """sqlite3's default context manager commits but does not close on Windows."""

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_chunks = re.findall(r"[A-Za-z0-9_]+|[^\w\s]", re.sub(r"[\u3400-\u9fff]", " ", text))
    latin_cost = sum(max(1, math.ceil(len(chunk) / 4)) for chunk in latin_chunks)
    return cjk + latin_cost


def truncate_to_tokens(text: str, token_budget: int) -> str:
    text = str(text or "")
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= max(token_budget - 1, 1):
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


def _redact_text(text: str) -> str:
    value = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SECRET_KEY_PATTERN.search(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _safe_json(value: Any) -> str:
    return json.dumps(redact_sensitive(value), ensure_ascii=False, default=str, separators=(",", ":"))


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _normalize_text(value: Any, limit: int = MEMORY_MAX_CONTENT_CHARS) -> str:
    text = re.sub(r"\s+", " ", _redact_text(str(value or ""))).strip()
    return text[:limit]


def _normalize_message_content(value: Any) -> str:
    """Preserve display formatting while still redacting stored message text."""
    text = _redact_text(str(value or ""))
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_keywords(values: Iterable[Any] | None, content: str = "") -> list[str]:
    keywords: list[str] = []
    for value in values or []:
        term = _normalize_text(value, 60).lower()
        if term and term not in keywords:
            keywords.append(term)
    lowered = content.lower()
    for term in DOMAIN_TERMS:
        if term.lower() in lowered and term.lower() not in keywords:
            keywords.append(term.lower())
    for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|\d+(?:\.\d+)?%?", content):
        normalized = term.lower()
        if normalized not in keywords:
            keywords.append(normalized)
    return keywords[:40]


def _semantic_terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(text or "").lower())
    terms = set(re.findall(r"[a-z][a-z0-9_-]{1,}|\d+(?:\.\d+)?", normalized))
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    terms.update(chinese[index:index + 2] for index in range(max(len(chinese) - 1, 0)))
    terms.update(term for term in DOMAIN_TERMS if term.lower() in normalized)
    return {term for term in terms if term}


def _cosine_terms(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def _parse_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _recency_score(value: Any, half_life_days: float = 120.0) -> float:
    age_days = max((datetime.now(timezone.utc) - _parse_time(value)).total_seconds() / 86400.0, 0.0)
    return math.exp(-math.log(2) * age_days / max(half_life_days, 1.0))


def select_recent_messages(
    messages: list[dict[str, Any]],
    token_budget: int = MEMORY_RECENT_TOKEN_LIMIT,
) -> list[dict[str, str]]:
    if token_budget <= 0:
        return []
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        content = _normalize_text(message.get("content") or "")
        if role not in {"system", "user", "assistant", "tool"} or not content:
            continue
        normalized.append(
            {
                "index": index,
                "role": role,
                "content": content,
                "message_type": str(message.get("message_type") or ""),
                "token_count": int(message.get("token_count") or estimate_tokens(content)),
            }
        )
    selected: dict[int, dict[str, Any]] = {}
    remaining = token_budget
    system_allowance = min(max(token_budget // 4, 64), 600)
    system_used = 0

    for item in normalized:
        if item["role"] == "system":
            available = min(item["token_count"], remaining, max(system_allowance - system_used, 0))
            clipped = truncate_to_tokens(item["content"], available)
            if clipped and remaining > 0:
                selected[item["index"]] = {**item, "content": clipped, "token_count": estimate_tokens(clipped)}
                remaining -= estimate_tokens(clipped)
                system_used += estimate_tokens(clipped)

    recent_tool = next(
        (
            item
            for item in reversed(normalized)
            if item["role"] == "tool" or item["message_type"] == "tool_result"
        ),
        None,
    )
    if recent_tool and recent_tool["index"] not in selected and remaining > 0:
        tool_allowance = min(max(token_budget // 4, 64), 600)
        clipped = truncate_to_tokens(
            recent_tool["content"],
            min(recent_tool["token_count"], remaining, tool_allowance),
        )
        if clipped:
            selected[recent_tool["index"]] = {
                **recent_tool,
                "content": clipped,
                "token_count": estimate_tokens(clipped),
            }
            remaining -= estimate_tokens(clipped)

    recent_user = next((item for item in reversed(normalized) if item["role"] == "user"), None)
    if recent_user and recent_user["index"] not in selected and remaining > 0:
        user_allowance = min(max(token_budget // 4, 64), remaining)
        clipped = truncate_to_tokens(recent_user["content"], min(recent_user["token_count"], user_allowance))
        if clipped:
            selected[recent_user["index"]] = {
                **recent_user,
                "content": clipped,
                "token_count": estimate_tokens(clipped),
            }
            remaining -= estimate_tokens(clipped)

    for item in reversed(normalized):
        if item["index"] in selected or remaining <= 0:
            continue
        if item["token_count"] <= remaining:
            selected[item["index"]] = item
            remaining -= item["token_count"]
            continue
        if item["role"] in {"user", "assistant"} and remaining >= 64:
            clipped = truncate_to_tokens(item["content"], remaining)
            selected[item["index"]] = {**item, "content": clipped, "token_count": estimate_tokens(clipped)}
            remaining = 0

    return [
        {"role": item["role"], "content": item["content"]}
        for _, item in sorted(selected.items())
    ]


def describe_model_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    role_tokens: Counter[str] = Counter()
    for message in messages:
        role_tokens[str(message.get("role") or "unknown")] += estimate_tokens(message.get("content") or "")
    return {
        "message_count": len(messages),
        "estimated_tokens": int(sum(role_tokens.values())),
        "tokens_by_role": dict(role_tokens),
    }


def default_working_memory(
    session_id: str,
    user_id: str,
    project_id: str,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "project_id": project_id,
        "current_goal": "",
        "current_stage": "",
        "domain": "",
        "entities": {},
        "constraints": [],
        "confirmed_decisions": [],
        "completed_steps": [],
        "pending_steps": [],
        "required_inputs": [],
        "recent_tool_results": [],
        "referenced_files": [],
        "updated_at": utc_now(),
    }


class MemoryManager:
    def __init__(
        self,
        db_path: Path | str | None = None,
        default_user_id: str = "",
        default_project_id: str = "",
    ) -> None:
        self.db_path = Path(db_path or MEMORY_DB_PATH)
        self.default_user_id = _normalize_text(default_user_id, 160)
        self.default_project_id = _normalize_text(default_project_id, 160)
        self._lock = threading.RLock()
        self._fts_available = False
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.db_path,
                timeout=15,
                factory=_ClosingSQLiteConnection,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute("PRAGMA journal_mode=WAL")
            return connection
        except (OSError, sqlite3.Error) as error:
            if connection is not None:
                connection.close()
            raise MemoryStorageError(f"无法打开记忆数据库：{error}") from error

    def _initialize_database(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(user_id, project_id, updated_at);

        CREATE TABLE IF NOT EXISTS conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'chat',
            tool_name TEXT,
            tool_result_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON conversation_messages(session_id, id);
        CREATE INDEX IF NOT EXISTS idx_messages_scope ON conversation_messages(user_id, project_id, created_at);

        CREATE TABLE IF NOT EXISTS working_memory (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            state_json TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS conversation_summaries (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            summarized_through_id INTEGER NOT NULL DEFAULT 0,
            token_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            importance REAL NOT NULL DEFAULT 5,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            superseded_by TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            last_accessed_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_dedup
            ON memories(user_id, project_id, memory_type, content_hash, status);
        CREATE INDEX IF NOT EXISTS idx_memory_scope
            ON memories(user_id, project_id, status, memory_type, last_accessed_at);

        CREATE TABLE IF NOT EXISTS citrus_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            variety TEXT,
            origin TEXT,
            event_time TEXT,
            growth_stage TEXT,
            maturity TEXT,
            image_paths_json TEXT NOT NULL DEFAULT '[]',
            disease_or_quality TEXT,
            processing_goal TEXT,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            solution TEXT,
            outcome TEXT,
            source TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_samples_scope
            ON citrus_samples(user_id, project_id, status, variety, origin, updated_at);

        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            original_input TEXT NOT NULL,
            system_prompt_version TEXT NOT NULL,
            model_name TEXT,
            context_manifest_json TEXT NOT NULL DEFAULT '{}',
            retrieved_memory_ids_json TEXT NOT NULL DEFAULT '[]',
            retrieved_literature_ids_json TEXT NOT NULL DEFAULT '[]',
            retrieved_sample_ids_json TEXT NOT NULL DEFAULT '[]',
            tool_calls_json TEXT NOT NULL DEFAULT '[]',
            model_raw_output TEXT,
            final_output TEXT,
            state_updates_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_scope
            ON agent_runs(user_id, project_id, session_id, created_at);
        """
        try:
            with self._connect() as connection:
                connection.executescript(schema)
                try:
                    connection.executescript(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                            content, keywords,
                            content='memories', content_rowid='id',
                            tokenize='unicode61 remove_diacritics 2'
                        );
                        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                            INSERT INTO memories_fts(rowid, content, keywords)
                            VALUES (new.id, new.content, new.keywords_json);
                        END;
                        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                            INSERT INTO memories_fts(memories_fts, rowid, content, keywords)
                            VALUES ('delete', old.id, old.content, old.keywords_json);
                        END;
                        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                            INSERT INTO memories_fts(memories_fts, rowid, content, keywords)
                            VALUES ('delete', old.id, old.content, old.keywords_json);
                            INSERT INTO memories_fts(rowid, content, keywords)
                            VALUES (new.id, new.content, new.keywords_json);
                        END;
                        CREATE VIRTUAL TABLE IF NOT EXISTS samples_fts USING fts5(
                            variety, origin, disease_or_quality, processing_goal, solution, outcome, keywords,
                            content='citrus_samples', content_rowid='id',
                            tokenize='unicode61 remove_diacritics 2'
                        );
                        CREATE TRIGGER IF NOT EXISTS samples_ai AFTER INSERT ON citrus_samples BEGIN
                            INSERT INTO samples_fts(
                                rowid, variety, origin, disease_or_quality, processing_goal, solution, outcome, keywords
                            ) VALUES (
                                new.id, new.variety, new.origin, new.disease_or_quality,
                                new.processing_goal, new.solution, new.outcome, new.keywords_json
                            );
                        END;
                        CREATE TRIGGER IF NOT EXISTS samples_ad AFTER DELETE ON citrus_samples BEGIN
                            INSERT INTO samples_fts(
                                samples_fts, rowid, variety, origin, disease_or_quality,
                                processing_goal, solution, outcome, keywords
                            ) VALUES (
                                'delete', old.id, old.variety, old.origin, old.disease_or_quality,
                                old.processing_goal, old.solution, old.outcome, old.keywords_json
                            );
                        END;
                        CREATE TRIGGER IF NOT EXISTS samples_au AFTER UPDATE ON citrus_samples BEGIN
                            INSERT INTO samples_fts(
                                samples_fts, rowid, variety, origin, disease_or_quality,
                                processing_goal, solution, outcome, keywords
                            ) VALUES (
                                'delete', old.id, old.variety, old.origin, old.disease_or_quality,
                                old.processing_goal, old.solution, old.outcome, old.keywords_json
                            );
                            INSERT INTO samples_fts(
                                rowid, variety, origin, disease_or_quality, processing_goal, solution, outcome, keywords
                            ) VALUES (
                                new.id, new.variety, new.origin, new.disease_or_quality,
                                new.processing_goal, new.solution, new.outcome, new.keywords_json
                            );
                        END;
                        """
                    )
                    self._fts_available = True
                except sqlite3.Error:
                    self._fts_available = False
        except (sqlite3.Error, OSError, MemoryStorageError) as error:
            if isinstance(error, MemoryStorageError):
                raise
            raise MemoryStorageError(f"初始化记忆数据库失败：{error}") from error

    def _scope(self, user_id: str = "", project_id: str = "") -> tuple[str, str]:
        resolved_user = _normalize_text(user_id or self.default_user_id, 160)
        resolved_project = _normalize_text(project_id or self.default_project_id, 160)
        if not resolved_user or not resolved_project:
            raise MemoryIsolationError("记忆读写必须同时提供 user_id 和 project_id。")
        return resolved_user, resolved_project

    def ensure_session(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        user_id, project_id = self._scope(user_id, project_id)
        session_id = _normalize_text(session_id, 160)
        if not session_id:
            raise MemoryValidationError("session_id 不能为空。")
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, project_id FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row and (row["user_id"] != user_id or row["project_id"] != project_id):
                raise MemoryIsolationError("session_id 已属于其他用户或项目，拒绝交叉访问。")
            connection.execute(
                """
                INSERT INTO sessions(session_id,user_id,project_id,status,config_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status='active',
                    config_json=CASE WHEN ?=1 THEN excluded.config_json ELSE sessions.config_json END,
                    updated_at=excluded.updated_at
                """,
                (
                    session_id,
                    user_id,
                    project_id,
                    "active",
                    _safe_json(config or {}),
                    now,
                    now,
                    1 if config is not None else 0,
                ),
            )
            state = default_working_memory(session_id, user_id, project_id)
            connection.execute(
                """
                INSERT OR IGNORE INTO working_memory(
                    session_id,user_id,project_id,state_json,version,updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (session_id, user_id, project_id, _safe_json(state), 1, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO conversation_summaries(
                    session_id,user_id,project_id,summary,summarized_through_id,token_count,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (session_id, user_id, project_id, "", 0, 0, now),
            )

    def record_message(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
        role: str,
        content: str,
        *,
        message_id: str | None = None,
        message_type: str = "chat",
        tool_name: str = "",
        tool_result_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        user_id, project_id = self._scope(user_id, project_id)
        self.ensure_session(user_id, session_id, project_id)
        if role not in {"system", "user", "assistant", "tool"}:
            raise MemoryValidationError(f"不支持的消息角色：{role}")
        normalized = _normalize_message_content(content)
        if not normalized.strip():
            raise MemoryValidationError("不能保存空消息。")
        resolved_id = _normalize_text(message_id or f"msg_{uuid4().hex}", 160)
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO conversation_messages(
                    message_id,user_id,session_id,project_id,role,content,token_count,
                    message_type,tool_name,tool_result_id,metadata_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    resolved_id,
                    user_id,
                    session_id,
                    project_id,
                    role,
                    normalized,
                    estimate_tokens(normalized),
                    _normalize_text(message_type, 60) or "chat",
                    _normalize_text(tool_name, 120),
                    _normalize_text(tool_result_id, 160),
                    _safe_json(metadata or {}),
                    now,
                ),
            )
            connection.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        return resolved_id

    def restore_session_messages(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        user_id, project_id = self._scope(user_id, project_id)
        self.ensure_session(user_id, session_id, project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT message_id,role,content,token_count,message_type,tool_name,tool_result_id,metadata_json,created_at
                FROM conversation_messages
                WHERE user_id=? AND session_id=? AND project_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, session_id, project_id, max(int(limit), 1)),
            ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "token_count": row["token_count"],
                "message_type": row["message_type"],
                "tool_name": row["tool_name"],
                "tool_result_id": row["tool_result_id"],
                "metadata": _load_json(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def load_working_memory(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        user_id, project_id = self._scope(user_id, project_id)
        self.ensure_session(user_id, session_id, project_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state_json,version FROM working_memory
                WHERE user_id=? AND session_id=? AND project_id=?
                """,
                (user_id, session_id, project_id),
            ).fetchone()
        if not row:
            return default_working_memory(session_id, user_id, project_id)
        state = _load_json(row["state_json"], default_working_memory(session_id, user_id, project_id))
        state["version"] = int(row["version"])
        return state

    @staticmethod
    def _validated_list_update(existing: list[Any], update: Any) -> list[str]:
        if isinstance(update, dict):
            if "set" in update:
                if not isinstance(update.get("set"), list):
                    raise MemoryValidationError("列表字段的 set 值必须是列表。")
                add = update.get("set", [])
                values = []
            else:
                add = update.get("add", [])
                remove = {_normalize_text(item, 500) for item in update.get("remove", [])}
                values = [item for item in existing if _normalize_text(item, 500) not in remove]
        elif isinstance(update, list):
            add = update
            values = list(existing)
        else:
            raise MemoryValidationError("列表型工作记忆字段必须为列表或 {set}/{add, remove}。")
        for item in add:
            normalized = _normalize_text(item, 500)
            if normalized and normalized not in values:
                values.append(normalized)
        return values[-100:]

    def update_working_memory(
        self,
        session_id: str,
        updates: dict[str, Any],
        *,
        user_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any]:
        user_id, project_id = self._scope(user_id, project_id)
        current = self.load_working_memory(user_id, session_id, project_id)
        if not isinstance(updates, dict):
            raise MemoryValidationError("工作记忆更新必须是字典。")
        rejected = set(updates) - WORKING_MEMORY_FIELDS
        if rejected:
            raise MemoryValidationError(f"不允许更新工作记忆字段：{sorted(rejected)}")

        state = {key: value for key, value in current.items() if key != "version"}
        for key, value in updates.items():
            if key == "entities":
                if not isinstance(value, dict):
                    raise MemoryValidationError("entities 必须是字典。")
                entities = dict(state.get("entities") or {})
                for entity_key, entity_value in value.items():
                    normalized_key = _normalize_text(entity_key, 100)
                    if not normalized_key:
                        continue
                    if entity_value in (None, ""):
                        entities.pop(normalized_key, None)
                    else:
                        entities[normalized_key] = redact_sensitive(entity_value)
                state["entities"] = dict(list(entities.items())[-100:])
            elif key in LIST_WORKING_FIELDS:
                state[key] = self._validated_list_update(list(state.get(key) or []), value)
            else:
                if not isinstance(value, (str, int, float, bool)) and value is not None:
                    raise MemoryValidationError(f"{key} 必须是标量。")
                state[key] = _normalize_text(value, 1000)
        state.update(
            {
                "session_id": session_id,
                "user_id": user_id,
                "project_id": project_id,
                "updated_at": utc_now(),
            }
        )
        version = int(current.get("version") or 1) + 1
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE working_memory
                SET state_json=?, version=?, updated_at=?
                WHERE user_id=? AND session_id=? AND project_id=?
                """,
                (_safe_json(state), version, state["updated_at"], user_id, session_id, project_id),
            )
        state["version"] = version
        return state

    def _summary_record(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT summary,summarized_through_id,token_count,updated_at
                FROM conversation_summaries
                WHERE user_id=? AND session_id=? AND project_id=?
                """,
                (user_id, session_id, project_id),
            ).fetchone()
        return dict(row) if row else {
            "summary": "",
            "summarized_through_id": 0,
            "token_count": 0,
            "updated_at": "",
        }

    @staticmethod
    def _incremental_summary(
        old_summary: str,
        messages: list[sqlite3.Row],
        working: dict[str, Any],
    ) -> str:
        history_lines: list[str] = []
        if old_summary.strip():
            history_lines.extend(
                line.strip()
                for line in old_summary.splitlines()
                if line.strip() and not line.startswith("增量对话摘要")
            )

        protected = [
            ("目标", working.get("current_goal")),
            ("阶段", working.get("current_stage")),
            ("领域", working.get("domain")),
            ("实体", _safe_json(working.get("entities") or {})),
            ("约束", "；".join(working.get("constraints") or [])),
            ("已确认决定", "；".join(working.get("confirmed_decisions") or [])),
            ("待办", "；".join(working.get("pending_steps") or [])),
            ("待补输入", "；".join(working.get("required_inputs") or [])),
            ("文件", "；".join(working.get("referenced_files") or [])),
        ]
        protected_lines: list[str] = []
        for label, value in protected:
            normalized = _normalize_text(value, 1200)
            if normalized and normalized not in {"{}", "[]"}:
                protected_lines.append(f"- {label}：{normalized}")

        for row in messages:
            content = _normalize_text(row["content"], 900)
            if not content or GREETING_PATTERN.match(content):
                continue
            role_label = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}.get(
                row["role"], row["role"]
            )
            high_value = (
                row["role"] in {"user", "tool"}
                or any(term in content for term in DOMAIN_TERMS)
                or bool(re.search(r"\d+(?:\.\d+)?(?:%|kg|°?bx|天|小时|分钟)?", content, flags=re.I))
            )
            if high_value:
                history_lines.append(f"- {role_label}：{content}")

        deduplicated_history: list[str] = []
        seen: set[str] = set()
        for line in history_lines:
            key = re.sub(r"\s+", "", line).lower()
            if key and key not in seen:
                seen.add(key)
                deduplicated_history.append(line)

        deduplicated_protected: list[str] = []
        for line in protected_lines:
            key = re.sub(r"\s+", "", line).lower()
            if key and key not in seen:
                seen.add(key)
                deduplicated_protected.append(line)

        header = "增量对话摘要："
        protected_text = "\n".join(deduplicated_protected)
        reserved = estimate_tokens(header) + estimate_tokens(protected_text)
        remaining = max(MEMORY_SUMMARY_TOKEN_LIMIT - reserved - 8, 0)
        selected_latest: list[str] = []
        used = 0
        for line in reversed(deduplicated_history[-120:]):
            cost = estimate_tokens(line) + 1
            if used + cost > remaining:
                continue
            selected_latest.append(line)
            used += cost
        selected_latest.reverse()
        sections = [header]
        if deduplicated_protected:
            sections.extend(deduplicated_protected)
        sections.extend(selected_latest)
        return truncate_to_tokens("\n".join(sections), MEMORY_SUMMARY_TOKEN_LIMIT)

    def summarize_history(
        self,
        session_id: str,
        *,
        user_id: str = "",
        project_id: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        user_id, project_id = self._scope(user_id, project_id)
        self.ensure_session(user_id, session_id, project_id)
        current = self._summary_record(user_id, session_id, project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id,role,content,token_count,message_type
                FROM conversation_messages
                WHERE user_id=? AND session_id=? AND project_id=?
                ORDER BY id
                """,
                (user_id, session_id, project_id),
            ).fetchall()
        total_tokens = sum(int(row["token_count"]) for row in rows)
        if not force and total_tokens <= MEMORY_SUMMARY_TRIGGER_TOKENS:
            return current

        recent_budget = MEMORY_RECENT_TOKEN_LIMIT
        recent_ids: set[int] = set()
        for row in reversed(rows):
            cost = int(row["token_count"])
            if cost > recent_budget:
                break
            recent_ids.add(int(row["id"]))
            recent_budget -= cost
        cursor = int(current.get("summarized_through_id") or 0)
        new_rows = [row for row in rows if int(row["id"]) > cursor and int(row["id"]) not in recent_ids]
        if not new_rows:
            return current

        working = self.load_working_memory(user_id, session_id, project_id)
        summary = self._incremental_summary(str(current.get("summary") or ""), new_rows, working)
        through_id = max(int(row["id"]) for row in new_rows)
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE conversation_summaries
                SET summary=?, summarized_through_id=?, token_count=?, updated_at=?
                WHERE user_id=? AND session_id=? AND project_id=?
                """,
                (
                    summary,
                    through_id,
                    estimate_tokens(summary),
                    now,
                    user_id,
                    session_id,
                    project_id,
                ),
            )
        return {
            "summary": summary,
            "summarized_through_id": through_id,
            "token_count": estimate_tokens(summary),
            "updated_at": now,
        }

    def save_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(memory, dict):
            raise MemoryValidationError("长期记忆必须是字典。")
        user_id, project_id = self._scope(
            str(memory.get("user_id") or ""),
            str(memory.get("project_id") or ""),
        )
        session_id = _normalize_text(memory.get("session_id") or "", 160)
        if not session_id:
            raise MemoryValidationError("长期记忆必须包含 session_id。")
        self.ensure_session(user_id, session_id, project_id)
        memory_type = _normalize_text(memory.get("memory_type") or "", 80)
        if memory_type not in ALLOWED_MEMORY_TYPES:
            raise MemoryValidationError(f"不支持的 memory_type：{memory_type}")
        content = _normalize_text(memory.get("content") or "")
        if not content or GREETING_PATTERN.match(content):
            raise MemoryValidationError("该内容不适合保存为长期记忆。")
        importance = min(max(float(memory.get("importance") or 5), 0.0), 10.0)
        source = _normalize_text(memory.get("source") or "user_confirmed", 160)
        source_id = _normalize_text(memory.get("source_id") or f"src_{uuid4().hex}", 160)
        metadata = redact_sensitive(memory.get("metadata") or {})
        keywords = _normalize_keywords(memory.get("keywords") or [], content)
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        now = utc_now()

        with self._lock, self._connect() as connection:
            duplicate = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id=? AND project_id=? AND memory_type=? AND content_hash=? AND status='active'
                LIMIT 1
                """,
                (user_id, project_id, memory_type, content_hash),
            ).fetchone()
            if duplicate:
                connection.execute(
                    "UPDATE memories SET importance=?,last_accessed_at=? WHERE memory_id=?",
                    (max(float(duplicate["importance"]), importance), now, duplicate["memory_id"]),
                )
                result = dict(duplicate)
                result["deduplicated"] = True
                return result

            memory_id = _normalize_text(memory.get("memory_id") or f"mem_{uuid4().hex}", 160)
            conflict_key = _normalize_text((metadata or {}).get("conflict_key") or "", 160)
            conflicting_ids: list[str] = []
            if conflict_key:
                rows = connection.execute(
                    """
                    SELECT memory_id,metadata_json,content FROM memories
                    WHERE user_id=? AND project_id=? AND memory_type=? AND status='active'
                    """,
                    (user_id, project_id, memory_type),
                ).fetchall()
                for row in rows:
                    old_metadata = _load_json(row["metadata_json"], {})
                    if str(old_metadata.get("conflict_key") or "") == conflict_key and row["content"] != content:
                        conflicting_ids.append(str(row["memory_id"]))

            connection.execute(
                """
                INSERT INTO memories(
                    memory_id,user_id,session_id,project_id,memory_type,content,keywords_json,
                    importance,source,source_id,content_hash,status,superseded_by,metadata_json,
                    created_at,last_accessed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    memory_id,
                    user_id,
                    session_id,
                    project_id,
                    memory_type,
                    content,
                    _safe_json(keywords),
                    importance,
                    source,
                    source_id,
                    content_hash,
                    "active",
                    None,
                    _safe_json(metadata),
                    now,
                    now,
                ),
            )
            if conflicting_ids and bool((metadata or {}).get("confirmed", False)):
                connection.executemany(
                    "UPDATE memories SET status='superseded',superseded_by=? WHERE memory_id=?",
                    [(memory_id, old_id) for old_id in conflicting_ids],
                )
        return {
            "memory_id": memory_id,
            "user_id": user_id,
            "session_id": session_id,
            "project_id": project_id,
            "memory_type": memory_type,
            "content": content,
            "keywords": keywords,
            "importance": importance,
            "source": source,
            "source_id": source_id,
            "status": "active",
            "superseded_memory_ids": conflicting_ids,
            "created_at": now,
        }

    def _memory_candidates(
        self,
        user_id: str,
        project_id: str,
        filters: dict[str, Any],
    ) -> list[sqlite3.Row]:
        clauses = ["m.user_id=?", "m.project_id=?", "m.status='active'"]
        params: list[Any] = [user_id, project_id]
        if filters.get("session_id"):
            clauses.append("m.session_id=?")
            params.append(str(filters["session_id"]))
        memory_types = filters.get("memory_type") or filters.get("memory_types")
        if isinstance(memory_types, str):
            memory_types = [memory_types]
        if memory_types:
            placeholders = ",".join("?" for _ in memory_types)
            clauses.append(f"m.memory_type IN ({placeholders})")
            params.extend(str(value) for value in memory_types)
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT m.* FROM memories AS m
                WHERE {' AND '.join(clauses)}
                ORDER BY m.last_accessed_at DESC
                LIMIT 500
                """,
                params,
            ).fetchall()

    def search_memories(
        self,
        query: str,
        filters: dict[str, Any],
        top_k: int = MEMORY_LONG_TERM_TOP_K,
    ) -> list[dict[str, Any]]:
        if not isinstance(filters, dict):
            raise MemoryValidationError("filters 必须是字典。")
        user_id, project_id = self._scope(
            str(filters.get("user_id") or ""),
            str(filters.get("project_id") or ""),
        )
        query_text = _normalize_text(query, 4000)
        query_terms = _semantic_terms(query_text)
        query_keywords = set(_normalize_keywords([], query_text))
        ranked: list[tuple[float, dict[str, Any]]] = []
        seen_hashes: set[str] = set()
        for row in self._memory_candidates(user_id, project_id, filters):
            if row["content_hash"] in seen_hashes:
                continue
            seen_hashes.add(row["content_hash"])
            keywords = _load_json(row["keywords_json"], [])
            candidate_terms = _semantic_terms(f"{row['content']} {' '.join(keywords)}")
            semantic = _cosine_terms(query_terms, candidate_terms)
            keyword = len(query_keywords & set(keywords)) / max(len(query_keywords), 1)
            recency = _recency_score(row["last_accessed_at"])
            importance = min(max(float(row["importance"]) / 10.0, 0.0), 1.0)
            scope_bonus = 1.0
            if query_text and semantic < 0.05 and keyword <= 0:
                continue
            score = 0.38 * semantic + 0.24 * keyword + 0.14 * recency + 0.16 * importance + 0.08 * scope_bonus
            if query_text and score < MEMORY_MIN_RELEVANCE:
                continue
            item = dict(row)
            item["keywords"] = keywords
            item["metadata"] = _load_json(row["metadata_json"], {})
            item["final_score"] = round(score, 4)
            for key in ["keywords_json", "metadata_json", "id", "content_hash"]:
                item.pop(key, None)
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        selected = [item for _, item in ranked[:max(int(top_k), 1)]]
        if selected:
            now = utc_now()
            with self._lock, self._connect() as connection:
                connection.executemany(
                    "UPDATE memories SET last_accessed_at=? WHERE memory_id=?",
                    [(now, item["memory_id"]) for item in selected],
                )
        return selected

    def capture_long_term_from_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        project_id: str,
        user_input: str,
        source_id: str,
    ) -> list[dict[str, Any]]:
        text = _normalize_text(user_input)
        if not text or GREETING_PATTERN.match(text) or "[REDACTED]" in _redact_text(text):
            return []
        candidates: list[tuple[str, int, str]] = []
        if re.search(r"(请记住|帮我记住|以后都|今后都|默认|我的偏好|我们习惯)", text):
            memory_type = "user_preference" if re.search(r"(偏好|习惯|默认|喜欢|不要)", text) else "project_decision"
            candidates.append((memory_type, 9, "explicit_memory_request"))
        if re.search(r"(已经决定|确认采用|最终选择|项目决定|统一使用|以后采用)", text):
            candidates.append(("project_decision", 8, "confirmed_decision"))
        if re.search(r"\d+(?:\.\d+)?\s*(?:%|kg|公斤|°?bx|brix|小时|分钟|天|℃|°c)", text, flags=re.I) and re.search(
            r"(实验|小试|参数|温度|时间|浓度|糖度|酸度|水分|产率|得率)", text
        ):
            candidates.append(("experiment_parameter", 8, "confirmed_parameter"))
        if re.search(r"([A-Za-z]:[\\/][^\s]+|[^\s]+\.(?:pdf|docx?|xlsx?|csv|json|md))", text, flags=re.I):
            candidates.append(("document_reference", 7, "file_reference"))

        saved: list[dict[str, Any]] = []
        seen_types: set[str] = set()
        for memory_type, importance, reason in candidates:
            if memory_type in seen_types:
                continue
            seen_types.add(memory_type)
            saved.append(
                self.save_memory(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "project_id": project_id,
                        "memory_type": memory_type,
                        "content": text,
                        "keywords": [],
                        "importance": importance,
                        "source": "user_confirmed",
                        "source_id": source_id,
                        "metadata": {
                            "write_reason": reason,
                            "confirmed": True,
                            "conflict_key": f"{memory_type}:{','.join(_normalize_keywords([], text)[:3])}",
                        },
                    }
                )
            )
        return saved

    def save_sample(self, sample: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(sample, dict):
            raise MemoryValidationError("历史样本必须是字典。")
        user_id, project_id = self._scope(
            str(sample.get("user_id") or ""),
            str(sample.get("project_id") or ""),
        )
        session_id = _normalize_text(sample.get("session_id") or "", 160)
        if not session_id:
            raise MemoryValidationError("历史样本必须包含 session_id。")
        self.ensure_session(user_id, session_id, project_id)
        fields = {
            "variety": _normalize_text(sample.get("variety"), 160),
            "origin": _normalize_text(sample.get("origin"), 160),
            "event_time": _normalize_text(sample.get("time") or sample.get("event_time"), 80),
            "growth_stage": _normalize_text(sample.get("growth_stage"), 160),
            "maturity": _normalize_text(sample.get("maturity"), 160),
            "disease_or_quality": _normalize_text(sample.get("disease_or_quality"), 1000),
            "processing_goal": _normalize_text(sample.get("processing_goal"), 1000),
            "solution": _normalize_text(sample.get("solution"), 3000),
            "outcome": _normalize_text(sample.get("outcome"), 3000),
            "source": _normalize_text(sample.get("source") or "agent_analysis", 160),
        }
        metrics = redact_sensitive(sample.get("metrics") or {})
        image_paths = [_normalize_text(path, 500) for path in sample.get("image_paths") or [] if _normalize_text(path, 500)]
        confidence = min(max(float(sample.get("confidence") or 0.5), 0.0), 1.0)
        keywords = _normalize_keywords(
            sample.get("keywords") or [],
            " ".join(str(value) for value in fields.values()),
        )
        identity = _safe_json({**fields, "metrics": metrics, "image_paths": image_paths})
        scoped_identity = _safe_json(
            {"user_id": user_id, "project_id": project_id, "sample": identity}
        )
        sample_hash = hashlib.sha256(scoped_identity.encode("utf-8")).hexdigest()
        sample_id = _normalize_text(sample.get("sample_id") or f"sample_{sample_hash[:24]}", 160)
        now = utc_now()
        try:
            with self._lock, self._connect() as connection:
                # Make deduplication atomic. Streamlit may execute overlapping
                # reruns in different threads/processes, so a SELECT followed by
                # a plain INSERT can still race on the globally unique sample_id.
                candidate_id = sample_id
                for collision_attempt in range(2):
                    changes_before = connection.total_changes
                    connection.execute(
                        """
                        INSERT INTO citrus_samples(
                            sample_id,user_id,session_id,project_id,variety,origin,event_time,growth_stage,maturity,
                            image_paths_json,disease_or_quality,processing_goal,metrics_json,solution,outcome,
                            source,confidence,keywords_json,status,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(sample_id) DO NOTHING
                        """,
                        (
                            candidate_id,
                            user_id,
                            session_id,
                            project_id,
                            fields["variety"],
                            fields["origin"],
                            fields["event_time"],
                            fields["growth_stage"],
                            fields["maturity"],
                            _safe_json(image_paths),
                            fields["disease_or_quality"],
                            fields["processing_goal"],
                            _safe_json(metrics),
                            fields["solution"],
                            fields["outcome"],
                            fields["source"],
                            confidence,
                            _safe_json(keywords),
                            "active",
                            now,
                            now,
                        ),
                    )
                    if connection.total_changes > changes_before:
                        sample_id = candidate_id
                        break

                    existing = connection.execute(
                        """
                        SELECT sample_id,user_id,project_id FROM citrus_samples
                        WHERE sample_id=?
                        """,
                        (candidate_id,),
                    ).fetchone()
                    if existing and existing["user_id"] == user_id and existing["project_id"] == project_id:
                        return {"sample_id": candidate_id, "deduplicated": True}

                    if collision_attempt == 0:
                        # A caller-supplied ID or a legacy content-only ID may
                        # belong to another tenant. Namespace it without exposing
                        # or reusing that tenant's record, then retry atomically.
                        scope_suffix = hashlib.sha256(
                            f"{user_id}\x1f{project_id}\x1f{candidate_id}".encode("utf-8")
                        ).hexdigest()[:12]
                        candidate_id = f"{candidate_id[:147]}_{scope_suffix}"
                        continue
                    raise MemoryIsolationError("历史样本 ID 与其他用户作用域冲突。")
        except sqlite3.Error as error:
            raise MemoryStorageError(f"保存历史样本失败：{error}") from error
        return {
            "sample_id": sample_id,
            "user_id": user_id,
            "session_id": session_id,
            "project_id": project_id,
            **fields,
            "image_paths": image_paths,
            "metrics": metrics,
            "confidence": confidence,
            "keywords": keywords,
            "created_at": now,
        }

    def retrieve_similar_samples(
        self,
        sample: dict[str, Any],
        top_k: int = MEMORY_SAMPLE_TOP_K,
    ) -> list[dict[str, Any]]:
        if not isinstance(sample, dict):
            raise MemoryValidationError("样本检索条件必须是字典。")
        user_id, project_id = self._scope(
            str(sample.get("user_id") or ""),
            str(sample.get("project_id") or ""),
        )
        query_text = _normalize_text(sample.get("query") or "")
        query_fields = {
            "variety": _normalize_text(sample.get("variety"), 160),
            "origin": _normalize_text(sample.get("origin"), 160),
            "disease_or_quality": _normalize_text(sample.get("disease_or_quality"), 1000),
            "processing_goal": _normalize_text(sample.get("processing_goal"), 1000),
            "maturity": _normalize_text(sample.get("maturity"), 160),
        }
        query_terms = _semantic_terms(" ".join([query_text, *query_fields.values()]))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM citrus_samples
                WHERE user_id=? AND project_id=? AND status='active'
                ORDER BY updated_at DESC LIMIT 500
                """,
                (user_id, project_id),
            ).fetchall()
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            candidate_text = " ".join(
                str(row[key] or "")
                for key in ["variety", "origin", "disease_or_quality", "processing_goal", "maturity", "solution", "outcome"]
            )
            semantic = _cosine_terms(query_terms, _semantic_terms(candidate_text))
            exact_scores = [
                1.0 if query_fields[key] and query_fields[key].lower() == str(row[key] or "").lower() else 0.0
                for key in ["variety", "origin", "maturity"]
            ]
            exact = sum(exact_scores) / max(sum(1 for key in ["variety", "origin", "maturity"] if query_fields[key]), 1)
            goal = _cosine_terms(
                _semantic_terms(query_fields["processing_goal"]),
                _semantic_terms(str(row["processing_goal"] or "")),
            )
            quality = _cosine_terms(
                _semantic_terms(query_fields["disease_or_quality"]),
                _semantic_terms(str(row["disease_or_quality"] or "")),
            )
            confidence = float(row["confidence"])
            recency = _recency_score(row["updated_at"], 180.0)
            if query_terms and max(semantic, exact, goal, quality) < 0.05:
                continue
            score = 0.34 * semantic + 0.20 * exact + 0.16 * goal + 0.12 * quality + 0.10 * confidence + 0.08 * recency
            if query_terms and score < MEMORY_MIN_RELEVANCE:
                continue
            item = dict(row)
            item["image_paths"] = _load_json(row["image_paths_json"], [])
            item["metrics"] = _load_json(row["metrics_json"], {})
            item["keywords"] = _load_json(row["keywords_json"], [])
            item["final_score"] = round(score, 4)
            for key in ["id", "image_paths_json", "metrics_json", "keywords_json"]:
                item.pop(key, None)
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:max(int(top_k), 1)]]

    @staticmethod
    def _format_working_memory(state: dict[str, Any]) -> str:
        visible = {
            key: state.get(key)
            for key in [
                "current_goal",
                "current_stage",
                "domain",
                "entities",
                "constraints",
                "confirmed_decisions",
                "completed_steps",
                "pending_steps",
                "required_inputs",
                "recent_tool_results",
                "referenced_files",
            ]
            if state.get(key) not in (None, "", [], {})
        }
        return _safe_json(visible)

    @staticmethod
    def _format_long_term(memories: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"[记忆:{item['memory_id']}] 类型={item['memory_type']}；来源={item['source']}；"
            f"重要性={item['importance']}；内容={item['content']}"
            for item in memories
        )

    @staticmethod
    def _format_samples(samples: list[dict[str, Any]]) -> str:
        lines = []
        for item in samples:
            lines.append(
                f"[样本:{item['sample_id']}] 品种={item.get('variety') or '未知'}；"
                f"产地={item.get('origin') or '未知'}；成熟度={item.get('maturity') or '未知'}；"
                f"问题/品质={item.get('disease_or_quality') or '未记录'}；"
                f"加工目标={item.get('processing_goal') or '未记录'}；"
                f"方案={item.get('solution') or '未记录'}；结果={item.get('outcome') or '未记录'}；"
                f"可信度={item.get('confidence')}；相似度={item.get('final_score')}"
            )
        return "\n".join(lines)

    def load_context(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
        query: str,
        *,
        recent_messages: list[dict[str, Any]] | None = None,
        current_tool_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        user_id, project_id = self._scope(user_id, project_id)
        self.ensure_session(user_id, session_id, project_id)
        self.summarize_history(
            session_id,
            user_id=user_id,
            project_id=project_id,
            force=False,
        )
        working = self.load_working_memory(user_id, session_id, project_id)
        summary_record = self._summary_record(user_id, session_id, project_id)
        memories = self.search_memories(
            query,
            {"user_id": user_id, "project_id": project_id},
            MEMORY_LONG_TERM_TOP_K,
        )
        entities = working.get("entities") or {}
        samples = self.retrieve_similar_samples(
            {
                "user_id": user_id,
                "project_id": project_id,
                "query": query,
                "variety": entities.get("variety") or entities.get("品种") or "",
                "origin": entities.get("origin") or entities.get("产地") or "",
                "disease_or_quality": entities.get("disease_or_quality") or "",
                "processing_goal": entities.get("processing_goal") or working.get("current_goal") or "",
                "maturity": entities.get("maturity") or "",
            },
            MEMORY_SAMPLE_TOP_K,
        )
        source_messages = recent_messages if recent_messages is not None else self.restore_session_messages(
            user_id, session_id, project_id
        )
        recent = select_recent_messages(source_messages, CONTEXT_TOKEN_BUDGETS["recent_dialog"])
        tool_results = [
            {
                "tool": _normalize_text(item.get("tool") or item.get("name"), 120),
                "result_id": _normalize_text(item.get("result_id") or item.get("tool_result_id"), 160),
                "summary": _normalize_text(item.get("summary") or item.get("observation"), MEMORY_TOOL_RESULT_CHARS),
            }
            for item in (current_tool_results or [])[-6:]
        ]
        with self._connect() as connection:
            session_row = connection.execute(
                "SELECT config_json FROM sessions WHERE session_id=? AND user_id=? AND project_id=?",
                (session_id, user_id, project_id),
            ).fetchone()
        session_config = _load_json(session_row["config_json"], {}) if session_row else {}
        sections = {
            "profile": truncate_to_tokens(
                _safe_json(
                    {
                        "user_id": user_id,
                        "project_id": project_id,
                        "session_id": session_id,
                        "config": session_config,
                    }
                ),
                CONTEXT_TOKEN_BUDGETS["profile"],
            ),
            "working_memory": truncate_to_tokens(
                self._format_working_memory(working),
                CONTEXT_TOKEN_BUDGETS["working_memory"],
            ),
            "summary": truncate_to_tokens(
                str(summary_record.get("summary") or ""),
                CONTEXT_TOKEN_BUDGETS["summary"],
            ),
            "long_term": truncate_to_tokens(
                self._format_long_term(memories),
                CONTEXT_TOKEN_BUDGETS["long_term"],
            ),
            "samples": truncate_to_tokens(
                self._format_samples(samples),
                CONTEXT_TOKEN_BUDGETS["samples"],
            ),
            "tool_results": truncate_to_tokens(
                _safe_json(tool_results),
                CONTEXT_TOKEN_BUDGETS["tool_results"],
            ),
        }
        token_usage = {name: estimate_tokens(value) for name, value in sections.items()}
        token_usage["recent_dialog"] = sum(estimate_tokens(item["content"]) for item in recent)
        token_usage["current_input"] = estimate_tokens(query)
        over_budget = {
            name: usage - int(CONTEXT_TOKEN_BUDGETS.get(name, usage))
            for name, usage in token_usage.items()
            if usage > int(CONTEXT_TOKEN_BUDGETS.get(name, usage))
        }
        return {
            "user_id": user_id,
            "session_id": session_id,
            "project_id": project_id,
            "working_memory": working,
            "summary": summary_record,
            "long_term_memories": memories,
            "similar_samples": samples,
            "recent_messages": recent,
            "tool_results": tool_results,
            "context_sections": sections,
            "token_budgets": dict(CONTEXT_TOKEN_BUDGETS),
            "token_usage": token_usage,
            "manifest": {
                "working_memory_version": working.get("version"),
                "summary_through_message_id": summary_record.get("summarized_through_id"),
                "memory_ids": [item["memory_id"] for item in memories],
                "sample_ids": [item["sample_id"] for item in samples],
                "recent_message_count": len(recent),
                "token_usage": token_usage,
                "over_budget": over_budget,
            },
        }

    def log_agent_run(self, run_record: dict[str, Any]) -> str:
        if not isinstance(run_record, dict):
            raise MemoryValidationError("审计记录必须是字典。")
        user_id, project_id = self._scope(
            str(run_record.get("user_id") or ""),
            str(run_record.get("project_id") or ""),
        )
        session_id = _normalize_text(run_record.get("session_id") or "", 160)
        if not session_id:
            raise MemoryValidationError("审计记录必须包含 session_id。")
        self.ensure_session(user_id, session_id, project_id)
        run_id = _normalize_text(run_record.get("run_id") or f"run_{uuid4().hex}", 160)
        sanitized = redact_sensitive(run_record)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs(
                    run_id,user_id,session_id,project_id,original_input,system_prompt_version,
                    model_name,context_manifest_json,retrieved_memory_ids_json,
                    retrieved_literature_ids_json,retrieved_sample_ids_json,tool_calls_json,
                    model_raw_output,final_output,state_updates_json,error,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    user_id,
                    session_id,
                    project_id,
                    _normalize_text(sanitized.get("original_input"), MEMORY_MAX_CONTENT_CHARS),
                    _normalize_text(sanitized.get("system_prompt_version") or "unknown", 160),
                    _normalize_text(sanitized.get("model_name"), 160),
                    _safe_json(sanitized.get("context_manifest") or {}),
                    _safe_json(sanitized.get("retrieved_memory_ids") or []),
                    _safe_json(sanitized.get("retrieved_literature_ids") or []),
                    _safe_json(sanitized.get("retrieved_sample_ids") or []),
                    _safe_json(sanitized.get("tool_calls") or []),
                    _normalize_text(sanitized.get("model_raw_output"), MEMORY_MAX_CONTENT_CHARS),
                    _normalize_message_content(sanitized.get("final_output")),
                    _safe_json(sanitized.get("state_updates") or {}),
                    _normalize_text(sanitized.get("error"), 3000),
                    utc_now(),
                ),
            )
        return run_id

    def get_agent_run(
        self,
        run_id: str,
        *,
        user_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any] | None:
        user_id, project_id = self._scope(user_id, project_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM agent_runs
                WHERE run_id=? AND user_id=? AND project_id=?
                """,
                (_normalize_text(run_id, 160), user_id, project_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in [
            "context_manifest_json",
            "retrieved_memory_ids_json",
            "retrieved_literature_ids_json",
            "retrieved_sample_ids_json",
            "tool_calls_json",
            "state_updates_json",
        ]:
            result[key.removesuffix("_json")] = _load_json(result.pop(key), {})
        return result

    def delete_memory(
        self,
        memory_id: str,
        *,
        user_id: str = "",
        project_id: str = "",
    ) -> bool:
        user_id, project_id = self._scope(user_id, project_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories SET status='inactive'
                WHERE memory_id=? AND user_id=? AND project_id=? AND status='active'
                """,
                (_normalize_text(memory_id, 160), user_id, project_id),
            )
        return cursor.rowcount > 0

    def clear_session(
        self,
        session_id: str,
        *,
        user_id: str = "",
        project_id: str = "",
        include_long_term: bool = False,
    ) -> None:
        user_id, project_id = self._scope(user_id, project_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT user_id,project_id FROM sessions WHERE session_id=?",
                (_normalize_text(session_id, 160),),
            ).fetchone()
            if row and (row["user_id"] != user_id or row["project_id"] != project_id):
                raise MemoryIsolationError("拒绝清理其他用户或项目的会话。")
            connection.execute(
                "DELETE FROM conversation_messages WHERE user_id=? AND project_id=? AND session_id=?",
                (user_id, project_id, session_id),
            )
            connection.execute(
                "DELETE FROM conversation_summaries WHERE user_id=? AND project_id=? AND session_id=?",
                (user_id, project_id, session_id),
            )
            connection.execute(
                "DELETE FROM working_memory WHERE user_id=? AND project_id=? AND session_id=?",
                (user_id, project_id, session_id),
            )
            if include_long_term:
                connection.execute(
                    "UPDATE memories SET status='inactive' WHERE user_id=? AND project_id=? AND session_id=?",
                    (user_id, project_id, session_id),
                )
                connection.execute(
                    "UPDATE citrus_samples SET status='inactive' WHERE user_id=? AND project_id=? AND session_id=?",
                    (user_id, project_id, session_id),
                )
            connection.execute(
                "UPDATE sessions SET status='cleared',updated_at=? WHERE session_id=?",
                (utc_now(), session_id),
            )


def build_context_messages(memory_context: dict[str, Any] | None) -> list[dict[str, str]]:
    if not memory_context:
        return []
    sections = memory_context.get("context_sections") or {}
    messages: list[dict[str, str]] = []
    labels = [
        ("profile", "当前用户和项目配置"),
        ("working_memory", "结构化工作记忆"),
        ("summary", "较早对话的增量摘要"),
        ("long_term", "检索到的相关长期记忆"),
        ("samples", "检索到的相似历史样本"),
        ("tool_results", "当前步骤必要的工具结果摘要"),
    ]
    for key, label in labels:
        content = str(sections.get(key) or "").strip()
        if content:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"{label}：\n{content}\n"
                        "只把这些内容作为有来源的上下文；当前用户输入优先，冲突时不得静默覆盖。"
                    ),
                }
            )
    return messages


def _safe_count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def build_memory_snapshot(batch: dict[str, Any], image_observation: str, product_filter: str) -> dict[str, Any]:
    """Compatibility snapshot used by the controlled batch workflow."""
    stats = database_stats(LITERATURE_DB_PATH)
    legacy_count = _safe_count_jsonl(LITERATURE_PATH)
    if stats["available"]:
        literature_chunk_count = int(stats["chunks"]) + legacy_count
        knowledge_sources = ["data/literature/literature.db", "data/literature/chunks.jsonl"]
    else:
        literature_chunk_count = legacy_count
        knowledge_sources = ["data/literature/chunks.jsonl"]
    return {
        "short_term": {
            "current_batch_id": batch.get("batch_id"),
            "origin": batch.get("origin"),
            "variety": batch.get("variety"),
            "customer_type": batch.get("customer_type"),
            "image_observation": image_observation or "未填写",
            "product_filter": product_filter,
            "recent_dialog_token_limit": MEMORY_RECENT_TOKEN_LIMIT,
        },
        "long_term": {
            "literature_document_count": int(stats["documents"]),
            "literature_chunk_count": literature_chunk_count,
            "indexed_categories": stats["categories"],
            "knowledge_sources": knowledge_sources,
            "memory_database": str(MEMORY_DB_PATH),
        },
    }
