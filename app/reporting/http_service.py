"""Dependency-free HTTP adapter for the reusable project report service.

Run from the ``streamlit-deploy`` directory with::

    python -m app.reporting.http_service

The adapter deliberately contains no Streamlit code. Other applications can
POST the envelope documented by the project-report-writing skill and receive
the same Markdown, sources, and editable Word output as the workbench.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .service import generate_project_report


MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 12_000


class ReportRequestError(ValueError):
    """A client supplied an invalid report request."""


def _text(value: Any, *, limit: int = MAX_TEXT_CHARS) -> str:
    return str(value or "").strip()[:limit]


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ReportRequestError(f"{name} must be an object")
    return value


def _sources(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ReportRequestError("sources must be an array")
    cleaned: list[dict[str, Any]] = []
    for item in value[:32]:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "title": _text(item.get("title") or item.get("document_title"), limit=600),
            "url": _text(item.get("url") or item.get("source"), limit=2000),
            "snippet": _text(item.get("snippet") or item.get("abstract") or item.get("content")),
            "source_type": _text(item.get("source_type") or "local", limit=80),
        })
    return [item for item in cleaned if item["title"] or item["url"] or item["snippet"]]


def build_generate_kwargs(payload: dict[str, Any], *, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Map the public envelope to ``generate_project_report`` arguments."""
    if not isinstance(payload, dict):
        raise ReportRequestError("request body must be a JSON object")

    project = _mapping(payload.get("project"), "project")
    facts = _mapping(payload.get("facts"), "facts")
    route = _mapping(payload.get("route"), "route")
    process = _mapping(payload.get("process"), "process")
    report_profile = _mapping(payload.get("report_profile"), "report_profile")
    sources = _sources(payload.get("sources"))
    if not facts:
        raise ReportRequestError("facts must contain at least one project fact")

    # The core service receives normalized facts and selected route/process
    # data, while local sources are kept in the same evidence shape as the
    # workbench. Internal request metadata never enters the writing prompt.
    analysis = {
        "cleaning": {"normalized": facts},
        "recommended_route": route,
        "routes": route.get("alternatives") or [],
        "processing_plan": process,
        "report_enrichment": {"evidence": sources},
        "pipeline_version": "report-service-v1",
    }
    profile = {**project, **report_profile}
    title = _text(profile.get("title") or project.get("name"), limit=400)
    if title:
        profile["title"] = title
    task_id = _text(payload.get("task_id") or payload.get("request_id") or "task_" + uuid4().hex[:20], limit=200)
    record_id = _text(payload.get("record_id") or "record_" + uuid4().hex[:20], limit=200)
    kwargs: dict[str, Any] = {
        "task_id": task_id,
        "record_id": record_id,
        "document": {"report_enrichment": {"evidence": sources}},
        "analysis": analysis,
        "profile": profile,
    }
    if output_dir is not None:
        kwargs["output_dir"] = output_dir
    return kwargs


def generate_from_payload(payload: dict[str, Any], *, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Generate a report from the public JSON envelope."""
    return generate_project_report(**build_generate_kwargs(payload, output_dir=output_dir))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ReportRequestHandler(BaseHTTPRequestHandler):
    """Small HTTP surface suitable for a separate report-service process."""

    server_version = "ProjectReportService/1.0"

    def _send_json(self, status: int, body: Any) -> None:
        raw = _json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", os.getenv("REPORT_SERVICE_CORS", "*"))
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        expected = os.getenv("REPORT_SERVICE_API_KEY", "").strip()
        if not expected:
            return True
        provided = self.headers.get("X-Report-Service-Key", "").strip()
        if not provided:
            authorization = self.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
        return provided == expected

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send_json(200, {"status": "ok", "service": "project-report"})
            return
        self._send_json(404, {"status": "error", "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path != "/report/generate":
            self._send_json(404, {"status": "error", "message": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"status": "error", "message": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"status": "error", "message": "request body must be between 1 byte and 2 MB"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            output_dir = os.getenv("REPORT_SERVICE_OUTPUT_DIR", "").strip() or None
            result = generate_from_payload(payload, output_dir=output_dir)
        except (UnicodeDecodeError, json.JSONDecodeError, ReportRequestError) as exc:
            self._send_json(400, {"status": "error", "message": str(exc)})
            return
        except Exception as exc:  # keep provider errors in a JSON API response
            self.log_error("report generation failed: %s", exc)
            self._send_json(502, {"status": "error", "message": "report generation failed", "detail": type(exc).__name__})
            return
        self._send_json(200, result)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep service logs useful without echoing report contents or sources.
        super().log_message(format, *args)


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or os.getenv("REPORT_SERVICE_HOST", "0.0.0.0")
    port = port or int(os.getenv("REPORT_SERVICE_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), ReportRequestHandler)
    print(f"Project report service listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()


__all__ = ["ReportRequestError", "build_generate_kwargs", "generate_from_payload", "serve"]
