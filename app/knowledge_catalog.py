"""Build the lightweight SQLite catalog used by the Knowledge browser."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any


CATALOG_SCHEMA_VERSION = 1
DIRECT_CITRUS_TITLE_MARKERS = (
    "citrus",
    "orange",
    "mandarin",
    "tangerine",
    "lemon",
    "lime",
    "grapefruit",
    "pomelo",
    "clementine",
    "satsuma",
    "kinnow",
    "bergamot",
    "kumquat",
    "citron",
    "citri reticulatae",
    "chenpi",
    "柑橘",
    "橙",
    "柚",
    "柠檬",
    "桔",
    "橘",
)
OFF_DOMAIN_TITLE_MARKERS = (
    "near field communication",
    "nfc-enabled",
    "nfc-a4wp",
    "dc-nfc",
    "e-wallet",
    "public surveillance",
    "wireless networks",
    "internet of things",
    "wearable electronic",
    "connected clothing",
    "remote photoactivation",
)
OFF_DOMAIN_TITLE_PATTERN = re.compile(
    "|".join(re.escape(marker) for marker in OFF_DOMAIN_TITLE_MARKERS),
    flags=re.IGNORECASE,
)


CATALOG_SCHEMA = """
CREATE TABLE catalog_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    year TEXT,
    categories TEXT,
    publication TEXT,
    doi TEXT,
    source_file TEXT,
    chunk_count INTEGER,
    text_quality TEXT,
    is_off_domain INTEGER NOT NULL,
    relevance_rank INTEGER NOT NULL,
    year_sort INTEGER NOT NULL
);
CREATE TABLE document_categories (
    document_id TEXT NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY (document_id, category)
) WITHOUT ROWID;
CREATE TABLE category_counts (
    category TEXT PRIMARY KEY,
    document_count INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX documents_browse_order
    ON documents(is_off_domain, relevance_rank, year_sort DESC, title COLLATE NOCASE);
CREATE INDEX document_categories_lookup
    ON document_categories(category, document_id);
"""


def is_off_domain_title(value: Any) -> bool:
    return bool(OFF_DOMAIN_TITLE_PATTERN.search(str(value or "")))


def relevance_rank(value: Any) -> int:
    title = str(value or "").casefold()
    return 0 if any(marker in title for marker in DIRECT_CITRUS_TITLE_MARKERS) else 1


def year_sort_value(value: Any) -> int:
    text = str(value or "").strip()
    return int(text) if re.fullmatch(r"\d{4}", text) else 0


def json_categories(value: Any) -> list[str]:
    try:
        decoded = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return list(dict.fromkeys(str(item or "").strip() for item in decoded if str(item or "").strip()))


def _package_identity(source_path: Path, destination_path: Path) -> dict[str, Any]:
    candidates = (
        source_path.parent / "package" / "manifest.json",
        destination_path.parent / "package" / "manifest.json",
    )
    for manifest_path in dict.fromkeys(candidates):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if int(manifest.get("original_size") or 0) == source_path.stat().st_size:
            return manifest
    return {}


def build_catalog(source_path: Path, destination_path: Path) -> dict[str, Any]:
    """Create a deterministic, metadata-only catalog from the full RAG database."""
    source = Path(source_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.part")
    temporary.unlink(missing_ok=True)
    source_connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    source_connection.row_factory = sqlite3.Row
    output_connection = sqlite3.connect(temporary)
    category_counts: Counter[str] = Counter()
    visible_document_ids: list[str] = []
    document_rows: list[tuple[Any, ...]] = []
    document_categories: list[tuple[str, str]] = []
    try:
        output_connection.executescript(CATALOG_SCHEMA)
        rows = source_connection.execute(
            """
            SELECT document_id, title, authors, year, categories, publication,
                   doi, source_file, chunk_count, text_quality
            FROM documents
            ORDER BY document_id
            """
        )
        for row in rows:
            document_id = str(row["document_id"])
            off_domain = int(is_off_domain_title(row["title"]))
            document_rows.append(
                (
                    document_id,
                    row["title"],
                    row["authors"],
                    row["year"],
                    row["categories"],
                    row["publication"],
                    row["doi"],
                    row["source_file"],
                    row["chunk_count"],
                    row["text_quality"],
                    off_domain,
                    relevance_rank(row["title"]),
                    year_sort_value(row["year"]),
                )
            )
            categories = json_categories(row["categories"])
            document_categories.extend((document_id, category) for category in categories)
            if not off_domain:
                visible_document_ids.append(document_id)
                category_counts.update(categories)

        output_connection.executemany(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            document_rows,
        )
        output_connection.executemany(
            "INSERT INTO document_categories VALUES (?, ?)",
            document_categories,
        )
        output_connection.executemany(
            "INSERT INTO category_counts VALUES (?, ?)",
            sorted(category_counts.items()),
        )

        source_documents = len(document_rows)
        source_chunks = int(source_connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        visible_chunks = 0
        if visible_document_ids:
            source_connection.execute("CREATE TEMP TABLE visible_documents(document_id TEXT PRIMARY KEY)")
            source_connection.executemany(
                "INSERT INTO visible_documents VALUES (?)",
                ((document_id,) for document_id in visible_document_ids),
            )
            visible_chunks = int(
                source_connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM chunks c
                    JOIN visible_documents v ON v.document_id = c.document_id
                    """
                ).fetchone()[0]
            )

        package_identity = _package_identity(source, destination)
        built_at = str(package_identity.get("built_at") or "") or datetime.fromtimestamp(
            source.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()
        meta = {
            "schema_version": str(CATALOG_SCHEMA_VERSION),
            "built_at": built_at,
            "source_sha256": str(package_identity.get("sha256") or ""),
            "source_documents": str(source_documents),
            "source_chunks": str(source_chunks),
            "visible_documents": str(len(visible_document_ids)),
            "visible_chunks": str(visible_chunks),
        }
        output_connection.executemany(
            "INSERT INTO catalog_meta VALUES (?, ?)",
            sorted(meta.items()),
        )
        output_connection.commit()
        output_connection.execute("ANALYZE")
        output_connection.commit()
        output_connection.execute("VACUUM")
    except Exception:
        output_connection.close()
        source_connection.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        output_connection.close()
        source_connection.close()
        os.replace(temporary, destination)
        return {
            "path": str(destination),
            "size": destination.stat().st_size,
            **{key: int(value) if value.isdigit() else value for key, value in meta.items()},
        }
