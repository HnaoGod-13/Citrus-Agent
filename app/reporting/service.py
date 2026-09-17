"""High quality, evidence-grounded project report service."""
from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from agent.llm_client import DeepSeekAPIError, chat_with_deepseek, get_deepseek_api_key
from app.intake_pipeline import flatten_intake
from .web_search import search_web


SECTIONS = [
    "项目摘要", "项目背景", "项目建设必要性", "原料与批次基本情况", "产地与品种产业分析",
    "市场需求与竞争环境", "加工路线和工艺方案", "项目建设内容", "设备、产能和场地需求",
    "质量安全与合规方案", "副产物综合利用", "投资估算与资金使用方向", "运营模式和收益逻辑",
    "实施计划", "风险分析与应对措施", "结论和立项建议", "参考资料", "待人工复核项",
]

_PROFILE_FIELDS = (
    "title", "agency", "department", "preparedBy", "region", "period",
    "purpose", "template", "templateFile",
)


def build_research_queries(facts: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    origin, variety, target = facts.get("origin") or "", facts.get("variety") or "", facts.get("target_product") or ""
    region = profile.get("region") or origin
    queries = [
        f"{origin} {variety} 产量 统计 年鉴 官方",
        f"{variety} 品种 特点 营养 加工 研究 论文",
        f"{target or '柑橘加工'} 市场需求 产业发展 报告",
        f"{variety} 果汁 加工 工艺 质量安全 标准",
        f"{region} 柑橘 产业链 项目 建设 政策",
    ]
    return [q for q in queries if q.strip()]


def _local_sources(document: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    enrichment = analysis.get("report_enrichment") if isinstance(analysis, dict) else {}
    evidence = enrichment.get("evidence", []) if isinstance(enrichment, dict) else []
    return [dict(item, source_type=item.get("source_type") or "local") for item in evidence if isinstance(item, dict)][:12]


def _source_text(sources: list[dict[str, Any]]) -> str:
    lines = []
    for i, source in enumerate(sources, 1):
        title = str(source.get("title") or source.get("document_title") or "未命名来源")[:300]
        url = str(source.get("url") or source.get("source") or "")[:1000]
        snippet = str(source.get("snippet") or source.get("abstract") or source.get("content") or "")[:1600]
        lines.append(f"[{i}] {title}\nURL: {url}\n摘要: {snippet}")
    return "\n\n".join(lines)


def _fallback_report(facts: dict[str, Any], analysis: dict[str, Any], profile: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    route = (analysis.get("recommended_route") or {}).get("label") or "待补充"
    score = (analysis.get("cleaning") or {}).get("weighted_score", "待评估")
    stages = "、".join((analysis.get("processing_plan") or {}).get("stages") or []) or "待工艺评审"
    title = profile.get("title") or "柑橘产业项目报告"
    facts_line = f"{facts.get('origin') or '待补充'}的{facts.get('variety') or '柑橘'}，批次 {facts.get('batch') or '待补充'}，数量 {facts.get('quantity_kg') or '待补充'} kg，目标产品为 {facts.get('target_product') or '待补充'}。"
    source_lines = [f"- {s.get('title') or s.get('document_title') or '来源'}：{s.get('url') or s.get('source') or '本地证据'}" for s in sources]
    return f"""# {title}

## 项目摘要
本报告依据正式提交的单条采集记录编制，围绕{facts_line}形成项目论证初稿。系统清洗后的加权数据质量分为 {score}/100，当前推荐路线为“{route}”。报告中没有提交依据的产量、价格、投资额和收益率均标注为待测算，不能直接替代可研批复。

## 项目背景
柑橘鲜果具有明显的季节性和区域性，建设稳定的加工和质量控制能力，有助于把原料供应、加工过程、产品销售和副产物利用连接起来。项目正式立项前，应补充当地统计年鉴、企业历史采购量、目标市场订单和建设条件。

## 项目建设必要性
本批次已经形成产地、品种、数量和质量字段，可作为项目底稿。项目必要性主要体现在延长产业链、提高原料利用率、降低鲜果集中上市造成的销售波动，并通过检测、批次追溯和标准化工艺提升产品稳定性。

## 原料与批次基本情况
{facts_line}糖度 {facts.get('brix') or '待补充'} °Brix，酸度 {facts.get('acidity') or '待补充'}，安全检测资料为 {'；'.join(facts.get('safety_tests') or []) or '待补充'}。上述内容来自用户正式提交记录，后续应与原始附件逐项核对。

## 产地与品种产业分析
产地、品种的产量、种植面积、价格和产业规模需要以官方统计和可核验文献为准。当前检索结果只作为研究线索，不能把搜索摘要直接视为当地事实。建议在可研阶段补充连续三年产量、收购价和加工企业名录。

## 市场需求与竞争环境
目标产品的市场规模、竞争产品、渠道和价格尚未由本条记录直接提供。建议以客户访谈、订单、平台销售数据和行业报告建立需求边界，先确定区域市场，再评估全国市场扩张。

## 加工路线和工艺方案
系统推荐路线为“{route}”，建议工艺阶段为：{stages}。本方案用于路线评审和小试设计，具体温度、时间、压力、配方和放行指标必须以企业批准的SOP、法规标准及小试验证结果为准，不能直接作为生产参数。

## 项目建设内容
建设内容建议包括原料验收区、分选清洗区、核心加工区、包装区、成品库、质量检验室、污水和副产物处理设施，以及批次追溯和文件管理系统。最终建设规模需根据供应半径、设备能力和订单测算。

## 设备、产能和场地需求
设备清单、产能、厂房面积、能耗和人员编制当前缺少正式参数。建议先以单批处理能力和旺季日处理量为边界开展设备询价，再形成可比选的投资估算表。

## 质量安全与合规方案
应建立供应商准入、原料验收、过程监控、成品放行、留样和召回制度；涉及食品生产许可、农残、重金属、微生物和标签要求的内容，须按项目所在地和产品类别核对现行官方规定。

## 副产物综合利用
果皮、果渣和不合格品应分类收集，优先评估果胶、精油、饲料或有机肥方向。每个方向都要先做成分检测、稳定性和经济性小试，再决定是否建设配套线。

## 投资估算与资金使用方向
本批次未提交厂房、设备、土地、建设周期和融资条件，因此不虚构投资金额。建议将资金分为厂房改造、设备购置、检验与信息化、环保设施、流动资金和预备费，并以询价和工程量清单测算。

## 运营模式和收益逻辑
可采用“订单牵引+稳定供应+分级加工+副产物利用”的运营模式。收益测算需同时考虑原料采购、损耗率、包装、人工、能源、检测、物流、销售费用和税费，形成保守、基准、乐观三种情景。

## 实施计划
建议按“补充资料—小试验证—设备与厂房方案—投资测算—合规审查—试生产—验收投产”推进。每一步应明确责任人、输入资料、输出文件和通过标准。

## 风险分析与应对措施
主要风险包括原料季节性、质量波动、市场价格变化、工艺放大失败、合规资料缺失和现金流压力。应通过多来源采购、批次检测、分阶段投资、订单锁定和风险预留降低影响。

## 结论和立项建议
该批次具备进入项目方案论证和小试验证的基础，但投资额、产能、市场规模和收益率仍需补充证据后确认。建议先立项开展补充调查与小试，不建议在当前资料不足时直接作出固定投资承诺。

## 参考资料
{chr(10).join(source_lines) if source_lines else '- 互联网检索暂未返回可核验来源，需补充官方统计和论文文献。'}

## 待人工复核项
- 核对产地、品种、批次、数量、糖度和检测附件；
- 补充当地近三年产量、价格和产业政策；
- 补充建设地点、厂房、设备、产能、投资和资金来源；
- 由工艺、质量、财务和法务人员共同审阅后定稿。
"""


def _llm_report(facts: dict[str, Any], analysis: dict[str, Any], profile: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    api_key = get_deepseek_api_key()
    if not api_key:
        raise DeepSeekAPIError("未配置 DeepSeek API Key")
    prompt = f"""你是农业食品项目可研报告总撰稿人。请根据以下正式提交的单条批次事实、系统清洗和路线结果、互联网及本地证据，撰写一份可直接交给项目评审、申报或投资沟通前审阅的中文《项目报告》。

硬性要求：
1. 只写输入事实和来源支持的内容；没有数据就写“待补充/待测算”，绝不编造统计数字、价格、法规、论文或投资金额。
2. 把正式提交记录中的事实、外部来源结论、你的工程判断分开表达；重要外部结论在句末用[来源编号]标注。
3. 需要完整连贯的正文和必要表格，不能只给提纲。按以下18个二级标题输出：{"、".join(SECTIONS)}。
4. 工艺参数只能写成小试建议或待验证范围，不能把单篇文献参数写成生产标准。
5. 项目报告只能有一个报告类型，语言正式、审慎、可编辑，篇幅尽量充分。

报告配置：{json.dumps(profile, ensure_ascii=False)}
批次事实：{json.dumps(facts, ensure_ascii=False)}
系统分析：{json.dumps(analysis, ensure_ascii=False)}
来源证据：
{_source_text(sources)}
"""
    return chat_with_deepseek(api_key, [{"role": "system", "content": "你输出严谨、可核验、中文正式项目报告。"}, {"role": "user", "content": prompt}])


def generate_project_report(
    *,
    task_id: str,
    record_id: str,
    document: dict[str, Any],
    analysis: dict[str, Any],
    profile: dict[str, Any] | None = None,
    template_path: str | Path | None = None,
    output_dir: str | Path = "output/reports",
    web_searcher: Callable[[list[str]], dict[str, Any]] = search_web,
    llm_writer: Callable[[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]], str] | None = None,
) -> dict[str, Any]:
    raw_profile = profile or {}
    # Browser state may also contain a base64 Word file, a previous report and
    # earlier sources.  None of that belongs in the LLM prompt.
    profile = {key: str(raw_profile.get(key) or "")[:4000] for key in _PROFILE_FIELDS}
    profile.update(
        title=profile.get("title") or "柑橘产业项目报告",
        report_type="项目报告",
        reportType="项目报告",
    )
    facts = (analysis.get("cleaning") or {}).get("normalized") or flatten_intake(document)
    local = _local_sources(document, analysis)
    web = web_searcher(build_research_queries(facts, profile))
    sources = local[:8] + list(web["evidence"])[:16]
    report_analysis = {
        key: analysis.get(key)
        for key in ("cleaning", "routes", "recommended_route", "processing_plan", "batch_summary", "pipeline_version")
    }
    enrichment = analysis.get("report_enrichment") or {}
    report_analysis["report_enrichment"] = {
        key: enrichment.get(key)
        for key in ("research_status", "variety_insight", "queries")
        if key in enrichment
    }
    report_analysis["web_research"] = {
        "status": web.get("status"),
        "queries": web.get("queries", []),
        "errors": web.get("errors", []),
        "evidence_count": len(web.get("evidence", [])),
    }
    # A report requested by the user must be an LLM-authored report.  Missing
    # credentials or API failures are surfaced instead of silently returning a
    # fixed template that looks like a completed report.
    markdown = (llm_writer or _llm_report)(facts, report_analysis, profile, sources)
    if len(str(markdown).strip()) < 1200:
        raise DeepSeekAPIError("大模型返回的报告过短，未达到项目报告生成要求，请重试。")
    generation_mode = "injected_llm" if llm_writer else "deepseek"
    report_id = "report_" + uuid4().hex[:24]
    # Keep the main workspace importable when an old runtime has not installed
    # the optional Word dependency yet; deployment installs python-docx from
    # requirements before this path is used.
    from .docx_export import markdown_to_docx
    out_dir = Path(output_dir)
    docx_path = out_dir / f"{report_id}.docx"
    markdown_path = out_dir / f"{report_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    markdown_to_docx(markdown, docx_path, profile=profile, template_path=template_path, sources=sources)
    result = {
        "report_id": report_id, "task_id": task_id, "record_id": record_id,
        "status": "completed", "generation_mode": generation_mode, "llm_used": True,
        "markdown": markdown, "sources": sources, "web_search": web,
        "docx_path": str(docx_path.resolve()), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    result["docx_base64"] = base64.b64encode(docx_path.read_bytes()).decode("ascii")
    return result


__all__ = ["generate_project_report", "build_research_queries"]
