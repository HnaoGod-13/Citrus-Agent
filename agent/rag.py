from __future__ import annotations

import math
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LITERATURE_PATH = ROOT / "data" / "literature" / "chunks.jsonl"
DEMO_PATH = ROOT / "data" / "clean_chunks" / "sample_chunks.jsonl"
SUPPLEMENTAL_PATHS = [ROOT / "data" / "literature" / "citrus_processing_tree_chunks.jsonl"]
DATA_PATH = LITERATURE_PATH if LITERATURE_PATH.exists() else DEMO_PATH


QUERY_EXPANSIONS = {
    "陈皮": ["chenpi", "citri reticulatae", "dried tangerine peel", "tangerine peel", "chachi"],
    "茶枝柑": ["chachi", "citrus reticulata cv chachiensis"],
    "柑橘": ["citrus", "mandarin", "orange"],
    "整果": ["whole citrus", "whole fruit"],
    "果肉": ["citrus pulp", "fruit pulp", "juice sacs"],
    "果皮": ["citrus peel", "pericarp", "peel"],
    "副产物": ["byproduct", "pomace", "residue"],
    "橙汁": ["orange juice", "citrus juice", "nfc"],
    "果汁": ["juice", "nfc", "concentrate"],
    "浓缩汁": ["concentrated juice", "vacuum concentration"],
    "NFC": ["not from concentrate", "nfc"],
    "果醋": ["vinegar", "fermentation"],
    "果酒": ["fruit wine", "fermentation"],
    "罐头": ["canned", "canning"],
    "砂囊": ["juice sac", "pulp sac"],
    "蜜饯": ["preserve", "candied"],
    "果脯": ["preserve", "candied"],
    "精油": ["essential oil", "volatile oil"],
    "香精": ["flavor", "flavour", "essential oil"],
    "果胶": ["pectin", "pectic"],
    "黄酮": ["flavonoid", "flavonoids"],
    "色素": ["pigment", "carotenoid"],
    "籽油": ["seed oil"],
    "橘核": ["citrus seed"],
    "饲料": ["feed"],
    "有机肥": ["organic fertilizer", "compost"],
    "陈化": ["aging", "ageing", "storage"],
    "仓储": ["storage", "stored"],
    "贮藏": ["storage", "stored"],
    "多糖": ["polysaccharide", "polysaccharides"],
    "挥发油": ["volatile oil", "essential oil"],
    "干燥": ["drying", "dried"],
    "发酵": ["fermentation", "microbial"],
    "质控": ["quality", "authentication", "fingerprint"],
    "霉变": ["mildew", "mold", "fungal"],
    "抗氧化": ["antioxidant"],
    "抗炎": ["anti-inflammatory", "inflammation"],
}

CITRUS_PRODUCTS = {"柑橘", "陈皮", "橙汁", "整果", "果肉", "果皮", "种子", "副产物"}

RETRIEVAL_FIELDS = ["title", "topic", "keywords", "chunk_text", "doi", "source"]
TITLE_WEIGHT_FIELDS = ["title", "topic", "keywords"]
SEMANTIC_CONCEPTS = {
    "chenpi": ["陈皮", "广陈皮", "新会", "茶枝柑", "chenpi", "citri reticulatae", "dried tangerine peel", "aged tangerine peel", "chachi"],
    "citrus": ["柑橘", "柑", "橘", "橙", "citrus", "mandarin", "tangerine", "orange"],
    "whole_fruit": ["整果", "whole citrus", "whole fruit", "candied citrus", "preserved citrus"],
    "pulp": ["果肉", "砂囊", "果粒", "citrus pulp", "fruit pulp", "juice sac", "pulp sac", "vesicle"],
    "peel": ["果皮", "皮渣", "citrus peel", "orange peel", "pericarp", "peel waste"],
    "juice": ["果汁", "橙汁", "NFC", "浓缩汁", "orange juice", "citrus juice", "not from concentrate", "concentrated juice"],
    "fermentation": ["果醋", "果酒", "发酵", "vinegar", "fruit wine", "fermentation", "acetic acid"],
    "essential_oil": ["精油", "挥发油", "香气", "essential oil", "volatile oil", "limonene", "aroma"],
    "pectin": ["果胶", "膳食纤维", "pectin", "pectic", "dietary fiber"],
    "flavonoid": ["黄酮", "多甲氧基黄酮", "flavonoid", "hesperidin", "nobiletin", "tangeretin", "polymethoxyflavone"],
    "seed": ["种子", "籽油", "橘核", "citrus seed", "seed oil"],
    "byproduct": ["副产物", "饲料", "有机肥", "果渣", "pomace", "byproduct", "by-product", "waste valorization", "compost", "feed"],
    "quality": ["质控", "质量", "指纹图谱", "鉴别", "quality", "authentication", "fingerprint", "marker", "origin discrimination"],
    "safety": ["农残", "重金属", "微生物", "黄曲霉", "霉变", "pesticide", "heavy metal", "microbial", "aflatoxin", "mycotoxin", "mold", "fungal"],
    "storage": ["水分", "仓储", "贮藏", "陈化", "干燥", "moisture", "water activity", "storage", "aging", "drying", "shelf life"],
}


def _chunk_paths(path: Path) -> list[Path]:
    paths = [path]
    if path == DATA_PATH:
        paths.extend(item for item in SUPPLEMENTAL_PATHS if item != path)
    return paths


def load_chunks(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk_path in _chunk_paths(path):
        if not chunk_path.exists():
            continue
        with chunk_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                chunk_id = str(chunk.get("chunk_id") or f"{chunk_path}:{len(chunks)}")
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                chunks.append(chunk)
    return chunks


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return words | set(chinese_terms)


def _expand_query(query: str) -> str:
    expansions: list[str] = []
    for keyword, terms in QUERY_EXPANSIONS.items():
        if keyword in query:
            expansions.extend(terms)
    query_lower = query.lower()
    for terms in SEMANTIC_CONCEPTS.values():
        if any(term.lower() in query_lower for term in terms):
            expansions.extend(terms)
    return " ".join([query, *expansions])


def _matches_product(chunk_product: str, product_filter: str | None) -> bool:
    if not product_filter or product_filter == "不限":
        return True
    if chunk_product == product_filter:
        return True
    if product_filter == "柑橘":
        return chunk_product in CITRUS_PRODUCTS
    if product_filter == "陈皮" and chunk_product in {"陈皮", "柑橘", "果皮"}:
        return True
    if product_filter == "橙汁" and chunk_product in {"橙汁", "柑橘", "果肉"}:
        return True
    if product_filter == "果肉" and chunk_product in {"果肉", "橙汁", "柑橘"}:
        return True
    if product_filter == "果皮" and chunk_product in {"果皮", "陈皮", "柑橘"}:
        return True
    if product_filter in {"整果", "种子", "副产物"} and chunk_product in {product_filter, "柑橘"}:
        return True
    return False


def _chunk_search_text(chunk: dict[str, Any], fields: list[str] | None = None) -> str:
    fields = fields or RETRIEVAL_FIELDS
    return " ".join(str(chunk.get(field, "")) for field in fields)


def _english_terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower())


def _chinese_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> list[str]:
    terms: list[str] = []
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(phrase) < min_n:
            continue
        if len(phrase) <= max_n + 2:
            terms.append(phrase)
        for n in range(min_n, max_n + 1):
            if len(phrase) >= n:
                terms.extend(phrase[index : index + n] for index in range(len(phrase) - n + 1))
    return terms


def _concept_terms(text: str) -> list[str]:
    text_lower = text.lower()
    concepts: list[str] = []
    for concept, terms in SEMANTIC_CONCEPTS.items():
        if any(term.lower() in text_lower for term in terms):
            concepts.append(f"concept:{concept}")
    return concepts


def _semantic_counter(text: str) -> Counter[str]:
    expanded_text = _expand_query(text)
    words = _english_terms(expanded_text)
    terms: list[str] = []
    terms.extend(words)
    terms.extend(f"{words[index]} {words[index + 1]}" for index in range(len(words) - 1))
    terms.extend(word[:-1] for word in words if len(word) > 4 and word.endswith("s"))
    terms.extend(_chinese_ngrams(expanded_text))
    terms.extend(_concept_terms(expanded_text))
    return Counter(term for term in terms if term)


def _keyword_score(query_tokens: set[str], chunk: dict[str, Any]) -> tuple[float, list[str]]:
    text_tokens = _tokens(_chunk_search_text(chunk))
    overlap = query_tokens & text_tokens
    score = float(len(overlap))
    for field in TITLE_WEIGHT_FIELDS:
        score += 1.5 * len(query_tokens & _tokens(str(chunk.get(field, ""))))
    return score, sorted(overlap)[:12]


def _idf_weights(counters: list[Counter[str]]) -> dict[str, float]:
    doc_count = len(counters)
    doc_freq: Counter[str] = Counter()
    for counter in counters:
        doc_freq.update(counter.keys())
    return {term: math.log((doc_count + 1) / (freq + 1)) + 1 for term, freq in doc_freq.items()}


def _weighted_vector(counter: Counter[str], idf: dict[str, float], doc_count: int) -> dict[str, float]:
    vector: dict[str, float] = {}
    fallback_idf = math.log(doc_count + 1) + 1
    for term, count in counter.items():
        vector[term] = (1 + math.log(count)) * idf.get(term, fallback_idf)
    return vector


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _metadata_score(chunk: dict[str, Any], product_filter: str | None) -> float:
    product = str(chunk.get("product", ""))
    score = 0.0
    if product_filter and product_filter != "不限":
        score += 1.0 if product == product_filter else 0.55
    if chunk.get("source_type") == "pdf_image_manual_extract":
        score += 0.35
    if chunk.get("title"):
        score += 0.1
    if chunk.get("doi"):
        score += 0.1
    return min(score, 1.0)


def keyword_search_knowledge(query: str, product_filter: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    """Search the local literature chunk library with lexical keyword matching."""
    expanded_query = _expand_query(query)
    query_tokens = _tokens(expanded_query)
    scored: list[tuple[float, dict[str, Any]]] = []

    for chunk in load_chunks():
        if not _matches_product(str(chunk.get("product", "")), product_filter):
            continue
        score, matched_terms = _keyword_score(query_tokens, chunk)
        if chunk.get("source_type") == "pdf_image_manual_extract":
            score += 30
        if score:
            enriched = dict(chunk)
            enriched["match_score"] = score
            enriched["keyword_score"] = score
            enriched["vector_score"] = 0.0
            enriched["metadata_score"] = _metadata_score(chunk, product_filter)
            enriched["retrieval_method"] = "keyword"
            enriched["matched_terms"] = matched_terms
            scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def semantic_search_knowledge(query: str, product_filter: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    """Search literature chunks by local TF-IDF vector similarity with bilingual concept bridges."""
    chunks = [chunk for chunk in load_chunks() if _matches_product(str(chunk.get("product", "")), product_filter)]
    if not chunks:
        return []

    chunk_counters = [_semantic_counter(_chunk_search_text(chunk)) for chunk in chunks]
    idf = _idf_weights(chunk_counters)
    query_vector = _weighted_vector(_semantic_counter(query), idf, len(chunks))
    scored: list[tuple[float, dict[str, Any]]] = []

    for chunk, counter in zip(chunks, chunk_counters):
        vector = _weighted_vector(counter, idf, len(chunks))
        score = _cosine_similarity(query_vector, vector)
        if score:
            enriched = dict(chunk)
            enriched["match_score"] = round(score * 100, 4)
            enriched["keyword_score"] = 0.0
            enriched["vector_score"] = round(score, 4)
            enriched["metadata_score"] = _metadata_score(chunk, product_filter)
            enriched["retrieval_method"] = "semantic"
            enriched["matched_terms"] = []
            scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def hybrid_search_knowledge(query: str, product_filter: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    """Search with keyword recall, local semantic vector similarity, and product metadata weighting."""
    chunks = [chunk for chunk in load_chunks() if _matches_product(str(chunk.get("product", "")), product_filter)]
    if not chunks:
        return []

    expanded_query = _expand_query(query)
    query_tokens = _tokens(expanded_query)
    keyword_scores: list[float] = []
    matched_terms_by_index: list[list[str]] = []
    chunk_counters: list[Counter[str]] = []

    for chunk in chunks:
        keyword_score, matched_terms = _keyword_score(query_tokens, chunk)
        keyword_scores.append(keyword_score)
        matched_terms_by_index.append(matched_terms)
        chunk_counters.append(_semantic_counter(_chunk_search_text(chunk)))

    idf = _idf_weights(chunk_counters)
    query_vector = _weighted_vector(_semantic_counter(expanded_query), idf, len(chunks))
    max_keyword_score = max(keyword_scores) or 1.0

    scored: list[tuple[float, dict[str, Any]]] = []
    for index, chunk in enumerate(chunks):
        keyword_norm = keyword_scores[index] / max_keyword_score
        chunk_vector = _weighted_vector(chunk_counters[index], idf, len(chunks))
        vector_score = _cosine_similarity(query_vector, chunk_vector)
        metadata = _metadata_score(chunk, product_filter)
        hybrid_score = 0.46 * keyword_norm + 0.44 * vector_score + 0.10 * metadata

        if not hybrid_score:
            continue

        enriched = dict(chunk)
        enriched["match_score"] = round(hybrid_score * 100, 4)
        enriched["keyword_score"] = round(keyword_norm, 4)
        enriched["vector_score"] = round(vector_score, 4)
        enriched["metadata_score"] = round(metadata, 4)
        enriched["retrieval_method"] = "hybrid"
        enriched["matched_terms"] = matched_terms_by_index[index]
        scored.append((hybrid_score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def search_knowledge(query: str, product_filter: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    """Default RAG entry: hybrid retrieval with keyword and semantic relevance scores."""
    return hybrid_search_knowledge(query=query, product_filter=product_filter, top_k=top_k)
