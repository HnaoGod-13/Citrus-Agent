from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4


TaskScope = tuple[str, str, str]
ProgressCallback = Callable[[str], None]
TaskTarget = Callable[[ProgressCallback], Any]
_TERMINAL_STATES = {"succeeded", "failed"}


@dataclass(frozen=True)
class TaskSnapshot:
    job_id: str
    scope: TaskScope
    status: str
    progress: str
    error: str
    created_at: float
    updated_at: float

    @property
    def done(self) -> bool:
        return self.status in _TERMINAL_STATES


@dataclass(frozen=True)
class TaskResultClaim:
    job_id: str
    token: str
    result: Any
    error: str


@dataclass
class _TaskRecord:
    job_id: str
    scope: TaskScope
    status: str
    progress: str
    error: str
    created_at: float
    updated_at: float
    result: Any = None
    harvested: bool = False
    harvest_token: str = ""
    harvest_lease_until: float = 0.0


class TaskRunner:
    """Run Agent turns independently from Streamlit script reruns."""

    def __init__(self, max_workers: int | None = None) -> None:
        configured = max_workers or int(os.getenv("CITRUS_AGENT_WORKERS", "2"))
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(configured, 4)),
            thread_name_prefix="citrus-agent",
        )
        self._lock = threading.RLock()
        self._tasks: dict[str, _TaskRecord] = {}

    def submit(self, job_id: str, scope: TaskScope, target: TaskTarget) -> str:
        normalized_id = str(job_id or "").strip()
        if not normalized_id:
            raise ValueError("job_id cannot be empty")
        normalized_scope: TaskScope = tuple(str(item or "").strip() for item in scope)  # type: ignore[assignment]
        if not all(normalized_scope):
            raise ValueError("task scope must contain user, project, and session identifiers")

        now = time.time()
        with self._lock:
            existing = self._tasks.get(normalized_id)
            if existing is not None:
                return existing.job_id
            for record in self._tasks.values():
                if record.scope == normalized_scope and record.status not in _TERMINAL_STATES:
                    raise RuntimeError("该对话已有 Agent 任务正在运行。")
            self._discard_expired_locked(now)
            self._tasks[normalized_id] = _TaskRecord(
                job_id=normalized_id,
                scope=normalized_scope,
                status="queued",
                progress="正在启动 Agent 任务",
                error="",
                created_at=now,
                updated_at=now,
            )
        try:
            self._executor.submit(self._execute, normalized_id, target)
        except Exception:
            with self._lock:
                self._tasks.pop(normalized_id, None)
            raise
        return normalized_id

    def _execute(self, job_id: str, target: TaskTarget) -> None:
        self._set_state(job_id, status="running")
        try:
            result = target(lambda message: self.update_progress(job_id, message))
        except Exception as error:
            self._set_state(
                job_id,
                status="failed",
                error=f"{type(error).__name__}: {error}",
            )
            return
        with self._lock:
            record = self._tasks.get(job_id)
            if record is None:
                return
            record.result = result
            record.status = "succeeded"
            record.updated_at = time.time()

    def _set_state(self, job_id: str, *, status: str, error: str = "") -> None:
        with self._lock:
            record = self._tasks.get(job_id)
            if record is None:
                return
            record.status = status
            record.error = error
            record.updated_at = time.time()

    def update_progress(self, job_id: str, message: str) -> None:
        normalized = str(message or "").strip()
        if not normalized:
            return
        with self._lock:
            record = self._tasks.get(job_id)
            if record is None or record.status in _TERMINAL_STATES:
                return
            record.progress = normalized[:500]
            record.updated_at = time.time()

    def snapshot(self, job_id: str) -> TaskSnapshot | None:
        with self._lock:
            record = self._tasks.get(str(job_id or ""))
            if record is None:
                return None
            return TaskSnapshot(
                job_id=record.job_id,
                scope=record.scope,
                status=record.status,
                progress=record.progress,
                error=record.error,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    def active_job(self, scope: TaskScope) -> str:
        normalized_scope: TaskScope = tuple(str(item or "").strip() for item in scope)  # type: ignore[assignment]
        with self._lock:
            matches = [
                record
                for record in self._tasks.values()
                if record.scope == normalized_scope and record.status not in _TERMINAL_STATES
            ]
            if not matches:
                return ""
            return max(matches, key=lambda item: item.created_at).job_id

    def result(self, job_id: str) -> Any:
        with self._lock:
            record = self._tasks.get(str(job_id or ""))
            if record is None:
                raise KeyError(job_id)
            if record.status == "failed":
                raise RuntimeError(record.error or "Agent task failed")
            if record.status != "succeeded":
                raise RuntimeError("Agent task is still running")
            return record.result

    def claim_result(
        self,
        job_id: str,
        *,
        lease_seconds: float = 15.0,
    ) -> TaskResultClaim | None:
        """Lease a terminal result so interrupted harvests can be retried."""
        with self._lock:
            record = self._tasks.get(str(job_id or ""))
            if record is None:
                raise KeyError(job_id)
            if record.status not in _TERMINAL_STATES:
                raise RuntimeError("Agent task is still running")
            if record.harvested:
                return None
            now = time.monotonic()
            if record.harvest_token and record.harvest_lease_until > now:
                return None
            token = f"claim_{uuid4().hex}"
            record.harvest_token = token
            record.harvest_lease_until = now + max(float(lease_seconds), 0.1)
            return TaskResultClaim(
                job_id=record.job_id,
                token=token,
                result=record.result,
                error=record.error if record.status == "failed" else "",
            )

    def acknowledge_result(self, job_id: str, token: str) -> bool:
        with self._lock:
            record = self._tasks.get(str(job_id or ""))
            if record is None or record.harvested or record.harvest_token != str(token or ""):
                return False
            record.harvested = True
            record.harvest_token = ""
            record.harvest_lease_until = 0.0
            return True

    def discard(self, job_id: str) -> None:
        with self._lock:
            record = self._tasks.get(str(job_id or ""))
            if record is not None and record.status in _TERMINAL_STATES:
                self._tasks.pop(record.job_id, None)

    def _discard_expired_locked(self, now: float) -> None:
        cutoff = now - 3600
        expired = [
            job_id
            for job_id, record in self._tasks.items()
            if record.status in _TERMINAL_STATES and record.updated_at < cutoff
        ]
        for job_id in expired:
            self._tasks.pop(job_id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
