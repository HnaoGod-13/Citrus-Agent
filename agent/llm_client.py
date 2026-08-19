from __future__ import annotations

import importlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .memory import build_context_messages, estimate_tokens, select_recent_messages, truncate_to_tokens
from .memory_config import CONTEXT_TOKEN_BUDGETS, MEMORY_RECENT_TOKEN_LIMIT
from .process_knowledge import format_processing_context
from .rag import comprehensive_search_knowledge, format_evidence_context

try:
    from . import llm_config as _llm_config
except ImportError:
    _llm_config = None


DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-pro"
HISTORY_REFERENCE_KEYWORDS = [
    "根据上面",
    "根据刚才",
    "上文",
    "上述",
    "刚才",
    "前面",
    "上一条",
    "上一个问题",
    "继续",
    "接着",
    "这批",
    "当前批次",
    "该批次",
    "这个结论",
    "这个推荐",
    "这个结果",
    "为什么这样",
    "为什么这么",
    "那它",
    "那这个",
    "按你说的",
]
HISTORY_RESET_KEYWORDS = ["忽略上文", "不要参考上文", "不结合前文", "重新开始一个话题"]
LITERATURE_DOMAIN_KEYWORDS = [
    "柑橘", "陈皮", "广陈皮", "茶枝柑", "橙", "柑", "橘", "柚", "柠檬",
    "果汁", "橙汁", "nfc", "果肉", "果皮", "果胶", "精油", "黄酮", "种子", "籽油",
    "副产物", "果渣", "加工", "工艺", "流程", "参数", "提取", "清洗", "榨汁", "均质",
    "脱气", "杀菌", "灌装", "包装", "温度", "时间", "压力", "流量", "浓度", "干燥",
    "发酵", "陈化", "贮藏", "储藏", "质控",
    "农残", "重金属", "微生物", "黄曲霉", "文献", "论文", "研究", "依据", "来源", "参考文献",
    "citrus", "chenpi", "pectin", "essential oil", "pasteurization", "deaeration", "filling",
]


class DeepSeekAPIError(RuntimeError):
    pass


def get_deepseek_api_key() -> str:
    configured_key = ""
    if _llm_config is not None:
        try:
            module = importlib.reload(_llm_config)
            configured_key = getattr(module, "DEEPSEEK_API_KEY", "")
        except Exception:
            configured_key = getattr(_llm_config, "DEEPSEEK_API_KEY", "")
    return (configured_key or os.getenv("DEEPSEEK_API_KEY", "")).strip()


def _item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _shorten(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def should_include_history(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", "", user_prompt.lower())
    return not any(keyword.lower() in normalized for keyword in HISTORY_RESET_KEYWORDS)


def explicitly_references_history(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", "", user_prompt.lower())
    if not should_include_history(user_prompt):
        return False
    if any(keyword.lower() in normalized for keyword in HISTORY_REFERENCE_KEYWORDS):
        return True
    if len(normalized) <= 80 and re.search(
        r"(?:单独|列出|整理|给我|发我|引用|用到).*(?:文献|依据|来源|结论|方案)|"
        r"(?:产地|品种|糖度|brix|酸度|水分|重量|客户|农残|重金属|微生物|黄曲霉).{0,12}"
        r"(?:改成|调整为|更正为|更新为|补充|改为)|"
        r"(它|他|她|这个|那个|该)(?:是|和|与|为什么|怎么|有什么|能|可以|适合|指)",
        normalized,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _clean_history(
    history: list[dict[str, str]],
    user_prompt: str,
    limit: int,
    token_budget: int = MEMORY_RECENT_TOKEN_LIMIT,
) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    current = user_prompt.strip()
    for item in history:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "user" and content == current:
            continue
        cleaned.append({"role": role, "content": content})
    return select_recent_messages(cleaned[-limit:], token_budget)


def _should_retrieve_literature(user_prompt: str) -> bool:
    normalized = user_prompt.lower()
    return any(keyword.lower() in normalized for keyword in LITERATURE_DOMAIN_KEYWORDS)


def _retrieval_query_with_history(history: list[dict[str, str]], user_prompt: str) -> str:
    normalized = re.sub(r"\s+", "", user_prompt)
    is_short_follow_up = len(normalized) <= 50 and (
        any(keyword in normalized for keyword in HISTORY_REFERENCE_KEYWORDS)
        or re.search(r"(?:把|将|给我|列出|整理|展开|详细).*(?:文献|依据|来源|方案|结论)", normalized)
        or re.search(r"(?:文献|依据|来源|方案|结论).*(?:给我|列出|整理|展开|详细)", normalized)
        or re.search(r"(?:有|查|找|看|给).{0,8}(?:证据|文献|依据|来源)", normalized)
    )
    if not is_short_follow_up:
        return user_prompt
    for item in reversed(history):
        if item.get("role") == "user" and str(item.get("content") or "").strip():
            return f"{item['content']} {user_prompt}"
    return user_prompt


def retrieve_general_literature(
    user_prompt: str,
    top_k: int = 10,
    history: list[dict[str, str]] | None = None,
    *,
    retrieval_mode: str = "quick",
    return_metadata: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    query = _retrieval_query_with_history(history or [], user_prompt)
    should_retrieve = _should_retrieve_literature(user_prompt)
    if retrieval_mode == "deep" and query != user_prompt:
        should_retrieve = should_retrieve or _should_retrieve_literature(query)
    if not should_retrieve:
        if return_metadata:
            return {
                "evidence": [],
                "deep_retrieval_stats": {
                    "retrieval_mode": retrieval_mode,
                    "selected_count": 0,
                    "selected_document_count": 0,
                },
            }
        return []
    return comprehensive_search_knowledge(
        query,
        product_filter="不限",
        top_k=top_k,
        retrieval_mode=retrieval_mode,
        return_metadata=return_metadata,
    )


def _format_evidence_with_budget(evidence: list[dict[str, Any]], excerpt_chars: int) -> str:
    rendered = format_evidence_context(evidence, excerpt_chars=excerpt_chars)
    return truncate_to_tokens(rendered, CONTEXT_TOKEN_BUDGETS["literature"])


def build_general_chat_messages(
    history: list[dict[str, str]],
    user_prompt: str,
    *,
    memory_context: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    retrieval_mode: str = "quick",
) -> list[dict[str, str]]:
    system_prompt = """
你是柑橘产业链智能助手，可以回答普通大模型式问题，也可以围绕柑橘加工、陈皮、质控、文献、报告和业务沟通给出建议。
如果用户询问食品安全放行、检测合格、法规承诺、标签宣称、报价或客户承诺，必须提醒人工复核原始资料。
不要虚构检测结果、法规结论或文献来源；不确定时说明需要补充资料。
回答用中文，直接、清楚、可执行。
不要使用 Markdown 标题、加粗星号、代码块或复杂列表；用简洁段落和普通编号表达。
凡系统提供了本地文献证据，优先依据证据中的研究对象、处理条件、检测指标、结果和局限回答，避免只给通用常识。
把证据综合进论证，不要机械粘贴片段；每个由文献支持的关键判断后用“[文献1]”格式标注对应编号。宽泛问题尽量综合至少 3 篇不同文献。
答案末尾增加“本次引用文献”，只列正文实际用到的编号、题名、年份、页码和 DOI（没有 DOI 就列本地来源）；不得编造题录信息。
严格区分“文献直接结论”“基于文献的推断”和“建议”。体外、动物、网络药理或相关性研究不得写成人体疗效或确定因果；不同文献结论不一致时要说明差异。
系统提供的内容有四种来源，回答时必须严格区分：当前用户输入是当前事实；历史样本只能作为类比案例；本地文献是外部证据；长期记忆和模型推断不能冒充当前事实。出现冲突时，以用户最新明确确认的当前信息为准，并指出冲突。
遇到“它、这个品种、这个方案、上一个样本”等指代，先结合结构化工作记忆、摘要和最近原始对话解析；仍有两个以上合理对象时再向用户澄清，不要直接说没有上下文。
只有证据片段明确给出且适用条件一致时，才能引用温度、时间、浓度、得率等数值；同时交代对象与条件，不得把单篇研究参数直接包装成通用生产标准。
若证据章节标记为“题录（待OCR）”，只能说明库中存在该题名，不能把题名推测成研究结果或结论。
如果回答包含明确的加工方向、方案或工艺建议，必须在建议句后立即给出完整加工流程，至少写清原料准入、分选前处理、核心加工、稳定化包装、成品检测与人工放行；不得只给加工方向。
同一对话中的历史消息会作为短期记忆提供给你。先判断本轮是追问、补充、更正还是新话题：追问时必须承接前文；新话题时只回答新问题，不得把旧批次事实硬套进来。只有用户明确要求忽略上文时才丢弃历史。
如果用户只是要求介绍、科普、解释某个概念，应按其当前问题回答；除非有明确指代，不要主动套用历史批次数据。
演示模板、默认字段和旧批次不得被当作本轮事实；没有资料时必须说明缺少什么，不能自行补全后给结论。
    """.strip()
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_context_messages(memory_context))
    if evidence is None:
        retrieval = retrieve_general_literature(
            user_prompt,
            top_k=24 if retrieval_mode == "deep" else 10,
            history=history,
            retrieval_mode=retrieval_mode,
            return_metadata=retrieval_mode == "deep",
        )
        evidence = list(retrieval.get("evidence") or []) if isinstance(retrieval, dict) else retrieval
    if evidence:
        mode_note = (
            "本轮已启用全库深度检索：候选来自完整本地索引的多轮聚焦召回，"
            "但只把经重排和去重后的证据片段放入模型上下文。\n"
            if retrieval_mode == "deep"
            else ""
        )
        messages.append(
            {
                "role": "system",
                "content": (
                    mode_note
                    +
                    "以下是本轮从本地文献数据库检索并重排后的证据。只引用这些片段实际支持的内容；"
                    "页码用于回查原文，不代表已完成全文人工复核。\n\n"
                    + _format_evidence_with_budget(
                        evidence,
                        excerpt_chars=460 if retrieval_mode == "deep" else 700,
                    )
                ),
            }
        )
    if should_include_history(user_prompt):
        recent = (memory_context or {}).get("recent_messages")
        messages.extend(recent if recent is not None else _clean_history(history, user_prompt, 100))
    messages.append({"role": "user", "content": user_prompt})
    return messages


def build_analysis_context(result: dict[str, Any]) -> str:
    batch = result.get("batch", {})
    scores = result.get("scores", [])
    risks = result.get("quality_risks", [])
    evidence = result.get("evidence", [])
    next_actions = result.get("next_actions", [])
    processing_plan = result.get("processing_plan", {})
    retrieval_mode = str(result.get("retrieval_mode") or "quick")
    retrieval_stats = result.get("deep_retrieval_stats") or {}
    processing_context = format_processing_context(
        result.get("processing_intent") or {},
        result.get("parameter_groups") or [],
        result.get("processing_evidence") or evidence,
    )
    vision_status = str(result.get("vision_status") or "not_requested")
    vision_status_text = {
        "success": "已接收图片，并已完成视觉模型分析",
        "failed": "已接收图片，但视觉模型分析失败",
        "missing_bytes": "页面显示选择了图片，但服务端未读取到图片数据",
        "not_requested": "本轮未调用视觉模型",
    }.get(vision_status, vision_status)

    score_lines = [
        f"- {_item_value(item, 'direction')}：{_item_value(item, 'match_level', '待评估')}；"
        f"文献支持：{_item_value(item, 'evidence_support', '未评估')}；"
        f"数据置信度：{_item_value(item, 'data_confidence', '低')}；"
        f"原因：{'；'.join(_item_value(item, 'reasons', [])) or '暂无'}；"
        f"风险：{'；'.join(_item_value(item, 'risk_notes', [])) or '暂无'}"
        for item in scores
    ]
    risk_lines = [
        f"- [{_item_value(item, 'level')}] {_item_value(item, 'item')}：{_item_value(item, 'suggestion')}"
        for item in risks
    ]
    evidence_lines = []
    evidence_tokens = 0
    evidence_limit = 24 if retrieval_mode == "deep" else 16
    excerpt_limit = 420 if retrieval_mode == "deep" else 560
    for index, item in enumerate(evidence[:evidence_limit], 1):
        page = item.get("page") or item.get("page_start") or "未标注"
        line = (
            f"- [文献{index}] {item.get('title') or '未命名文献'}"
            f"（{item.get('year') or '年份未知'}；{item.get('category') or item.get('product') or '未分类'}；"
            f"{item.get('section') or '正文'}；第{page}页；匹配分 {item.get('match_score')}）："
            f"{_shorten(item.get('chunk_text') or '', excerpt_limit)}"
        )
        line_tokens = estimate_tokens(line)
        remaining = CONTEXT_TOKEN_BUDGETS["literature"] - evidence_tokens
        if remaining <= 0:
            break
        if line_tokens > remaining:
            line = truncate_to_tokens(line, remaining)
        evidence_lines.append(line)
        evidence_tokens += estimate_tokens(line)
    plan_lines = [
        f"- {stage.get('name')}："
        f"{' → '.join(str(step) for step in stage.get('steps', []))}；"
        f"操作要点：{stage.get('operation')}；"
        f"质控要求：{stage.get('control')}；"
        f"必留记录：{stage.get('record')}"
        for stage in processing_plan.get("stages", [])
    ]

    context = f"""
本轮用户问题：
{result.get('analysis_question') or '未单独记录，按当前批次做综合分析'}

文献检索模式：
- 模式：{'全库深度检索' if retrieval_mode == 'deep' else '快速检索'}
- 全库索引范围：{retrieval_stats.get('library_document_count') or '未记录'} 篇文献，{retrieval_stats.get('library_chunk_count') or '未记录'} 个片段
- 正文可用性：{retrieval_stats.get('library_usable_document_count') or '未记录'} 篇可用；{retrieval_stats.get('library_ocr_document_count') or '未记录'} 篇待 OCR
- 本轮候选与采用：候选 {retrieval_stats.get('database_candidates') or 0} 个片段；采用 {retrieval_stats.get('selected_count') or len(evidence)} 个片段，来自 {retrieval_stats.get('selected_document_count') or '未记录'} 篇文献
- 待 OCR 排除：{retrieval_stats.get('ocr_filtered_count') or 0}；相邻方法/结果补充：{retrieval_stats.get('adjacent_added_count') or 0}
- 边界：全库深度检索表示完整索引均可参与多轮召回，不表示把全部文献正文同时发送给模型。

当前批次：
- 批次号：{batch.get('batch_id')}
- 产地：{batch.get('origin')}
- 品种：{batch.get('variety')}
- 采收日期：{batch.get('harvest_date')}
- 重量：{batch.get('weight_kg')} kg
- 糖度 Brix：{batch.get('brix')}
- 酸度：{batch.get('acidity')}
- 水分：{batch.get('moisture')}%
- 目标客户：{batch.get('customer_type')}
- 检测状态：农残={batch.get('pesticide')}，重金属={batch.get('heavy_metal')}，微生物={batch.get('microbe')}，黄曲霉毒素={batch.get('aflatoxin')}

外观描述：
{result.get('image_observation') or '未填写'}

图片与视觉模型状态：
- 状态：{vision_status_text}
- 视觉模型针对用户问题的回答：{result.get('vision_answer') or '无'}
- 调用错误：{result.get('vision_error') or '无'}

加工方向分级排序（不使用伪精确百分制）：
{chr(10).join(score_lines) or '暂无路线分级'}

完整加工流程（方案）：
- 目标产品：{processing_plan.get('product_form') or '待确认'}
- 全流程：{' → '.join(str(step) for step in processing_plan.get('flow', [])) or '待确认'}
{chr(10).join(plan_lines) or '- 暂无结构化方案'}

质控风险：
{chr(10).join(risk_lines) or '暂未触发高风险项'}

下一步动作：
{chr(10).join(f'- {item}' for item in next_actions) or '暂无'}

文献证据摘要：
{chr(10).join(evidence_lines) or '暂无文献证据'}

面向加工工艺的结构化证据（严格保留条件和来源）：
{processing_context}

报告草稿摘要：
{_shorten(result.get('report') or '', 1800)}
""".strip()
    return context


def build_chat_messages(
    result: dict[str, Any],
    history: list[dict[str, str]],
    user_prompt: str,
    *,
    memory_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    system_prompt = """
你是柑橘产业链加工决策助手，负责生成当前批次的完整主回答，而不是在通用模板后追加几句说明。
你必须基于当前批次、分级路线排序、质控风险、文献证据和报告草稿回答。
回答应形成“批次事实—文献证据—综合判断—完整流程—风险与行动”的闭环，让用户能直接看出文献如何影响分析。
文献证据不是装饰：说明推荐理由、工艺关注点或风险时，应综合最相关的研究对象、条件、结果与局限，并在相应判断后标注“[文献N]”。
必须区分四类来源：当前批次和用户本轮输入是当前事实；相似历史样本仅用于类比；文献片段是证据；长期记忆与模型推断不得写成当前批次检测事实。若来源冲突，以用户最新明确确认的信息为准并显式说明。
遇到“它、这个品种、这个方案、上一个样本”等指代，应先使用结构化工作记忆、增量摘要和最近原始对话消解，不要无故要求用户重复已经提供过的信息。
回答末尾列出正文实际引用的文献编号、题名、年份、页码和 DOI/本地来源，便于用户回查。
任何药典、法规、标准、行业共识、具体参数或研究结论，都必须由当前提供的文献证据明确支持，并在相关句后紧邻标注“[文献N]”；当前证据没有覆盖时，明确写“当前证据未覆盖，待人工核实”，不得依赖模型记忆补充。
当用户询问加工方案时，回答至少包含：一、加工目标与适用性判断；二、推荐工艺流程；三、详细操作参数表；四、设备需求；五、质量控制指标；六、风险与注意事项；七、参考文献及证据可信度；八、仍需补充的信息。参数表必须含步骤、操作说明、推荐参数、可调整范围、关键控制点和证据来源。
结构化参数证据中的“文献直接报告”只能复述为对应研究条件；“多文献归纳”才可表述为有条件推荐范围；工程配置或模型推断必须显式标为推断。高、中、低可信度要显示，实验室、中试、工业和 unknown 规模不得混写。
不同文献参数冲突时列出主要方案及各自原料、方法、规模和条件，不得求平均或静默合并。单位缺失、适用条件不明或标记为不可推荐的参数，不得写入生产参数。
宽泛结论优先交叉使用多篇不同文献；不得把单篇论文、体外实验、动物实验、网络药理或相关性结果夸大为通用生产结论或人体疗效。
若文献只支持方向而不足以确定生产参数，应明确写成“小试候选范围/需原文和企业 SOP 复核”，不要退化成空泛套话，也不要编造数值。
标记为“题录（待OCR）”的条目没有可用正文，只能作为待人工补录线索，不得用于证明结论。
不要把自己描述成最终审批人，不要给出最终检测放行、食品安全合格、可销售、可出厂、疗效或法规合规承诺。
涉及农残、重金属、微生物、黄曲霉毒素、标签、法规、报价、客户承诺时，必须提醒人工复核原始资料。
若“图片与视觉模型状态”明确为已完成，必须承认图片已接收且视觉结果可用，禁止声称“未收到图片、未检测到图片或没有识别调用结果”；只能对视觉判断本身的能力边界作说明。
如果用户要求改变推荐方向，你可以说明条件和权衡，但不能篡改规则与文献共同形成的分级排序结果。
回答用中文，结构清楚，优先给可执行建议。
""".strip()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]
    messages.extend(build_context_messages(memory_context))
    messages.append({"role": "system", "content": "当前 Agent 分析上下文：\n" + build_analysis_context(result)})
    if explicitly_references_history(user_prompt):
        recent = (memory_context or {}).get("recent_messages")
        messages.extend(recent if recent is not None else _clean_history(history, user_prompt, 100))
    messages.append({"role": "user", "content": user_prompt})
    return messages


def chat_with_deepseek(
    api_key: str,
    messages: list[dict[str, str]],
    model: str = DEEPSEEK_MODEL,
    timeout: int = 90,
) -> str:
    if not api_key.strip():
        raise DeepSeekAPIError("请先在 agent/llm_config.py 中填入 DeepSeek API Key。")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 8000,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }

    def request_completion(request_payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            DEEPSEEK_API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise DeepSeekAPIError(
                f"DeepSeek API 请求失败：HTTP {error.code}，{detail}"
            ) from error
        except urllib.error.URLError as error:
            raise DeepSeekAPIError(f"无法连接 DeepSeek API：{error.reason}") from error
        except TimeoutError as error:
            raise DeepSeekAPIError("DeepSeek API 请求超时，请稍后重试。") from error
        if not isinstance(response_data, dict):
            raise DeepSeekAPIError("DeepSeek API 返回格式异常：顶层结果不是对象。")
        return response_data

    def final_content(response_data: dict[str, Any]) -> str:
        try:
            content = response_data["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise DeepSeekAPIError("DeepSeek API 返回格式异常：缺少最终回答字段。") from error
        return str(content or "").strip()

    response_data = request_completion(payload)
    answer = final_content(response_data)
    if answer:
        return answer

    retry_payload = dict(payload)
    retry_payload["thinking"] = {"type": "disabled"}
    retry_payload["max_tokens"] = 4800
    retry_payload.pop("reasoning_effort", None)
    retry_response = request_completion(retry_payload)
    answer = final_content(retry_response)
    if answer:
        return answer

    finish_reason = str(
        (retry_response.get("choices") or [{}])[0].get("finish_reason") or "unknown"
    )
    raise DeepSeekAPIError(
        f"DeepSeek API 未返回可展示的最终回答（finish_reason={finish_reason}）。"
    )
