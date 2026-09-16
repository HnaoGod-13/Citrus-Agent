"""Batch report enrichment using the local literature index with safe fallback facts."""
from __future__ import annotations

from typing import Any

from app.intake_pipeline import clean_intake_record


VARIETY_FACTS = {
    "沃柑": "通常以鲜食和果汁加工为主要方向；报告应结合糖酸比、出汁率、果皮利用和冷链条件评价，不直接承诺产量或功效。",
    "脐橙": "常见用途包括鲜食、原汁和浓缩汁；产地规模、商品果率、糖酸比和采后损耗是项目测算的关键变量。",
    "茶枝柑": "常见于果皮、陈皮及综合利用场景；果皮完整度、水分、农残资料和陈化条件决定后续路线适配性。",
    "脐橙鲜果": "常见用途包括鲜食、原汁和浓缩汁；产地规模、商品果率、糖酸比和采后损耗是项目测算的关键变量。",
}


def build_research_queries(facts: dict[str, Any]) -> list[str]:
    origin, variety, product = facts.get("origin"), facts.get("variety"), facts.get("target_product")
    queries = []
    if variety:
        queries.append(f"{variety} 品种 特性 糖酸比 产量 采后加工")
    if origin:
        queries.append(f"{origin} 柑橘 产量 产业规模 统计")
    if product:
        queries.append(f"{variety or '柑橘'} {product} 加工工艺 质量控制")
    return queries


def enrich_report_context(document: dict[str, Any], *, searcher=None, top_k: int = 6) -> dict[str, Any]:
    cleaned = clean_intake_record(document)
    facts = cleaned["normalized"]
    queries = build_research_queries(facts)
    evidence: list[dict[str, Any]] = []
    if searcher:
        for query in queries:
            try:
                result = searcher(query, top_k=top_k)
                if isinstance(result, dict):
                    result = result.get("evidence", [])
                evidence.extend(result or [])
            except Exception:
                continue
    variety = str(facts.get("variety") or "")
    fallback = VARIETY_FACTS.get(variety) or "当前品种缺少可直接复用的本地概览，报告会保留为待检索项并提示补充官方统计来源。"
    return {
        "facts": {k: facts.get(k) for k in ("origin", "variety", "batch", "quantity_kg", "brix", "acidity", "moisture", "target_product")},
        "queries": queries,
        "evidence": evidence[:top_k],
        "variety_insight": fallback,
        "research_status": "已完成本地文献检索" if evidence else "待补充外部统计或本地文献",
        "caveat": "产量、市场规模和品种优势必须在报告定稿前以官方统计、检测报告或可核验文献复核。",
    }


__all__ = ["enrich_report_context", "build_research_queries"]
