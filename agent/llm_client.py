from __future__ import annotations

import importlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

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
    if any(keyword.lower() in normalized for keyword in HISTORY_REFERENCE_KEYWORDS):
        return True
    if len(normalized) <= 80 and re.search(r"(它|他|她|这个|那个|该)(?:是|和|与|为什么|怎么|有什么|能|可以|适合|指)", normalized):
        return True
    return False


def _clean_history(
    history: list[dict[str, str]],
    user_prompt: str,
    limit: int,
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
    return cleaned[-limit:]


def build_general_chat_messages(history: list[dict[str, str]], user_prompt: str) -> list[dict[str, str]]:
    system_prompt = """
你是柑橘产业链智能助手，可以回答普通大模型式问题，也可以围绕柑橘加工、陈皮、质控、文献、报告和业务沟通给出建议。
如果用户询问食品安全放行、检测合格、法规承诺、标签宣称、报价或客户承诺，必须提醒人工复核原始资料。
不要虚构检测结果、法规结论或文献来源；不确定时说明需要补充资料。
回答用中文，直接、清楚、可执行。
不要使用 Markdown 标题、加粗星号、代码块或复杂列表；用简洁段落和普通编号表达。
如果用户只是要求介绍、科普、解释某个概念，必须按通用知识回答，不要结合历史批次、示例输入或当前批次信息。
默认把每个新问题当作独立问题。只有用户明确使用“根据上面、刚才、继续、这批、当前批次、它、这个结论”等指代语义时，才引用会话历史。
演示模板、默认字段和旧批次不得被当作本轮事实；没有资料时必须说明缺少什么，不能自行补全后给结论。
""".strip()
    messages = [{"role": "system", "content": system_prompt}]
    if should_include_history(user_prompt):
        messages.extend(_clean_history(history, user_prompt, 8))
    messages.append({"role": "user", "content": user_prompt})
    return messages


def build_analysis_context(result: dict[str, Any]) -> str:
    batch = result.get("batch", {})
    scores = result.get("scores", [])
    risks = result.get("quality_risks", [])
    evidence = result.get("evidence", [])
    next_actions = result.get("next_actions", [])

    score_lines = [
        f"- {_item_value(item, 'direction')}: {_item_value(item, 'score')} 分；"
        f"原因：{'；'.join(_item_value(item, 'reasons', [])) or '暂无'}；"
        f"风险：{'；'.join(_item_value(item, 'risk_notes', [])) or '暂无'}"
        for item in scores
    ]
    risk_lines = [
        f"- [{_item_value(item, 'level')}] {_item_value(item, 'item')}：{_item_value(item, 'suggestion')}"
        for item in risks
    ]
    evidence_lines = [
        f"- {item.get('title') or '未命名文献'}（{item.get('year') or '年份未知'}，匹配分 {item.get('match_score')}）："
        f"{_shorten(item.get('chunk_text') or '', 220)}"
        for item in evidence[:5]
    ]

    context = f"""
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

加工方向评分：
{chr(10).join(score_lines) or '暂无评分'}

质控风险：
{chr(10).join(risk_lines) or '暂未触发高风险项'}

下一步动作：
{chr(10).join(f'- {item}' for item in next_actions) or '暂无'}

文献证据摘要：
{chr(10).join(evidence_lines) or '暂无文献证据'}

报告草稿摘要：
{_shorten(result.get('report') or '', 1800)}
""".strip()
    return context


def build_chat_messages(result: dict[str, Any], history: list[dict[str, str]], user_prompt: str) -> list[dict[str, str]]:
    system_prompt = """
你是柑橘产业链加工决策助手，负责解释当前批次分析结果、回答追问、生成复核清单和沟通文本。
你必须基于当前批次、规则评分、质控风险、文献证据和报告草稿回答。
不要把自己描述成最终审批人，不要给出最终检测放行、食品安全合格、可销售、可出厂、疗效或法规合规承诺。
涉及农残、重金属、微生物、黄曲霉毒素、标签、法规、报价、客户承诺时，必须提醒人工复核原始资料。
如果用户要求改变推荐方向，你可以说明条件和权衡，但不能篡改规则评分结果。
回答用中文，结构清楚，优先给可执行建议。
""".strip()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": "当前 Agent 分析上下文：\n" + build_analysis_context(result)},
    ]
    if should_include_history(user_prompt):
        messages.extend(_clean_history(history, user_prompt, 8))
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

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 1600,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        raise DeepSeekAPIError(f"DeepSeek API 请求失败：HTTP {error.code}，{detail}") from error
    except urllib.error.URLError as error:
        raise DeepSeekAPIError(f"无法连接 DeepSeek API：{error.reason}") from error
    except TimeoutError as error:
        raise DeepSeekAPIError("DeepSeek API 请求超时，请稍后重试。") from error

    try:
        return response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise DeepSeekAPIError(f"DeepSeek API 返回格式异常：{response_data}") from error
