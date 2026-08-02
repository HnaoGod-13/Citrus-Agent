from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "文献"
LEGACY_SOURCE_DIR = ROOT / "文献库"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "literature"
DEFAULT_CHUNK_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 180
MIN_CHUNK_CHARS = 260
BUILDER_VERSION = "3.1-section-sqlite"

CATEGORY_PRODUCT = {
    "陈皮": "陈皮",
    "橙汁": "橙汁",
    "果胶": "果胶",
    "精油": "精油",
    "种子": "种子",
    "副产物": "副产物",
}
CATEGORY_TOPIC = {
    "陈皮": "陈皮成分、陈化与质量控制",
    "橙汁": "果汁加工、品质与稳定性",
    "果胶": "果胶提取、改性与应用",
    "精油": "精油提取、组成与应用",
    "种子": "柑橘种子成分与高值利用",
    "副产物": "柑橘副产物综合利用",
}
CONCEPT_TERMS = {
    "陈皮": ["chenpi", "citri reticulatae", "chachi", "tangerine peel"],
    "橙汁": ["orange juice", "citrus juice", "juice", "nfc", "concentrate"],
    "果胶": ["pectin", "pectic", "galacturonic acid"],
    "精油": ["essential oil", "volatile oil", "limonene", "aroma"],
    "种子": ["citrus seed", "seed oil", "kernel"],
    "副产物": ["byproduct", "by-product", "pomace", "waste valorization", "residue"],
    "质量": ["quality", "authentication", "fingerprint", "quality control"],
    "安全": ["pesticide", "heavy metal", "microbial", "aflatoxin", "mycotoxin"],
    "加工": ["processing", "extraction", "drying", "fermentation", "storage"],
}
CONCEPT_TOKEN_BY_LABEL = {
    "陈皮": "chenpi",
    "橙汁": "juice",
    "果胶": "pectin",
    "精油": "essential_oil",
    "种子": "seed",
    "副产物": "byproduct",
    "质量": "quality",
    "安全": "safety",
    "加工": "processing",
}
SECTION_PATTERNS = [
    ("摘要", re.compile(r"^(abstract|summary|摘要)\s*[:：.]?$", re.I)),
    ("关键词", re.compile(r"^(key\s*words?|keywords?|关键词)\s*[:：.]?$", re.I)),
    ("引言", re.compile(r"^(\d+[.\s]*)?(introduction|background|引言|前言)\s*[:：.]?$", re.I)),
    (
        "材料与方法",
        re.compile(
            r"^(\d+(?:\.\d+)*[.\s]*)?(materials?\s+and\s+methods?|methods?|experimental(?:\s+section)?|材料与方法|实验方法)\s*[:：.]?$",
            re.I,
        ),
    ),
    ("结果", re.compile(r"^(\d+(?:\.\d+)*[.\s]*)?(results?|结果)\s*[:：.]?$", re.I)),
    (
        "结果与讨论",
        re.compile(r"^(\d+(?:\.\d+)*[.\s]*)?(results?\s+and\s+discussion|结果与讨论)\s*[:：.]?$", re.I),
    ),
    ("讨论", re.compile(r"^(\d+(?:\.\d+)*[.\s]*)?(discussion|讨论)\s*[:：.]?$", re.I)),
    (
        "结论",
        re.compile(r"^(\d+(?:\.\d+)*[.\s]*)?(conclusions?|concluding\s+remarks?|结论|结语)\s*[:：.]?$", re.I),
    ),
    ("参考文献", re.compile(r"^(references|bibliography|literature\s+cited|参考文献)\s*[:：.]?$", re.I)),
]


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    canonical_path: Path
    source_files: tuple[str, ...]
    categories: tuple[str, ...]
    fingerprint: str


def clean_text(text: str, preserve_lines: bool = True) -> str:
    text = str(text or "").replace("\x00", " ")
    text = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", text)
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    if preserve_lines:
        text = re.sub(r"\n[ ]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def _json_list(value: Iterable[str]) -> str:
    return json.dumps(list(value), ensure_ascii=False)


def _safe_document_key(path: Path, source_dir: Path) -> str:
    suffix = re.search(r"_([0-9a-fA-F]{12,64})$", path.stem)
    if suffix:
        return suffix.group(1).lower()
    relative = path.relative_to(source_dir).as_posix().lower()
    return hashlib.sha1(relative.encode("utf-8")).hexdigest()[:20]


def _category_for(path: Path, source_dir: Path) -> str:
    relative = path.relative_to(source_dir)
    return relative.parts[0] if len(relative.parts) > 1 else "未分类"


def discover_documents(source_dir: Path) -> list[SourceDocument]:
    supported = {".pdf", ".json"}
    grouped: dict[str, list[Path]] = {}
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in supported:
            grouped.setdefault(_safe_document_key(path, source_dir), []).append(path)

    documents: list[SourceDocument] = []
    for key, paths in grouped.items():
        canonical = min(paths, key=lambda item: (item.suffix.lower() != ".pdf", len(str(item)), str(item)))
        categories = tuple(sorted({_category_for(item, source_dir) for item in paths}))
        source_files = tuple(sorted(item.relative_to(source_dir).as_posix() for item in paths))
        stat = canonical.stat()
        fingerprint_material = f"{stat.st_size}:{stat.st_mtime_ns}:{'|'.join(categories)}:{BUILDER_VERSION}"
        fingerprint = hashlib.sha1(fingerprint_material.encode("utf-8")).hexdigest()
        documents.append(
            SourceDocument(
                document_id=key,
                canonical_path=canonical,
                source_files=source_files,
                categories=categories,
                fingerprint=fingerprint,
            )
        )
    return sorted(documents, key=lambda item: item.source_files[0])


def _metadata_from_filename(path: Path) -> tuple[str, str]:
    stem = re.sub(r"_[0-9a-fA-F]{12,64}$", "", path.stem)
    match = re.match(r"^((?:19|20)\d{2})_(.+)$", stem)
    year = match.group(1) if match else "未知"
    title = match.group(2) if match else stem
    title = clean_text(title.replace("_", " "), preserve_lines=False)
    return year, title


def _find_doi(text: str) -> str:
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}")


def _remove_repeated_margins(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(page_texts) < 4:
        return page_texts
    margin_counts: Counter[str] = Counter()
    per_page: list[list[str]] = []
    for page in page_texts:
        lines = [clean_text(line, preserve_lines=False) for line in page["text"].splitlines()]
        lines = [line for line in lines if line]
        per_page.append(lines)
        for line in [*lines[:3], *lines[-3:]]:
            if 3 <= len(line) <= 160:
                margin_counts[line] += 1
    threshold = max(3, int(len(page_texts) * 0.35))
    repeated = {line for line, count in margin_counts.items() if count >= threshold}
    cleaned: list[dict[str, Any]] = []
    for page, lines in zip(page_texts, per_page):
        kept = [line for line in lines if line not in repeated and not re.fullmatch(r"\d{1,4}", line)]
        cleaned.append({"page": page["page"], "text": clean_text("\n".join(kept))})
    return cleaned


def _truncate_reference_section(page_texts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    total = len(page_texts)
    for index, page in enumerate(page_texts):
        lines = page["text"].splitlines()
        cut_at: int | None = None
        if index >= max(1, int(total * 0.35)):
            for line_index, line in enumerate(lines):
                normalized = clean_text(line, preserve_lines=False)
                if any(section == "参考文献" and pattern.match(normalized) for section, pattern in SECTION_PATTERNS):
                    cut_at = line_index
                    break
        if cut_at is None:
            kept.append(page)
            continue
        before = clean_text("\n".join(lines[:cut_at]))
        if before:
            kept.append({"page": page["page"], "text": before})
        break
    return kept


def extract_pdf(document: SourceDocument) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required: python -m pip install pypdf") from exc

    raw_pages: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    page_count = 0
    try:
        reader = PdfReader(str(document.canonical_path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                pass
        metadata = dict(reader.metadata or {})
        page_count = len(reader.pages)
        for page_number, page in enumerate(reader.pages, 1):
            try:
                text = clean_text(page.extract_text() or "")
            except Exception:
                continue
            if text:
                raw_pages.append({"page": page_number, "text": text})
    except Exception:
        raw_pages = []

    # Structurally independent fallback for malformed fonts/xref tables.
    if not raw_pages:
        try:
            import fitz

            with fitz.open(document.canonical_path) as pdf:
                page_count = pdf.page_count
                metadata = {**metadata, **(pdf.metadata or {})}
                for page_number, page in enumerate(pdf, 1):
                    text = clean_text(page.get_text("text") or "")
                    if text:
                        raw_pages.append({"page": page_number, "text": text})
        except Exception:
            pass

    page_texts = _truncate_reference_section(_remove_repeated_margins(raw_pages))
    filename_year, filename_title = _metadata_from_filename(document.canonical_path)
    metadata_title = clean_text(str(metadata.get("/Title") or metadata.get("title") or ""), preserve_lines=False)
    title = filename_title if len(filename_title) >= 12 else metadata_title or filename_title
    lead_text = "\n".join(item["text"] for item in raw_pages[:3])
    year = filename_year
    if year == "未知":
        match = re.search(r"\b(?:19|20)\d{2}\b", lead_text)
        year = match.group(0) if match else "未知"
    extracted_chars = sum(len(item["text"]) for item in page_texts)
    extracted_pages = len(page_texts)
    chars_per_page = extracted_chars / max(page_count, 1)
    text_quality = "good" if chars_per_page >= 350 else "limited" if chars_per_page >= 80 else "ocr_required"
    return {
        "source_type": "pdf",
        "title": title,
        "year": year,
        "doi": _find_doi(lead_text),
        "publication": clean_text(str(metadata.get("/Subject") or metadata.get("subject") or ""), preserve_lines=False),
        "authors": [
            clean_text(str(metadata.get("/Author") or metadata.get("author") or ""), preserve_lines=False)
        ]
        if metadata.get("/Author") or metadata.get("author")
        else [],
        "page_count": page_count,
        "extracted_pages": extracted_pages,
        "extracted_chars": extracted_chars,
        "text_quality": text_quality,
        "page_texts": page_texts,
    }


def _flatten_json_text(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        if len(value.strip()) >= 40:
            output.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _flatten_json_text(item, output)
    elif isinstance(value, list):
        for item in value:
            _flatten_json_text(item, output)


def extract_json(document: SourceDocument) -> dict[str, Any]:
    data = json.loads(document.canonical_path.read_text(encoding="utf-8"))
    article = data.get("full-text-retrieval-response", data) if isinstance(data, dict) else {}
    core = article.get("coredata", {}) if isinstance(article, dict) else {}
    filename_year, filename_title = _metadata_from_filename(document.canonical_path)
    title = core.get("dc:title") or article.get("title") or filename_title
    doi = core.get("prism:doi") or article.get("doi") or ""
    publication = core.get("prism:publicationName") or article.get("publication") or ""
    parts: list[str] = []
    _flatten_json_text(article, parts)
    text = clean_text("\n\n".join(dict.fromkeys(parts)))
    year_match = re.search(r"\b(?:19|20)\d{2}\b", str(core.get("prism:coverDate") or ""))
    year = year_match.group(0) if year_match else filename_year
    return {
        "source_type": "json",
        "title": clean_text(str(title), preserve_lines=False),
        "year": year,
        "doi": str(doi),
        "publication": str(publication),
        "authors": [],
        "page_count": 1,
        "extracted_pages": 1 if text else 0,
        "extracted_chars": len(text),
        "text_quality": "good" if len(text) >= 500 else "limited",
        "page_texts": [{"page": 1, "text": text}] if text else [],
    }


def _detect_section(line: str) -> str | None:
    normalized = clean_text(line, preserve_lines=False).strip(" .-–—")
    if not normalized or len(normalized) > 90:
        return None
    for section, pattern in SECTION_PATTERNS:
        if pattern.match(normalized):
            return section
    return None


def _section_segments(text: str, current_section: str) -> tuple[list[tuple[str, str]], str]:
    segments: list[tuple[str, str]] = []
    buffer: list[str] = []
    section = current_section
    for line in text.splitlines():
        detected = _detect_section(line)
        if detected:
            if buffer:
                segments.append((section, clean_text("\n".join(buffer))))
                buffer = []
            section = detected
            if section == "参考文献":
                break
            continue
        buffer.append(line)
    if buffer and section != "参考文献":
        segments.append((section, clean_text("\n".join(buffer))))
    return [(name, body) for name, body in segments if body], section


def _split_long_unit(text: str, limit: int) -> list[str]:
    sentences = re.split(r"(?<=[。！？!?；;])|(?<=[.!?])\s+(?=[A-Z0-9])", text)
    pieces: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= limit:
            pieces.append(sentence)
        else:
            for start in range(0, len(sentence), limit):
                pieces.append(sentence[start : start + limit].strip())
    return pieces


def split_text(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n|(?<=\.)\s{2,}", text):
        paragraph = clean_text(paragraph, preserve_lines=False)
        if paragraph:
            units.extend(_split_long_unit(paragraph, chunk_chars))
    if not units:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for unit in units:
        separator = 1 if current else 0
        if current and current_length + separator + len(unit) > chunk_chars:
            chunk = clean_text(" ".join(current), preserve_lines=False)
            if chunk:
                chunks.append(chunk)
            overlap_units: list[str] = []
            overlap_length = 0
            for previous in reversed(current):
                if overlap_length + len(previous) > overlap_chars and overlap_units:
                    break
                overlap_units.insert(0, previous)
                overlap_length += len(previous) + 1
            current = overlap_units
            current_length = len(" ".join(current))
        current.append(unit)
        current_length += separator + len(unit)
    if current:
        chunks.append(clean_text(" ".join(current), preserve_lines=False))

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk) < MIN_CHUNK_CHARS and len(merged[-1]) + len(chunk) + 1 <= int(chunk_chars * 1.25):
            merged[-1] = f"{merged[-1]} {chunk}"
        elif len(chunk) >= 40:
            merged.append(chunk)
    return merged


def is_reference_like(text: str) -> bool:
    lower = text.lower()
    doi_count = len(re.findall(r"\b10\.\d{4,9}/", lower))
    years = len(re.findall(r"\b(?:19|20)\d{2}\b", lower))
    bracket_refs = len(re.findall(r"\[\d+\]", text))
    return doi_count >= 4 or (years >= 10 and bracket_refs >= 3)


def infer_product(categories: tuple[str, ...], text: str) -> str:
    for category in categories:
        if category in CATEGORY_PRODUCT:
            return CATEGORY_PRODUCT[category]
    lower = text.lower()
    if any(term in lower for term in ["chenpi", "citri reticulatae", "陈皮"]):
        return "陈皮"
    if "pectin" in lower or "果胶" in lower:
        return "果胶"
    if "essential oil" in lower or "精油" in lower:
        return "精油"
    if "seed" in lower or "种子" in lower:
        return "种子"
    return "柑橘"


def infer_topic(categories: tuple[str, ...], section: str, text: str) -> str:
    lower = text.lower()
    topic_map = [
        ("安全与污染物", ["pesticide", "mycotoxin", "aflatoxin", "heavy metal", "microbial", "农残", "污染"]),
        ("工艺优化", ["optimization", "extraction", "drying", "fermentation", "processing", "提取", "干燥", "发酵"]),
        ("组成与品质", ["composition", "quality", "flavonoid", "phenolic", "品质", "成分", "黄酮"]),
        ("功能活性研究", ["antioxidant", "anti-inflammatory", "bioactivity", "抗氧化", "抗炎", "活性"]),
        ("储藏与稳定性", ["storage", "shelf life", "stability", "储藏", "贮藏", "稳定性"]),
    ]
    for topic, terms in topic_map:
        if any(term in lower for term in terms):
            return f"{topic}·{section}"
    base = next((CATEGORY_TOPIC[item] for item in categories if item in CATEGORY_TOPIC), "柑橘产业研究")
    return f"{base}·{section}"


def keywords_for(categories: tuple[str, ...], text: str) -> list[str]:
    lower = text.lower()
    found = list(categories)
    for label, terms in CONCEPT_TERMS.items():
        if label in text or any(term in lower for term in terms):
            found.append(label)
    return list(dict.fromkeys(found))[:16]


def search_terms_for(text: str, keywords: list[str]) -> str:
    normalized = clean_text(text, preserve_lines=False).lower()
    english = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", normalized)
    chinese_tokens: list[str] = []
    for phrase in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if 2 <= len(phrase) <= 8:
            chinese_tokens.append(phrase)
        for size in (2, 3):
            if len(phrase) >= size:
                chinese_tokens.extend(phrase[index : index + size] for index in range(len(phrase) - size + 1))
    concept_tokens = [
        f"concept_{CONCEPT_TOKEN_BY_LABEL[label]}"
        for label in keywords
        if label in CONCEPT_TOKEN_BY_LABEL
    ]
    tokens = [*english, *chinese_tokens, *concept_tokens]
    return " ".join(tokens)


def article_to_chunks(
    document: SourceDocument,
    article: dict[str, Any],
    chunk_chars: int,
    overlap_chars: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_section = "正文"
    chunk_index = 0
    categories_text = "、".join(document.categories)
    for page in article["page_texts"]:
        segments, current_section = _section_segments(page["text"], current_section)
        for section, segment in segments:
            for chunk_text in split_text(segment, chunk_chars, overlap_chars):
                if is_reference_like(chunk_text):
                    continue
                chunk_index += 1
                keywords = keywords_for(document.categories, f"{article['title']} {chunk_text}")
                product = infer_product(document.categories, chunk_text)
                topic = infer_topic(document.categories, section, chunk_text)
                chunks.append(
                    {
                        "chunk_id": f"{document.document_id}_p{page['page']:04d}_{chunk_index:04d}",
                        "document_id": document.document_id,
                        "chunk_index": chunk_index,
                        "source_type": article["source_type"],
                        "source_file": document.source_files[0],
                        "source_files": _json_list(document.source_files),
                        "category": categories_text,
                        "title": article["title"],
                        "year": article["year"],
                        "doi": article["doi"],
                        "publication": article["publication"],
                        "page_start": page["page"],
                        "page_end": page["page"],
                        "section": section,
                        "product": product,
                        "topic": topic,
                        "keywords": "、".join(keywords),
                        "chunk_text": chunk_text,
                        "search_terms": search_terms_for(
                            f"{article['title']} {categories_text} {topic} {chunk_text}", keywords
                        ),
                        "char_count": len(chunk_text),
                    }
                )
    if not chunks:
        keywords = keywords_for(document.categories, article["title"])
        category = "、".join(document.categories)
        chunks.append(
            {
                "chunk_id": f"{document.document_id}_metadata",
                "document_id": document.document_id,
                "chunk_index": 1,
                "source_type": article["source_type"],
                "source_file": document.source_files[0],
                "source_files": _json_list(document.source_files),
                "category": category,
                "title": article["title"],
                "year": article["year"],
                "doi": article["doi"],
                "publication": article["publication"],
                "page_start": None,
                "page_end": None,
                "section": "题录（待OCR）",
                "product": infer_product(document.categories, article["title"]),
                "topic": infer_topic(document.categories, "题录", article["title"]),
                "keywords": "、".join(keywords),
                "chunk_text": f"题名：{article['title']}。该 PDF 暂未提取到可用正文，不能据此推断研究结果。",
                "search_terms": search_terms_for(f"{article['title']} {category}", keywords),
                "char_count": len(article["title"]),
            }
        )
    return chunks


def process_document(document: SourceDocument, chunk_chars: int, overlap_chars: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if document.canonical_path.suffix.lower() == ".pdf":
        article = extract_pdf(document)
    else:
        article = extract_json(document)
    chunks = article_to_chunks(document, article, chunk_chars, overlap_chars)
    return article, chunks


def initialize_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            builder_version TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_files TEXT NOT NULL,
            categories TEXT NOT NULL,
            title TEXT NOT NULL,
            year TEXT,
            doi TEXT,
            publication TEXT,
            authors TEXT,
            page_count INTEGER NOT NULL DEFAULT 0,
            extracted_pages INTEGER NOT NULL DEFAULT 0,
            extracted_chars INTEGER NOT NULL DEFAULT 0,
            text_quality TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE,
            document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_files TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            year TEXT,
            doi TEXT,
            publication TEXT,
            page_start INTEGER,
            page_end INTEGER,
            section TEXT,
            product TEXT,
            topic TEXT,
            keywords TEXT,
            chunk_text TEXT NOT NULL,
            search_terms TEXT NOT NULL,
            char_count INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_product ON chunks(product);
        CREATE INDEX IF NOT EXISTS idx_chunks_category ON chunks(category);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            title, category, topic, keywords, search_terms, chunk_text,
            content='chunks', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid,title,category,topic,keywords,search_terms,chunk_text)
            VALUES (new.id,new.title,new.category,new.topic,new.keywords,new.search_terms,new.chunk_text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts,rowid,title,category,topic,keywords,search_terms,chunk_text)
            VALUES('delete',old.id,old.title,old.category,old.topic,old.keywords,old.search_terms,old.chunk_text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts,rowid,title,category,topic,keywords,search_terms,chunk_text)
            VALUES('delete',old.id,old.title,old.category,old.topic,old.keywords,old.search_terms,old.chunk_text);
            INSERT INTO chunks_fts(rowid,title,category,topic,keywords,search_terms,chunk_text)
            VALUES (new.id,new.title,new.category,new.topic,new.keywords,new.search_terms,new.chunk_text);
        END;
        """
    )
    return connection


def _write_document(
    connection: sqlite3.Connection,
    document: SourceDocument,
    article: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    connection.execute("DELETE FROM documents WHERE document_id = ?", (document.document_id,))
    connection.execute(
        """
        INSERT INTO documents (
            document_id,fingerprint,builder_version,source_file,source_files,categories,title,year,doi,
            publication,authors,page_count,extracted_pages,extracted_chars,text_quality,chunk_count,indexed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            document.document_id,
            document.fingerprint,
            BUILDER_VERSION,
            document.source_files[0],
            _json_list(document.source_files),
            _json_list(document.categories),
            article["title"],
            article["year"],
            article["doi"],
            article["publication"],
            _json_list(article["authors"]),
            article["page_count"],
            article["extracted_pages"],
            article["extracted_chars"],
            article["text_quality"],
            len(chunks),
            now,
        ),
    )
    connection.executemany(
        """
        INSERT INTO chunks (
            chunk_id,document_id,chunk_index,source_type,source_file,source_files,category,title,year,doi,
            publication,page_start,page_end,section,product,topic,keywords,chunk_text,search_terms,char_count
        ) VALUES (
            :chunk_id,:document_id,:chunk_index,:source_type,:source_file,:source_files,:category,:title,:year,:doi,
            :publication,:page_start,:page_end,:section,:product,:topic,:keywords,:chunk_text,:search_terms,:char_count
        )
        """,
        chunks,
    )


def _database_counts(connection: sqlite3.Connection) -> dict[str, Any]:
    documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    ocr_required = connection.execute("SELECT COUNT(*) FROM documents WHERE text_quality='ocr_required'").fetchone()[0]
    limited = connection.execute("SELECT COUNT(*) FROM documents WHERE text_quality='limited'").fetchone()[0]
    categories = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT category, COUNT(DISTINCT document_id) FROM chunks GROUP BY category ORDER BY category"
        )
    }
    return {
        "documents": documents,
        "chunks": chunks,
        "ocr_required_documents": ocr_required,
        "limited_text_documents": limited,
        "chunk_categories": categories,
    }


def export_jsonl(connection: sqlite3.Connection, destination: Path) -> None:
    columns = [item[1] for item in connection.execute("PRAGMA table_info(chunks)") if item[1] != "id"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as output:
        query = f"SELECT {','.join(columns)} FROM chunks ORDER BY document_id, chunk_index"
        for row in connection.execute(query):
            item = dict(zip(columns, row))
            item["page"] = item.get("page_start")
            item["source"] = item.get("publication") or item.get("doi") or item.get("source_file")
            item["keywords"] = [value for value in str(item.get("keywords") or "").split("、") if value]
            output.write(json.dumps(item, ensure_ascii=False) + "\n")


def build_index(args: argparse.Namespace) -> dict[str, Any]:
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    database_path = output_dir / "literature.db"
    manifest_path = output_dir / "manifest.json"
    if not source_dir.exists():
        raise FileNotFoundError(f"Literature source directory does not exist: {source_dir}")
    if args.rebuild and database_path.exists():
        database_path.unlink()

    documents = discover_documents(source_dir)
    if args.limit:
        documents = documents[: args.limit]
    connection = initialize_database(database_path)
    existing = {
        row[0]: (row[1], row[2])
        for row in connection.execute("SELECT document_id, fingerprint, builder_version FROM documents")
    }
    discovered_ids = {item.document_id for item in documents}
    removed_ids = set(existing) - discovered_ids if not args.limit else set()
    for document_id in removed_ids:
        connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
    connection.commit()

    pending = [
        item
        for item in documents
        if existing.get(item.document_id) != (item.fingerprint, BUILDER_VERSION)
    ]
    skipped = len(documents) - len(pending)
    errors: list[dict[str, str]] = []
    indexed = 0
    started_at = datetime.now()
    print(
        f"Discovered {len(documents)} unique documents; "
        f"pending={len(pending)}, unchanged={skipped}, removed={len(removed_ids)}.",
        flush=True,
    )

    # PDF text extraction is CPU-heavy in pypdf. Processes avoid the GIL and keep
    # SQLite writes in this parent process, so workers never contend on the database.
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(process_document, document, args.chunk_chars, args.overlap_chars): document
            for document in pending
        }
        for completed, future in enumerate(as_completed(future_map), 1):
            document = future_map[future]
            try:
                article, chunks = future.result()
                if not chunks:
                    raise ValueError(f"No usable text chunks (text_quality={article.get('text_quality')})")
                with connection:
                    _write_document(connection, document, article, chunks)
                indexed += 1
            except Exception as exc:
                errors.append({"file": document.source_files[0], "error": f"{type(exc).__name__}: {exc}"})
            if completed == 1 or completed % 20 == 0 or completed == len(pending):
                print(
                    f"[{completed}/{len(pending)}] indexed={indexed}, errors={len(errors)}, "
                    f"latest={document.source_files[0]}",
                    flush=True,
                )

    counts = _database_counts(connection)
    if args.export_jsonl:
        export_jsonl(connection, output_dir / "chunks_v3.jsonl")
    connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
    connection.commit()
    connection.close()

    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "duration_seconds": round((datetime.now() - started_at).total_seconds(), 2),
        "builder_version": BUILDER_VERSION,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "database": str(database_path),
        "source_files": sum(len(item.source_files) for item in documents),
        "unique_documents": len(documents),
        "duplicate_source_files": sum(len(item.source_files) for item in documents) - len(documents),
        "indexed_or_updated": indexed,
        "unchanged": skipped,
        "removed": len(removed_ids),
        **counts,
        "errors": errors,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Database ready: {counts['documents']} documents, {counts['chunks']} chunks, "
        f"errors={len(errors)}.\nDatabase: {database_path}\nManifest: {manifest_path}",
        flush=True,
    )
    return manifest


def parse_args() -> argparse.Namespace:
    default_source = DEFAULT_SOURCE_DIR if DEFAULT_SOURCE_DIR.exists() else LEGACY_SOURCE_DIR
    parser = argparse.ArgumentParser(description="Build an incremental, section-aware SQLite FTS literature index.")
    parser.add_argument("--source-dir", type=Path, default=default_source)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--overlap-chars", type=int, default=DEFAULT_OVERLAP_CHARS)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="Index only the first N unique documents (testing only).")
    parser.add_argument("--rebuild", action="store_true", help="Delete the existing SQLite index before building.")
    parser.add_argument("--export-jsonl", action="store_true", help="Also export the new index to chunks_v3.jsonl.")
    return parser.parse_args()


def main() -> None:
    build_index(parse_args())


if __name__ == "__main__":
    main()
