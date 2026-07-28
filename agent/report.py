from __future__ import annotations

from datetime import datetime
from typing import Any

from .rules import (
    DIRECTION_BYPRODUCT,
    DIRECTION_CONCENTRATE,
    DIRECTION_JUICE,
    DIRECTION_PARTS,
    DIRECTION_PEEL,
    DIRECTION_PEEL_FLAVONOID,
    DIRECTION_PEEL_OIL,
    DIRECTION_PEEL_PECTIN,
    DIRECTION_PULP_DRINK,
    DIRECTION_SEED,
    DIRECTION_SEGMENT,
    DIRECTION_SHRED,
    DIRECTION_VINEGAR_WINE,
    DIRECTION_WHOLE_DRY,
    DIRECTION_WHOLE_MEDICINAL,
    DIRECTION_WHOLE_POWDER_TEA,
    DIRECTION_WHOLE_PRESERVE,
    QualityRisk,
    ScoreResult,
)


FORBIDDEN_CLAIMS = ["治疗", "治愈", "降血糖", "降血压", "包治", "无农残", "绝对安全", "最好", "第一"]

FLOW_MAP = {
    DIRECTION_PEEL: ["原料验收", "分选剔除", "清洗", "开皮取皮", "干燥", "分级", "入仓陈化", "检测复核", "包装建档"],
    DIRECTION_SHRED: ["原料验收", "分选", "取皮干燥", "切丝/粉碎", "筛分", "异物检查", "微生物检测", "包装", "留样建档"],
    DIRECTION_PEEL_OIL: ["果皮验收", "清洗破碎", "冷压或蒸馏", "油水分离", "脱萜或调配", "稳定性检测", "避光包装"],
    DIRECTION_PEEL_PECTIN: ["皮渣验收", "清洗破碎", "酸提或酶提", "过滤浓缩", "醇沉/分离", "干燥粉碎", "标准化检测"],
    DIRECTION_PEEL_FLAVONOID: ["果皮验收", "干燥粉碎", "溶剂或水提", "纯化浓缩", "干燥制粉", "成分检测", "合规应用评审"],
    DIRECTION_JUICE: ["原料验收", "清洗分选", "榨汁", "过滤/均质", "杀菌", "无菌灌装", "稳定性观察", "微生物检测"],
    DIRECTION_CONCENTRATE: ["原料验收", "榨汁过滤", "低温真空浓缩", "冷冻或膜浓缩复核", "调配", "杀菌灌装", "稳定性检测"],
    DIRECTION_VINEGAR_WINE: ["原料验收", "榨汁澄清", "糖酸调整", "接种发酵", "过滤陈酿", "杀菌", "灌装留样"],
    DIRECTION_SEGMENT: ["原料验收", "去皮分瓣", "去囊衣", "分级装罐", "加糖液", "杀菌", "密封检漏", "商业无菌复核"],
    DIRECTION_PULP_DRINK: ["原料验收", "去皮分瓣", "分离砂囊/果粒", "调配均质", "杀菌", "灌装", "沉淀和口感复核"],
    DIRECTION_WHOLE_PRESERVE: ["整果验收", "清洗预处理", "糖渍或蜂蜜腌制", "低温干燥", "成品分级", "水分和微生物检测"],
    DIRECTION_WHOLE_DRY: ["整果验收", "清洗切片", "冷冻干燥或烘干", "筛选分级", "防潮包装", "留样建档"],
    DIRECTION_WHOLE_POWDER_TEA: ["整果验收", "清洗切片", "干燥", "粉碎筛分", "拼配或制茶", "包装", "风味复核"],
    DIRECTION_WHOLE_MEDICINAL: ["整果/幼果验收", "清洗", "盐渍/蒸煮/干燥", "分级", "资质与法规复核", "包装建档"],
    DIRECTION_SEED: ["种子分离", "清洗干燥", "压榨或萃取", "精炼检测", "橘核药材分级", "合规用途确认"],
    DIRECTION_BYPRODUCT: ["皮渣/囊衣/果渣收集", "分选去杂", "干燥或发酵", "饲料/肥料小试", "安全指标检测", "去向建档"],
}


def check_compliance(text: str) -> list[str]:
    issues = []
    for word in FORBIDDEN_CLAIMS:
        if word in text:
            issues.append(f"发现高风险宣传词：{word}")
    return issues


def processing_flow(direction: str) -> list[str]:
    return FLOW_MAP.get(direction, ["原料验收", "分选", "小试", "检测复核", "人工确认"])


def customer_suggestion(customer_type: str, recommended_direction: str) -> str:
    if customer_type == "陈皮经销商":
        return "重点说明果皮来源、产地批次、开皮/干燥记录、仓储条件、检测资料和可追溯性；若转向精油、果胶或副产物利用，需另找匹配客户。"
    if customer_type == "茶饮品牌":
        return "重点说明陈皮丝/粉、果茶、干片、NFC 果汁或果粒原料的香气稳定、规格统一、出品方便、批量供货和复配测试建议。"
    if customer_type == "食品加工厂":
        return "重点说明果肉、整果、果皮精深加工及副产物利用的规格、检测、批次一致性、供应稳定和可定制加工能力。"
    return f"围绕 {recommended_direction} 的规格、证据、质控和风险边界生成销售草稿。"


def _risk_lines(quality_risks: list[QualityRisk]) -> list[str]:
    if not quality_risks:
        return ["- 暂未触发高风险项，但仍需人工复核。"]
    return [f"- [{risk.level}] {risk.item}：{risk.suggestion}" for risk in quality_risks]


def _value(value: Any) -> Any:
    return "未填写" if value in (None, "") else value


def _grouped_score_lines(scores: list[ScoreResult]) -> str:
    grouped: dict[str, list[str]] = {}
    for item in scores:
        part = DIRECTION_PARTS.get(item.direction, "其他")
        risk_text = f" 风险：{'；'.join(item.risk_notes)}" if item.risk_notes else ""
        line = f"- {item.direction}：{item.score} 分。原因：{'；'.join(item.reasons)}{risk_text}"
        grouped.setdefault(part, []).append(line)

    preferred_order = ["整果", "果肉", "果皮", "种子", "副产物", "其他"]
    sections = []
    for part in preferred_order:
        lines = grouped.get(part)
        if lines:
            sections.append(f"### {part}\n" + "\n".join(lines))
    return "\n\n".join(sections)


def generate_report(
    batch: dict[str, Any],
    image_observation: str,
    evidence: list[dict[str, Any]],
    scores: list[ScoreResult],
    quality_risks: list[QualityRisk],
) -> str:
    top = scores[0]
    second = scores[1] if len(scores) > 1 else None
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    evidence_lines = []
    for index, item in enumerate(evidence, 1):
        evidence_lines.append(
            f"{index}. {item.get('title')}（{item.get('year')}，{item.get('source')}）：{item.get('chunk_text')}"
        )
    if not evidence_lines:
        evidence_lines.append("未检索到足够相关的文献片段，需要补充真实文献、标准或企业 SOP。")

    score_text = _grouped_score_lines(scores)
    alternative = f"备选方向为：**{second.direction}**，适配评分 **{second.score} 分**。" if second else ""
    process_steps = " -> ".join(processing_flow(top.direction))
    risk_lines = _risk_lines(quality_risks)

    report = f"""# 柑橘批次智能决策报告

生成时间：{now}

## 1. 结论摘要

当前建议优先考虑：**{top.direction}**，适配评分 **{top.score} 分**。{alternative}

本报告是 Demo 辅助决策结果，不能替代实验室检测、食品安全放行、标签审核和人工审批。

## 2. 输入信息

- 批次号：{_value(batch.get("batch_id"))}
- 产地：{_value(batch.get("origin"))}
- 品种：{_value(batch.get("variety"))}
- 采收时间：{_value(batch.get("harvest_date"))}
- 重量：{_value(batch.get("weight_kg"))} kg
- 糖度：{_value(batch.get("brix"))}
- 酸度：{_value(batch.get("acidity"))}
- 水分：{_value(batch.get("moisture"))}
- 目标客户：{_value(batch.get("customer_type"))}
- 外观描述：{image_observation or "未填写"}

## 3. 原料初判

本轮按柑橘加工图鉴中的原料部位拆分为整果、果肉、果皮、种子和副产物方向。照片或人工描述只用于判断外观、成熟度、破损、腐烂和疑似霉变，不作为糖度、农残、重金属、微生物或黄曲霉毒素结论。若存在疑似霉变、腐烂、异味或大面积破损，应先分选剔除并由质控人员复核。

## 4. 加工路线评分

{score_text}

## 5. 推荐工艺流程

主推方向：**{top.direction}**

建议流程：{process_steps}

进入正式生产前，应补齐关键检测、批次记录、操作记录和留样记录；若用于对外销售，还需由质控、法规或业务负责人确认。涉及中药材、保健品、提取物、日化或饲料肥料用途时，需单独复核生产资质、标签和适用法规。

## 6. 质控风险与人工复核

{chr(10).join(risk_lines)}

## 7. 文献依据

{chr(10).join(evidence_lines)}

注意：文献依据来自本地文献库切片。用于正式决策前，应由人工复核原文、页码、实验条件和适用边界；企业 SOP、检测报告和法规标准仍需单独归档。

## 8. 客户匹配与销售建议

{customer_suggestion(str(batch.get("customer_type", "")), top.direction)}

销售话术只能作为内部草稿，不得加入疾病相关功效、功效夸大、虚假年份、虚假产地、无依据检测结论或绝对化承诺。

## 9. 需要补充的数据

- 农残、重金属、微生物、黄曲霉毒素等检测结果。
- 糖度、酸度、水分、出汁率、果皮占比、籽粒比例和缺陷比例。
- 真实文献、标准或 SOP 依据。
- 图片拍摄条件、人工复核结果和不合格原料处置记录。
- 客户规格、价格区间、交付周期、包装要求和法规适用场景。

## 10. 合规声明

本建议基于当前输入数据和 Demo 知识库，仅作为工艺与经营辅助决策参考。食品安全放行、标签标识、对外宣传和报价需经企业质控、法规、法务或业务负责人确认。
"""

    compliance_issues = check_compliance(report)
    if compliance_issues:
        report += "\n## 11. 合规检查提示\n\n" + "\n".join(f"- {issue}" for issue in compliance_issues)
    return report