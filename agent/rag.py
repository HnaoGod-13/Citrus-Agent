from __future__ import annotations

import json
import hashlib
import math
import os
import re
import sqlite3
import tempfile
import threading
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

from .processing_config import (
    PROCESS_DEEP_MAX_DATABASE_CANDIDATES,
    PROCESS_DEEP_MAX_FTS_ROWS,
    PROCESS_DEEP_MAX_PER_QUERY,
    PROCESS_DEEP_NEIGHBOR_DOCUMENT_LIMIT,
    PROCESS_DEEP_NEIGHBOR_LIMIT,
    PROCESS_DEEP_NEIGHBOR_PER_HIT,
    PROCESS_DEEP_NEIGHBOR_RADIUS,
    PROCESS_DEEP_SQL_TIMEOUT_SECONDS,
)


ROOT = Path(__file__).resolve().parents[1]
LITERATURE_DIR = ROOT / "data" / "literature"
SOURCE_LITERATURE_DB_PATH = LITERATURE_DIR / "literature.db"
LITERATURE_PACKAGE_DIR = LITERATURE_DIR / "package"
RUNTIME_CACHE_DIR = Path(
    os.getenv("CITRUS_AGENT_CACHE_DIR", str(Path(tempfile.gettempdir()) / "citrus-agent"))
)
LITERATURE_DB_PATH = (
    SOURCE_LITERATURE_DB_PATH
    if SOURCE_LITERATURE_DB_PATH.exists()
    else RUNTIME_CACHE_DIR / "literature.db"
)
LITERATURE_PATH = LITERATURE_DIR / "chunks.jsonl"
DEMO_PATH = ROOT / "data" / "clean_chunks" / "sample_chunks.jsonl"
SUPPLEMENTAL_PATHS = [LITERATURE_DIR / "citrus_processing_tree_chunks.jsonl"]
DATA_PATH = LITERATURE_PATH if LITERATURE_PATH.exists() else DEMO_PATH

QUERY_EXPANSIONS = {
    "陈皮": ["chenpi", "citri reticulatae", "dried tangerine peel", "tangerine peel", "chachi"],
    "广陈皮": ["guang chenpi", "xinhui chenpi", "chachiensis"],
    "茶枝柑": ["chachi", "citrus reticulata chachiensis"],
    "柑橘": ["citrus", "mandarin", "orange", "tangerine"],
    "整果": ["whole citrus", "whole fruit"],
    "果肉": ["citrus pulp", "fruit pulp", "juice sac", "juice vesicle"],
    "果皮": ["citrus peel", "orange peel", "pericarp", "flavedo", "albedo"],
    "副产物": ["byproduct", "by-product", "pomace", "residue", "waste valorization"],
    "橙汁": ["orange juice", "citrus juice", "not from concentrate", "nfc"],
    "果汁": ["juice", "nfc", "concentrate", "pasteurization"],
    "浓缩汁": ["concentrated juice", "vacuum concentration", "evaporation"],
    "果醋": ["vinegar", "acetic fermentation"],
    "果酒": ["fruit wine", "alcoholic fermentation"],
    "罐头": ["canned", "canning", "thermal processing"],
    "蜜饯": ["preserve", "candied", "osmotic dehydration"],
    "精油": ["essential oil", "volatile oil", "limonene", "cold pressing", "hydrodistillation"],
    "香精": ["flavor", "flavour", "aroma", "essential oil"],
    "果胶": ["pectin", "pectic", "galacturonic acid", "degree of esterification"],
    "黄酮": ["flavonoid", "hesperidin", "nobiletin", "tangeretin", "polymethoxyflavone"],
    "色素": ["pigment", "carotenoid"],
    "籽油": ["seed oil", "citrus seed oil"],
    "橘核": ["citrus seed", "kernel"],
    "种子": ["citrus seed", "seed oil", "kernel"],
    "饲料": ["animal feed", "feed", "silage"],
    "有机肥": ["organic fertilizer", "compost", "soil amendment"],
    "陈化": ["aging", "ageing", "storage", "maturation"],
    "仓储": ["storage", "stored", "packaging", "shelf life"],
    "贮藏": ["storage", "stored", "shelf life"],
    "多糖": ["polysaccharide", "polysaccharides"],
    "干燥": ["drying", "dried", "freeze drying", "hot air drying"],
    "热风干燥": ["hot air drying", "convective drying"],
    "真空干燥": ["vacuum drying", "vacuum dehydration"],
    "冻干": ["freeze drying", "freeze-drying", "lyophilization"],
    "酶解": ["enzymatic treatment", "enzyme-assisted", "pectinase", "cellulase"],
    "澄清": ["clarification", "fining", "flotation", "depectinization"],
    "过滤": ["filtration", "microfiltration", "ultrafiltration", "centrifugation"],
    "均质": ["homogenization", "homogenisation", "high pressure homogenization"],
    "脱气": ["deaeration", "de-aeration", "vacuum deaeration"],
    "杀菌": ["pasteurization", "thermal treatment", "sterilization", "microbial inactivation"],
    "护色": ["anti-browning", "color protection", "ascorbic acid"],
    "包装": ["packaging", "filling", "bottling", "aseptic filling"],
    "料液比": ["solid liquid ratio", "material liquid ratio"],
    "发酵": ["fermentation", "microbial", "starter culture"],
    "质控": ["quality", "authentication", "fingerprint", "quality control"],
    "农残": ["pesticide residue", "pesticide"],
    "重金属": ["heavy metal", "lead", "cadmium", "arsenic", "mercury"],
    "霉变": ["mildew", "mold", "fungal", "mycotoxin"],
    "黄曲霉": ["aflatoxin", "aspergillus"],
    "抗氧化": ["antioxidant", "radical scavenging"],
    "抗炎": ["anti-inflammatory", "inflammation"],
}

SEMANTIC_CONCEPTS = {
    "chenpi": ["陈皮", "广陈皮", "新会", "茶枝柑", "chenpi", "citri reticulatae", "chachi"],
    "citrus": ["柑橘", "柑", "橘", "橙", "citrus", "mandarin", "tangerine", "orange"],
    "whole_fruit": ["整果", "whole citrus", "whole fruit", "candied citrus"],
    "pulp": ["果肉", "砂囊", "果粒", "citrus pulp", "juice sac", "juice vesicle"],
    "peel": ["果皮", "皮渣", "citrus peel", "orange peel", "pericarp", "flavedo", "albedo"],
    "juice": ["果汁", "橙汁", "nfc", "浓缩汁", "orange juice", "citrus juice", "concentrated juice"],
    "fermentation": ["果醋", "果酒", "发酵", "vinegar", "fruit wine", "fermentation"],
    "essential_oil": ["精油", "挥发油", "香气", "essential oil", "volatile oil", "limonene", "aroma"],
    "pectin": ["果胶", "膳食纤维", "pectin", "pectic", "galacturonic", "dietary fiber"],
    "flavonoid": ["黄酮", "多甲氧基黄酮", "flavonoid", "hesperidin", "nobiletin", "tangeretin"],
    "seed": ["种子", "籽油", "橘核", "citrus seed", "seed oil", "kernel"],
    "byproduct": ["副产物", "饲料", "有机肥", "果渣", "pomace", "byproduct", "waste valorization", "compost"],
    "quality": ["质控", "质量", "指纹图谱", "鉴别", "quality", "authentication", "fingerprint", "marker"],
    "safety": ["农残", "重金属", "微生物", "黄曲霉", "霉变", "pesticide", "heavy metal", "aflatoxin", "mycotoxin"],
    "storage": ["水分", "仓储", "贮藏", "陈化", "干燥", "moisture", "water activity", "storage", "aging", "drying"],
    "unit_operation": ["酶解", "澄清", "过滤", "均质", "脱气", "杀菌", "enzyme", "clarification", "filtration", "homogenization", "deaeration", "pasteurization"],
    "process_parameter": ["温度", "时间", "压力", "转速", "流量", "用量", "料液比", "temperature", "time", "pressure", "speed", "flow", "dosage", "ratio"],
}

CITRUS_PRODUCTS = {"柑橘", "陈皮", "橙汁", "整果", "果肉", "果皮", "果胶", "精油", "种子", "副产物"}
RETRIEVAL_FIELDS = ["title", "category", "section", "topic", "keywords", "chunk_text", "doi", "publication", "source"]
TITLE_WEIGHT_FIELDS = ["title", "category", "topic", "keywords"]
ENGLISH_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "that", "this", "using", "use", "its", "are", "was", "were",
    "study", "effect", "effects", "based", "analysis", "agent", "processing", "quality",
}
_DB_BUILD_LOCK = threading.Lock()


RetrievalMode = Literal["quick", "deep"]


def _normalize_retrieval_mode(retrieval_mode: str) -> RetrievalMode:
    normalized = str(retrieval_mode or "quick").strip().lower()
    if normalized not in {"quick", "deep"}:
        raise ValueError("retrieval_mode must be 'quick' or 'deep'")
    return normalized  # type: ignore[return-value]


def is_pending_ocr_entry(item: dict[str, Any]) -> bool:
    section = str(item.get("section") or "").strip().lower()
    text = str(item.get("chunk_text") or "").strip().lower()
    return "待ocr" in section or (text.startswith("题名：") and "未提取到可用正文" in text)


def _new_retrieval_stats(mode: RetrievalMode, query_count: int, top_k: int) -> dict[str, Any]:
    return {
        "retrieval_mode": mode,
        "query_count": query_count,
        "requested_top_k": top_k,
        "fts_rows_returned": 0,
        "database_rows_scanned": 0,
        "database_candidates": 0,
        "legacy_candidates": 0,
        "ranked_candidates": 0,
        "ocr_filtered_count": 0,
        "product_filtered_count": 0,
        "category_filtered_count": 0,
        "deduplicated_count": 0,
        "selected_count": 0,
        "selected_document_count": 0,
        "library_document_count": 0,
        "library_chunk_count": 0,
        "library_usable_document_count": 0,
        "library_ocr_document_count": 0,
        "database_available": None,
        "retrieval_complete": True,
        "retrieval_error": "",
        "timed_out": False,
        "elapsed_ms": 0,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest().lower()


def _database_matches_package(path: Path, manifest: dict[str, Any]) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    expected_size = int(manifest.get("original_size") or 0)
    expected_hash = str(manifest.get("sha256") or "").lower()
    if expected_size and path.stat().st_size != expected_size:
        return False
    if not expected_hash:
        return True
    marker = path.with_name(f"{path.name}.sha256")
    try:
        if marker.read_text(encoding="utf-8").strip().lower() == expected_hash:
            return True
    except OSError:
        pass
    if _file_sha256(path) != expected_hash:
        return False
    try:
        marker.write_text(expected_hash + "\n", encoding="utf-8")
    except OSError:
        pass
    return True


def ensure_literature_database(path: Path = LITERATURE_DB_PATH) -> bool:
    """Materialize the packaged full index once on cloud deployments."""
    manifest_path = LITERATURE_PACKAGE_DIR / "manifest.json"
    if path != LITERATURE_DB_PATH or not manifest_path.exists():
        return path.exists() and path.stat().st_size > 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return path.exists() and path.stat().st_size > 0
    if _database_matches_package(path, manifest):
        return True
    with _DB_BUILD_LOCK:
        if _database_matches_package(path, manifest):
            return True
        try:
            import zstandard as zstd

            parts = [LITERATURE_PACKAGE_DIR / str(name) for name in manifest.get("parts", [])]
            if not parts or any(not part.exists() for part in parts):
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{os.getpid()}.part")
            digest = hashlib.sha256()
            decompressor = zstd.ZstdDecompressor().decompressobj()
            with temporary.open("wb") as output:
                for part in parts:
                    with part.open("rb") as source:
                        while block := source.read(4 * 1024 * 1024):
                            decoded = decompressor.decompress(block)
                            if decoded:
                                output.write(decoded)
                                digest.update(decoded)
                tail = decompressor.flush()
                if tail:
                    output.write(tail)
                    digest.update(tail)
            expected_size = int(manifest.get("original_size") or 0)
            expected_hash = str(manifest.get("sha256") or "").lower()
            if expected_size and temporary.stat().st_size != expected_size:
                temporary.unlink(missing_ok=True)
                return False
            if expected_hash and digest.hexdigest().lower() != expected_hash:
                temporary.unlink(missing_ok=True)
                return False
            os.replace(temporary, path)
            marker = path.with_name(f"{path.name}.sha256")
            try:
                if expected_hash:
                    marker.write_text(expected_hash + "\n", encoding="utf-8")
                else:
                    marker.unlink(missing_ok=True)
            except OSError:
                pass
            return True
        except Exception:
            temporary = path.with_name(f"{path.name}.{os.getpid()}.part")
            temporary.unlink(missing_ok=True)
            return False


def database_stats(path: Path = LITERATURE_DB_PATH) -> dict[str, Any]:
    if path == LITERATURE_DB_PATH:
        ensure_literature_database(path)
    if not path.exists():
        return {"available": False, "documents": 0, "chunks": 0, "categories": {}}
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        documents = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        categories = {
            str(row[0]): int(row[1])
            for row in connection.execute("SELECT category, COUNT(*) FROM chunks GROUP BY category ORDER BY category")
        }
        connection.close()
        return {"available": True, "documents": documents, "chunks": chunks, "categories": categories}
    except (sqlite3.Error, OSError):
        return {"available": False, "documents": 0, "chunks": 0, "categories": {}}


@lru_cache(maxsize=8)
def _library_counts_cached(
    path_text: str,
    modified_ns: int,
    size: int,
    use_manifests: bool,
) -> tuple[int, int, int, int]:
    del modified_ns, size
    documents = 0
    chunks = 0
    if use_manifests:
        for manifest_path in (
            LITERATURE_PACKAGE_DIR / "manifest.json",
            LITERATURE_DIR / "manifest.json",
        ):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                documents = int(manifest.get("documents") or 0)
                chunks = int(manifest.get("chunks") or 0)
                if documents or chunks:
                    break
            except (OSError, TypeError, ValueError):
                continue
    try:
        connection = sqlite3.connect(f"file:{Path(path_text).as_posix()}?mode=ro", uri=True)
        if not documents:
            documents = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        if not chunks:
            chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        quality_rows = connection.execute(
            "SELECT text_quality, COUNT(*) FROM documents GROUP BY text_quality"
        ).fetchall()
        connection.close()
        quality_counts = {str(row[0] or ""): int(row[1] or 0) for row in quality_rows}
        ocr_documents = int(quality_counts.get("ocr_required") or 0)
        usable_documents = max(0, documents - ocr_documents)
        return documents, chunks, usable_documents, ocr_documents
    except (sqlite3.Error, OSError):
        return documents, chunks, 0, 0


def library_scope_stats(path: Path = LITERATURE_DB_PATH) -> dict[str, int]:
    try:
        stat = path.stat()
    except OSError:
        if path == LITERATURE_DB_PATH:
            for manifest_path in (
                LITERATURE_PACKAGE_DIR / "manifest.json",
                LITERATURE_DIR / "manifest.json",
            ):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    documents = int(manifest.get("documents") or 0)
                    chunks = int(manifest.get("chunks") or 0)
                    if documents or chunks:
                        return {
                            "library_document_count": documents,
                            "library_chunk_count": chunks,
                            "library_usable_document_count": 0,
                            "library_ocr_document_count": 0,
                        }
                except (OSError, TypeError, ValueError):
                    continue
        return {
            "library_document_count": 0,
            "library_chunk_count": 0,
            "library_usable_document_count": 0,
            "library_ocr_document_count": 0,
        }
    documents, chunks, usable_documents, ocr_documents = _library_counts_cached(
        str(path),
        stat.st_mtime_ns,
        stat.st_size,
        path == LITERATURE_DB_PATH,
    )
    return {
        "library_document_count": documents,
        "library_chunk_count": chunks,
        "library_usable_document_count": usable_documents,
        "library_ocr_document_count": ocr_documents,
    }


def _chunk_paths(path: Path) -> list[Path]:
    paths = [path]
    if path == DATA_PATH:
        paths.extend(item for item in SUPPLEMENTAL_PATHS if item != path)
    return paths


@lru_cache(maxsize=12)
def _load_jsonl_cached(path_text: str, modified_ns: int, size: int) -> tuple[dict[str, Any], ...]:
    del modified_ns, size
    path = Path(path_text)
    output: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                output.append(json.loads(line))
    return tuple(output)


def load_chunks(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk_path in _chunk_paths(path):
        if not chunk_path.exists():
            continue
        stat = chunk_path.stat()
        for chunk in _load_jsonl_cached(str(chunk_path), stat.st_mtime_ns, stat.st_size):
            chunk_id = str(chunk.get("chunk_id") or f"{chunk_path}:{len(chunks)}")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunks.append(dict(chunk))
    return chunks


def _english_terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower())


def _chinese_ngrams(text: str, min_n: int = 2, max_n: int = 3) -> list[str]:
    terms: list[str] = []
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        if min_n <= len(phrase) <= 8:
            terms.append(phrase)
        for size in range(min_n, max_n + 1):
            if len(phrase) >= size:
                terms.extend(phrase[index : index + size] for index in range(len(phrase) - size + 1))
    return terms


def _concept_terms(text: str) -> list[str]:
    lower = text.lower()
    return [
        f"concept_{concept}"
        for concept, terms in SEMANTIC_CONCEPTS.items()
        if any(term.lower() in lower for term in terms)
    ]


def _expand_query(query: str) -> str:
    expansions: list[str] = []
    lower = query.lower()
    for keyword, terms in QUERY_EXPANSIONS.items():
        if keyword.lower() in lower:
            expansions.extend(terms)
    for terms in SEMANTIC_CONCEPTS.values():
        if any(term.lower() in lower for term in terms):
            expansions.extend(terms)
    return " ".join(dict.fromkeys([query, *expansions]))


def _semantic_counter(text: str) -> Counter[str]:
    expanded = _expand_query(text)
    words = _english_terms(expanded)
    terms: list[str] = [word for word in words if word not in ENGLISH_STOPWORDS]
    terms.extend(f"{words[index]} {words[index + 1]}" for index in range(len(words) - 1))
    terms.extend(_chinese_ngrams(expanded))
    terms.extend(_concept_terms(expanded))
    return Counter(term for term in terms if len(term) > 1)


def _tokens(text: str) -> set[str]:
    return set(_semantic_counter(text))


def _chunk_search_text(chunk: dict[str, Any], fields: list[str] | None = None) -> str:
    values: list[str] = []
    for field in fields or RETRIEVAL_FIELDS:
        value = chunk.get(field, "")
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        else:
            values.append(str(value))
    return " ".join(values)


def _matches_product(chunk_product: str, product_filter: str | None) -> bool:
    if not product_filter or product_filter == "不限":
        return True
    products = {item for item in re.split(r"[、,;/\s]+", chunk_product) if item}
    if product_filter in products or chunk_product == product_filter:
        return True
    if product_filter == "柑橘":
        return bool(products & CITRUS_PRODUCTS) or chunk_product in CITRUS_PRODUCTS
    compatible = {
        "陈皮": {"陈皮", "柑橘", "果皮", "精油", "果胶"},
        "橙汁": {"橙汁", "柑橘", "果肉"},
        "果肉": {"果肉", "橙汁", "柑橘"},
        "果皮": {"果皮", "陈皮", "精油", "果胶", "柑橘"},
        "果胶": {"果胶", "果皮", "副产物", "柑橘"},
        "精油": {"精油", "果皮", "副产物", "柑橘"},
        "种子": {"种子", "副产物", "柑橘"},
        "副产物": {"副产物", "果胶", "精油", "种子", "柑橘"},
    }
    return bool(products & compatible.get(product_filter, {product_filter, "柑橘"}))


def _matches_category(chunk_category: str, category_filter: str | None) -> bool:
    if not category_filter:
        return True
    categories = {item for item in re.split(r"[、,;/\s]+", chunk_category) if item}
    return category_filter in categories


def _keyword_score(query_tokens: set[str], chunk: dict[str, Any]) -> tuple[float, list[str]]:
    body_tokens = _tokens(_chunk_search_text(chunk, ["section", "chunk_text", "doi", "publication", "source"]))
    metadata_tokens = _tokens(_chunk_search_text(chunk, TITLE_WEIGHT_FIELDS))
    body_overlap = query_tokens & body_tokens
    metadata_overlap = query_tokens & metadata_tokens
    score = float(len(body_overlap)) + 1.6 * len(metadata_overlap)
    matched = sorted(body_overlap | metadata_overlap, key=lambda item: (-len(item), item))[:16]
    return score, matched


def _idf_weights(counters: list[Counter[str]]) -> dict[str, float]:
    count = len(counters)
    frequencies: Counter[str] = Counter()
    for counter in counters:
        frequencies.update(counter.keys())
    return {term: math.log((count + 1) / (frequency + 1)) + 1 for term, frequency in frequencies.items()}


def _weighted_vector(counter: Counter[str], idf: dict[str, float], document_count: int) -> dict[str, float]:
    fallback = math.log(document_count + 1) + 1
    return {term: (1 + math.log(value)) * idf.get(term, fallback) for term, value in counter.items()}


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _metadata_score(chunk: dict[str, Any], product_filter: str | None, query: str = "") -> float:
    score = 0.0
    product = str(chunk.get("product") or chunk.get("category") or "")
    if product_filter and product_filter != "不限":
        score += 0.55 if product_filter in product else 0.25
    section = str(chunk.get("section") or "")
    if section in {"摘要", "结果", "结果与讨论", "结论"}:
        score += 0.22
    if any(term in query for term in ["工艺", "方法", "提取", "干燥", "发酵"]) and section == "材料与方法":
        score += 0.28
    if chunk.get("doi"):
        score += 0.08
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|mg|g|kg|°c|h|min|mpa|ppm|μg|µg)", str(chunk.get("chunk_text", "")), re.I):
        score += 0.15
    return min(score, 1.0)


def _fts_query_terms(query: str, limit: int = 56) -> list[str]:
    expanded = _expand_query(query)
    counter = _semantic_counter(expanded)
    terms = [term for term, _ in counter.most_common() if " " not in term and len(term) > 1]
    concepts = [term for term in _concept_terms(expanded) if term not in terms]
    ordered = [*concepts, *terms]
    return list(dict.fromkeys(ordered))[:limit]


DEEP_FTS_PRODUCT_ANCHORS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("柑橘汁", "橙汁", "果汁", "nfc", "orange juice", "citrus juice", "concentrated juice"),
     ("concept_juice", "橙汁", "果汁", "orange juice", "citrus juice")),
    (("陈皮", "广陈皮", "chenpi", "citri reticulatae"),
     ("concept_chenpi", "陈皮", "chenpi", "citri reticulatae")),
    (("果胶", "pectin"), ("concept_pectin", "果胶", "pectin")),
    (("精油", "挥发油", "essential oil", "volatile oil"),
     ("concept_essential_oil", "精油", "essential oil", "volatile oil")),
    (("种子", "籽油", "seed oil"), ("concept_seed", "种子", "籽油", "seed oil")),
    (("副产物", "果渣", "byproduct", "by-product", "pomace"),
     ("concept_byproduct", "副产物", "果渣", "byproduct", "pomace")),
    (("柑橘", "citrus", "orange", "mandarin", "tangerine"),
     ("concept_citrus", "柑橘", "citrus", "orange")),
)

DEEP_FTS_FOCUS_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("清洗", "洗涤", "washing", "wash"), ("清洗", "washing", "wash", "disinfection")),
    (("破碎", "crushing"), ("破碎", "crushing")),
    (("榨汁", "压榨", "juicing", "pressing"), ("榨汁", "压榨", "juicing", "pressing")),
    (("酶解", "果胶酶", "pectinase", "enzymatic"), ("酶解", "果胶酶", "pectinase", "enzymatic")),
    (("澄清", "clarification", "fining"), ("澄清", "clarification", "fining", "depectinization")),
    (("过滤", "超滤", "微滤", "filtration", "ultrafiltration", "microfiltration"),
     ("过滤", "filtration", "ultrafiltration", "microfiltration")),
    (("均质", "homogenization", "homogenisation", "homogenized", "hph"),
     ("均质", "homogenization", "homogenisation", "hph")),
    (("脱气", "deaeration", "de-aeration"), ("脱气", "deaeration", "de-aeration")),
    (("杀菌", "巴氏", "pasteurization", "sterilization"),
     ("杀菌", "巴氏", "pasteurization", "sterilization")),
    (("灌装", "filling", "bottling"), ("灌装", "filling", "bottling", "aseptic filling")),
    (("包装", "packaging"), ("包装", "packaging")),
    (("干燥", "热风", "冻干", "drying", "freeze-drying"),
     ("干燥", "drying", "hot air drying", "freeze-drying")),
    (("陈化", "aging", "ageing", "maturation"), ("陈化", "aging", "ageing", "maturation")),
    (("储藏", "贮藏", "storage", "shelf life"), ("储藏", "贮藏", "storage", "shelf life")),
    (("浓缩", "evaporation", "concentration"), ("浓缩", "evaporation", "concentrated juice")),
    (("发酵", "fermentation"), ("发酵", "fermentation")),
    (("提取", "extraction"), ("提取", "extraction")),
    (("压力", "pressure", "mpa"), ("压力", "pressure", "mpa")),
    (("流量", "flow"), ("流量", "flow")),
    (("转速", "rpm"), ("转速", "rpm")),
    (("料液比", "固液比", "solid liquid ratio"), ("料液比", "固液比", "solid liquid ratio")),
    (("酶用量", "dosage"), ("酶用量", "dosage", "pectinase")),
    (("水分活度", "water activity"), ("水分活度", "water activity")),
    (("ph",), ("ph",)),
)

DEEP_FTS_GENERIC_TERMS = {
    "concept_unit_operation", "concept_process_parameter", "materials", "material", "methods", "method",
    "results", "result", "discussion", "quality", "processing", "process", "parameter", "parameters",
    "condition", "conditions", "temperature", "time", "study", "research", "experiment",
    "材料", "方法", "结果", "讨论", "质量", "加工", "工艺", "参数", "条件", "温度", "时间", "研究",
    "实验", "流程", "评价", "完整",
}

# The first groups describe unit operations; later groups are generic
# parameter names. An operation is a much stronger retrieval anchor.
DEEP_FTS_OPERATION_GROUP_COUNT = 17


def _fts_phrase(term: str) -> str:
    return f'"{term.replace(chr(34), chr(34) * 2)}"'


def _matched_deep_terms(
    query: str,
    groups: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
    *,
    max_groups: int,
    terms_per_group: int,
) -> list[str]:
    lower = query.lower()
    matched: list[tuple[int, tuple[str, ...]]] = []
    for aliases, terms in groups:
        positions: list[int] = []
        for alias in aliases:
            normalized_alias = alias.lower()
            if re.fullmatch(r"[a-z0-9][a-z0-9 ._/-]*", normalized_alias):
                matches = list(
                    re.finditer(
                        rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])",
                        lower,
                    )
                )
                positions.append(matches[-1].start() if matches else -1)
            else:
                positions.append(lower.rfind(normalized_alias))
        position = max(positions, default=-1)
        if position >= 0:
            matched.append((position, terms))
    matched.sort(key=lambda item: item[0], reverse=True)
    selected: list[str] = []
    for _, terms in matched[:max_groups]:
        representatives = [terms[0]]
        representatives.extend(term for term in terms[1:] if re.search(r"[a-z]", term, flags=re.I))
        representatives.extend(terms[1:])
        selected.extend(list(dict.fromkeys(representatives))[:terms_per_group])
    return list(dict.fromkeys(selected))


def _is_deep_generic_term(term: str) -> bool:
    normalized = term.strip().lower()
    if normalized in DEEP_FTS_GENERIC_TERMS:
        return True
    return any(fragment in normalized for fragment in ("材料与方法", "实验条件", "研究结果", "工艺参数"))


def _build_fts_match_query(query: str, retrieval_mode: RetrievalMode = "quick") -> str:
    mode = _normalize_retrieval_mode(retrieval_mode)
    if mode == "quick":
        return " OR ".join(_fts_phrase(term) for term in _fts_query_terms(query))
    anchors = _matched_deep_terms(
        query, DEEP_FTS_PRODUCT_ANCHORS, max_groups=1, terms_per_group=1
    )
    focus = _matched_deep_terms(
        query,
        DEEP_FTS_FOCUS_GROUPS[:DEEP_FTS_OPERATION_GROUP_COUNT],
        max_groups=2,
        terms_per_group=2,
    )
    if not focus:
        focus = _matched_deep_terms(
            query,
            DEEP_FTS_FOCUS_GROUPS[DEEP_FTS_OPERATION_GROUP_COUNT:],
            max_groups=2,
            terms_per_group=2,
        )
    if not focus:
        focus = [
            term
            for term in _fts_query_terms(query, limit=24)
            if term not in anchors and not _is_deep_generic_term(term) and not term.startswith("concept_")
        ][:8]
    anchor_expression = " OR ".join(_fts_phrase(term) for term in anchors)
    focus_expression = " OR ".join(_fts_phrase(term) for term in focus)
    if anchor_expression and focus_expression:
        return f"({anchor_expression}) AND ({focus_expression})"
    return focus_expression or anchor_expression


def _database_candidates(
    query: str,
    product_filter: str | None,
    limit: int,
    db_path: Path = LITERATURE_DB_PATH,
    category_filter: str | None = None,
    *,
    retrieval_mode: RetrievalMode = "quick",
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    mode = _normalize_retrieval_mode(retrieval_mode)
    database_available = db_path.exists()
    if db_path == LITERATURE_DB_PATH:
        database_available = ensure_literature_database(db_path) and db_path.exists()
    if stats is not None:
        stats["database_available"] = database_available
    if not database_available:
        if stats is not None and mode == "deep":
            stats["retrieval_complete"] = False
            stats["retrieval_error"] = "全库文献索引未能加载，本轮未执行全库深度检索。"
        return []
    match_query = _build_fts_match_query(query, mode)
    if not match_query:
        return []
    if stats is not None:
        stats["fts_expression_term_count"] = int(stats.get("fts_expression_term_count") or 0) + match_query.count('"') // 2
    where = ["chunks_fts MATCH ?"]
    parameters: list[Any] = [match_query]
    if mode == "deep":
        # Exclude metadata-only entries before LIMIT so usable full-text rows
        # backfill the requested candidate window.
        where.append("LOWER(COALESCE(c.section, '')) NOT LIKE '%待ocr%'")
        if category_filter:
            where.append("INSTR(c.category, ?) > 0")
            parameters.append(category_filter)
    row_limit = (
        min(max(limit * 4, 240), PROCESS_DEEP_MAX_FTS_ROWS)
        if mode == "deep"
        else max(limit * 3, 80)
    )
    parameters.append(row_limit)
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    deadline = time.monotonic() + PROCESS_DEEP_SQL_TIMEOUT_SECONDS
    if mode == "deep":
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10_000)
    try:
        rows = connection.execute(
            f"""
            SELECT c.*, bm25(chunks_fts, 5.0, 2.8, 2.3, 2.0, 0.9, 0.35) AS fts_rank
            FROM chunks_fts
            JOIN chunks AS c ON c.id = chunks_fts.rowid
            WHERE {' AND '.join(where)}
            ORDER BY fts_rank
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    except sqlite3.Error as error:
        if stats is not None:
            stats["retrieval_complete"] = False
            if "interrupt" in str(error).lower():
                stats["timed_out"] = True
                stats["retrieval_error"] = "单次全文检索超过时限，本轮结果可能不完整。"
            else:
                stats["retrieval_error"] = "全文索引查询失败，本轮结果可能不完整。"
        rows = []
    finally:
        if mode == "deep":
            connection.set_progress_handler(None, 0)
        connection.close()
    if stats is not None:
        stats["fts_rows_returned"] = int(stats.get("fts_rows_returned") or 0) + len(rows)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if mode == "deep" and is_pending_ocr_entry(item):
            if stats is not None:
                stats["ocr_filtered_count"] = int(stats.get("ocr_filtered_count") or 0) + 1
            continue
        if not _matches_product(str(item.get("product") or item.get("category") or ""), product_filter):
            if stats is not None:
                stats["product_filtered_count"] = int(stats.get("product_filtered_count") or 0) + 1
            continue
        if not _matches_category(str(item.get("category") or ""), category_filter):
            if stats is not None:
                stats["category_filtered_count"] = int(stats.get("category_filtered_count") or 0) + 1
            continue
        rank = abs(float(item.pop("fts_rank", 0.0)))
        item["_fts_signal"] = rank / (rank + 4.0) if rank else 0.0
        item["page"] = item.get("page_start")
        item["source"] = item.get("publication") or item.get("doi") or item.get("source_file")
        item["keywords"] = [value for value in str(item.get("keywords") or "").split("、") if value]
        candidates.append(item)
        if len(candidates) >= limit:
            break
    if stats is not None:
        stats["database_candidates"] = int(stats.get("database_candidates") or 0) + len(candidates)
    return candidates


def _legacy_candidates(product_filter: str | None, category_filter: str | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    # Once the scalable database exists, the old chunks.jsonl is redundant. Keep
    # only the small hand-curated processing tree as supplemental evidence.
    source_chunks = (
        load_chunks(SUPPLEMENTAL_PATHS[0])
        if LITERATURE_DB_PATH.exists() and SUPPLEMENTAL_PATHS[0].exists()
        else load_chunks()
    )
    for chunk in source_chunks:
        if _matches_product(str(chunk.get("product") or chunk.get("category") or ""), product_filter):
            item = dict(chunk)
            item.setdefault("document_id", str(item.get("source_file") or item.get("title") or item.get("chunk_id")))
            item.setdefault("category", str(item.get("product") or "历史知识片段"))
            item.setdefault("section", "正文")
            item.setdefault("page", item.get("page_start"))
            item.setdefault("publication", str(item.get("source") or ""))
            item["_fts_signal"] = 0.0
            if _matches_category(str(item.get("category") or item.get("product") or ""), category_filter):
                candidates.append(item)
    return candidates


def _rank_candidates(query: str, candidates: list[dict[str, Any]], product_filter: str | None) -> list[dict[str, Any]]:
    if not candidates:
        return []
    query_tokens = _tokens(_expand_query(query))
    query_concepts = set(_concept_terms(query))
    counters = [_semantic_counter(_chunk_search_text(chunk)) for chunk in candidates]
    idf = _idf_weights(counters)
    query_vector = _weighted_vector(_semantic_counter(query), idf, len(candidates))
    keyword_scores: list[float] = []
    matched_terms: list[list[str]] = []
    for chunk in candidates:
        score, matched = _keyword_score(query_tokens, chunk)
        keyword_scores.append(score)
        matched_terms.append(matched)
    max_keyword = max(keyword_scores) or 1.0

    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, (chunk, counter) in enumerate(zip(candidates, counters)):
        keyword = keyword_scores[index] / max_keyword
        semantic = _cosine_similarity(query_vector, _weighted_vector(counter, idf, len(candidates)))
        metadata = _metadata_score(chunk, product_filter, query)
        fts_signal = float(chunk.get("_fts_signal") or 0.0)
        chunk_concepts = set(_concept_terms(_chunk_search_text(chunk)))
        chunk_concepts.update(
            term for term in str(chunk.get("search_terms") or "").split() if term.startswith("concept_")
        )
        concept_coverage = len(query_concepts & chunk_concepts) / max(len(query_concepts), 1)
        score = (
            0.31 * keyword
            + 0.27 * semantic
            + 0.17 * fts_signal
            + 0.12 * metadata
            + 0.13 * concept_coverage
        )
        if "concept_citrus" in query_concepts and "concept_citrus" not in chunk_concepts:
            continue
        if score <= 0:
            continue
        enriched = {key: value for key, value in chunk.items() if not key.startswith("_") and key != "search_terms"}
        enriched.update(
            {
                "match_score": round(score * 100, 3),
                "keyword_score": round(keyword, 4),
                "vector_score": round(semantic, 4),
                "metadata_score": round(metadata, 4),
                "retrieval_method": "sqlite_fts_hybrid" if fts_signal else "legacy_hybrid",
                "matched_terms": matched_terms[index],
            }
        )
        ranked.append((score, enriched))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked]


def _single_query_search(
    query: str,
    product_filter: str | None,
    limit: int,
    category_filter: str | None = None,
    *,
    retrieval_mode: RetrievalMode = "quick",
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    mode = _normalize_retrieval_mode(retrieval_mode)
    database_limit = (
        min(max(limit * 6, 160), PROCESS_DEEP_MAX_DATABASE_CANDIDATES)
        if mode == "deep"
        else max(limit * 5, 80)
    )
    database_items = _database_candidates(
        query,
        product_filter,
        database_limit,
        category_filter=category_filter,
        retrieval_mode=mode,
        stats=stats,
    )
    full_index_unavailable = (
        mode == "deep"
        and stats is not None
        and stats.get("database_available") is False
    )
    legacy_items = [] if full_index_unavailable else _legacy_candidates(product_filter, category_filter)
    if stats is not None:
        stats["legacy_candidates"] = int(stats.get("legacy_candidates") or 0) + len(legacy_items)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*database_items, *legacy_items]:
        if mode == "deep" and is_pending_ocr_entry(item):
            if stats is not None:
                stats["ocr_filtered_count"] = int(stats.get("ocr_filtered_count") or 0) + 1
            continue
        chunk_id = str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page')}:{len(candidates)}")
        if chunk_id in seen:
            if stats is not None:
                stats["deduplicated_count"] = int(stats.get("deduplicated_count") or 0) + 1
            continue
        seen.add(chunk_id)
        candidates.append(item)
    ranked = _rank_candidates(query, candidates, product_filter)
    if stats is not None:
        stats["ranked_candidates"] = int(stats.get("ranked_candidates") or 0) + len(ranked)
    diversified: list[dict[str, Any]] = []
    document_counts: Counter[str] = Counter()
    per_document_limit = 4 if mode == "deep" else 3
    for item in ranked:
        document_id = str(item.get("document_id") or item.get("source_file") or item.get("title"))
        if document_counts[document_id] >= per_document_limit:
            continue
        diversified.append(item)
        document_counts[document_id] += 1
        if len(diversified) >= limit:
            break
    return diversified


def _normalize_queries(query: str | Iterable[str]) -> list[str]:
    values = [query] if isinstance(query, str) else list(query)
    return [value.strip() for value in dict.fromkeys(str(item) for item in values) if value.strip()]


def _retrieval_output(
    evidence: list[dict[str, Any]],
    stats: dict[str, Any],
    started_at: float,
    return_metadata: bool,
) -> list[dict[str, Any]] | dict[str, Any]:
    scope_stats = library_scope_stats()
    for key, value in scope_stats.items():
        if value or not stats.get(key):
            stats[key] = value
    stats["selected_count"] = len(evidence)
    stats["selected_document_count"] = len(
        {
            str(item.get("document_id") or item.get("source_file") or item.get("title"))
            for item in evidence
        }
    )
    stats["elapsed_ms"] = round((time.monotonic() - started_at) * 1000, 2)
    if return_metadata:
        return {"evidence": evidence, "deep_retrieval_stats": stats}
    return evidence


def comprehensive_search_knowledge(
    query: str | Iterable[str],
    product_filter: str | None = None,
    top_k: int = 10,
    category_filter: str | None = None,
    *,
    retrieval_mode: RetrievalMode = "quick",
    return_metadata: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Run multi-query hybrid retrieval and return diversified evidence from distinct papers."""
    started_at = time.monotonic()
    mode = _normalize_retrieval_mode(retrieval_mode)
    queries = _normalize_queries(query)
    stats = _new_retrieval_stats(mode, len(queries), top_k)
    if not queries or top_k <= 0:
        return _retrieval_output([], stats, started_at, return_metadata)
    aggregate: dict[str, dict[str, Any]] = {}
    fusion_scores: defaultdict[str, float] = defaultdict(float)
    query_matches: defaultdict[str, list[str]] = defaultdict(list)
    keys_by_query: dict[str, list[str]] = {}
    per_query = (
        min(max(top_k * 5, 40), PROCESS_DEEP_MAX_PER_QUERY)
        if mode == "deep"
        else max(top_k * 3, 24)
    )
    stats["per_query_limit"] = per_query
    for subquery in queries:
        keys_by_query[subquery] = []
        for rank, item in enumerate(
            _single_query_search(
                subquery,
                product_filter,
                per_query,
                category_filter,
                retrieval_mode=mode,
                stats=stats,
            ),
            1,
        ):
            key = str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page')}:{rank}")
            keys_by_query[subquery].append(key)
            fusion_scores[key] += 1.0 / (20 + rank)
            query_matches[key].append(subquery)
            if key not in aggregate or float(item.get("match_score") or 0) > float(aggregate[key].get("match_score") or 0):
                aggregate[key] = item
        if mode == "deep" and stats.get("database_available") is False:
            break
    stats["unique_candidate_count"] = len(aggregate)
    if not aggregate:
        return _retrieval_output([], stats, started_at, return_metadata)
    max_fusion = max(fusion_scores.values()) or 1.0
    ordered: list[tuple[float, dict[str, Any]]] = []
    for key, item in aggregate.items():
        base = float(item.get("match_score") or 0) / 100.0
        fusion = fusion_scores[key] / max_fusion
        final = 0.76 * base + 0.24 * fusion
        enriched = dict(item)
        enriched["match_score"] = round(final * 100, 3)
        enriched["retrieval_queries"] = query_matches[key]
        enriched["retrieval_method"] = "multi_query_fts_hybrid" if len(queries) > 1 else item.get("retrieval_method", "hybrid")
        ordered.append((final, enriched))
    ordered.sort(key=lambda item: item[0], reverse=True)
    if mode == "deep":
        usable_ordered: list[tuple[float, dict[str, Any]]] = []
        for row in ordered:
            if is_pending_ocr_entry(row[1]):
                stats["ocr_filtered_count"] = int(stats["ocr_filtered_count"]) + 1
                continue
            usable_ordered.append(row)
        ordered = usable_ordered

    selected: list[dict[str, Any]] = []
    document_counts: Counter[str] = Counter()
    selected_keys: set[str] = set()

    # With explicit multi-query retrieval, reserve one strong result per facet
    # before global filling. This prevents a large, well-matching category from
    # hiding juice/pectin/oil/seed/by-product evidence in a broad batch analysis.
    enriched_by_key = {
        str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page')}"): item
        for _, item in ordered
    }
    per_document_limit = 3 if mode == "deep" else 2
    if len(queries) > 1:
        for subquery in queries:
            for key in keys_by_query.get(subquery, []):
                item = enriched_by_key.get(key)
                if not item or key in selected_keys:
                    continue
                document_id = str(item.get("document_id") or item.get("source_file") or item.get("title"))
                if document_counts[document_id] >= per_document_limit:
                    continue
                selected.append(item)
                selected_keys.add(key)
                document_counts[document_id] += 1
                break
            if len(selected) >= top_k:
                return _retrieval_output(selected[:top_k], stats, started_at, return_metadata)

    for _, item in ordered:
        key = str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page')}")
        if key in selected_keys:
            continue
        document_id = str(item.get("document_id") or item.get("source_file") or item.get("title"))
        if document_counts[document_id] >= per_document_limit:
            continue
        selected.append(item)
        selected_keys.add(key)
        document_counts[document_id] += 1
        if len(selected) >= top_k:
            break
    return _retrieval_output(selected, stats, started_at, return_metadata)


def keyword_search_knowledge(
    query: str,
    product_filter: str | None = None,
    top_k: int = 5,
    *,
    retrieval_mode: RetrievalMode = "quick",
    return_metadata: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    results = comprehensive_search_knowledge(
        query,
        product_filter,
        top_k,
        retrieval_mode=retrieval_mode,
        return_metadata=return_metadata,
    )
    evidence = results["evidence"] if isinstance(results, dict) else results
    for item in evidence:
        item["retrieval_method"] = f"keyword+{item.get('retrieval_method', 'hybrid')}"
    return results


def semantic_search_knowledge(
    query: str,
    product_filter: str | None = None,
    top_k: int = 5,
    *,
    retrieval_mode: RetrievalMode = "quick",
    return_metadata: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    results = comprehensive_search_knowledge(
        query,
        product_filter,
        top_k,
        retrieval_mode=retrieval_mode,
        return_metadata=return_metadata,
    )
    evidence = results["evidence"] if isinstance(results, dict) else results
    for item in evidence:
        item["retrieval_method"] = f"semantic+{item.get('retrieval_method', 'hybrid')}"
    return results


def hybrid_search_knowledge(
    query: str | Iterable[str],
    product_filter: str | None = None,
    top_k: int = 5,
    *,
    retrieval_mode: RetrievalMode = "quick",
    return_metadata: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    return comprehensive_search_knowledge(
        query=query,
        product_filter=product_filter,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
        return_metadata=return_metadata,
    )


def search_knowledge(
    query: str,
    product_filter: str | None = None,
    top_k: int = 5,
    *,
    retrieval_mode: RetrievalMode = "quick",
    return_metadata: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    return comprehensive_search_knowledge(
        query=query,
        product_filter=product_filter,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
        return_metadata=return_metadata,
    )


def _is_method_or_result_section(section: str) -> bool:
    normalized = str(section or "").strip().lower()
    return any(
        term in normalized
        for term in ("方法", "工艺", "材料", "结果", "讨论", "method", "material", "result", "discussion")
    )


def fetch_adjacent_method_result_chunks(
    evidence: list[dict[str, Any]],
    *,
    db_path: Path = LITERATURE_DB_PATH,
    retrieval_mode: RetrievalMode = "deep",
    radius: int = PROCESS_DEEP_NEIGHBOR_RADIUS,
    per_hit: int = PROCESS_DEEP_NEIGHBOR_PER_HIT,
    limit: int = PROCESS_DEEP_NEIGHBOR_LIMIT,
    return_metadata: bool = False,
) -> dict[str, list[dict[str, Any]]] | dict[str, Any]:
    """Fetch bounded method/result context next to already selected chunks."""
    started_at = time.monotonic()
    mode = _normalize_retrieval_mode(retrieval_mode)
    stats: dict[str, Any] = {
        "retrieval_mode": mode,
        "seed_count": 0,
        "adjacent_candidate_count": 0,
        "ocr_filtered_count": 0,
        "adjacent_added_count": 0,
        "elapsed_ms": 0,
    }
    seeds: list[tuple[str, str, int]] = []
    seen_documents: set[str] = set()
    seen_seeds: set[str] = set()
    for item in evidence:
        seed_key = str(item.get("chunk_id") or "").strip()
        document_id = str(item.get("document_id") or "").strip()
        try:
            chunk_index = int(item.get("chunk_index"))
        except (TypeError, ValueError):
            continue
        if not seed_key or not document_id or seed_key in seen_seeds:
            continue
        if document_id not in seen_documents and len(seen_documents) >= PROCESS_DEEP_NEIGHBOR_DOCUMENT_LIMIT:
            continue
        seen_documents.add(document_id)
        seen_seeds.add(seed_key)
        seeds.append((seed_key, document_id, chunk_index))
    stats["seed_count"] = len(seeds)
    adjacent_by_seed: dict[str, list[dict[str, Any]]] = {seed[0]: [] for seed in seeds}
    if not seeds or radius <= 0 or per_hit <= 0 or limit <= 0:
        stats["elapsed_ms"] = round((time.monotonic() - started_at) * 1000, 2)
        if return_metadata:
            return {"adjacent_chunks": adjacent_by_seed, "deep_retrieval_stats": stats}
        return adjacent_by_seed
    if db_path == LITERATURE_DB_PATH:
        ensure_literature_database(db_path)
    if not db_path.exists():
        stats["elapsed_ms"] = round((time.monotonic() - started_at) * 1000, 2)
        if return_metadata:
            return {"adjacent_chunks": adjacent_by_seed, "deep_retrieval_stats": stats}
        return adjacent_by_seed

    values = ", ".join("(?, ?, ?)" for _ in seeds)
    parameters: list[Any] = [value for seed in seeds for value in seed]
    parameters.extend([radius, radius])
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"""
            WITH seed(seed_key, document_id, chunk_index) AS (VALUES {values})
            SELECT seed.seed_key, ABS(c.chunk_index - seed.chunk_index) AS neighbor_distance, c.*
            FROM seed
            JOIN chunks AS c ON c.document_id = seed.document_id
            WHERE c.chunk_id <> seed.seed_key
              AND c.chunk_index BETWEEN seed.chunk_index - ? AND seed.chunk_index + ?
            ORDER BY seed.seed_key, neighbor_distance, c.chunk_index
            """,
            parameters,
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        connection.close()
    stats["adjacent_candidate_count"] = len(rows)
    total = 0
    seen_by_seed: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        seed_key = str(row["seed_key"])
        if len(adjacent_by_seed.get(seed_key, [])) >= per_hit or total >= limit:
            continue
        item = dict(row)
        item.pop("seed_key", None)
        distance = int(item.pop("neighbor_distance", 0) or 0)
        if not _is_method_or_result_section(str(item.get("section") or "")):
            continue
        if is_pending_ocr_entry(item):
            stats["ocr_filtered_count"] = int(stats["ocr_filtered_count"]) + 1
            continue
        chunk_id = str(item.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen_by_seed[seed_key]:
            continue
        seen_by_seed[seed_key].add(chunk_id)
        item["page"] = item.get("page_start")
        item["source"] = item.get("publication") or item.get("doi") or item.get("source_file")
        item["keywords"] = [value for value in str(item.get("keywords") or "").split("、") if value]
        item["retrieval_method"] = "sqlite_adjacent_method_result"
        item["adjacent_distance"] = distance
        adjacent_by_seed[seed_key].append(item)
        total += 1
    stats["adjacent_added_count"] = total
    stats["elapsed_ms"] = round((time.monotonic() - started_at) * 1000, 2)
    if return_metadata:
        return {"adjacent_chunks": adjacent_by_seed, "deep_retrieval_stats": stats}
    return adjacent_by_seed


def format_evidence_context(evidence: list[dict[str, Any]], excerpt_chars: int = 650) -> str:
    lines: list[str] = []
    for index, item in enumerate(evidence, 1):
        title = str(item.get("title") or "未命名文献")
        year = str(item.get("year") or "年份未知")
        category = str(item.get("category") or item.get("product") or "未分类")
        section = str(item.get("section") or "正文")
        page = item.get("page") or item.get("page_start")
        doi = str(item.get("doi") or "")
        locator = f"第{page}页" if page else "页码未标注"
        source = f"DOI {doi}" if doi else str(item.get("publication") or item.get("source_file") or "本地文献")
        excerpt = re.sub(r"\s+", " ", str(item.get("chunk_text") or "")).strip()
        if len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars].rstrip() + "…"
        lines.append(
            f"[文献{index}] {title}（{year}；类别：{category}；{section}；{locator}；{source}）\n证据片段：{excerpt}"
        )
    return "\n\n".join(lines)
