from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence import DIRECT_EVIDENCE, effective_evidence_level


DIRECTION_PEEL = "果皮-陈皮/陈皮茶"
DIRECTION_SHRED = "果皮-陈皮丝/陈皮粉"
DIRECTION_PEEL_OIL = "果皮-精油/香精"
DIRECTION_PEEL_PECTIN = "果皮-果胶/膳食纤维"
DIRECTION_PEEL_FLAVONOID = "果皮-黄酮/色素"
DIRECTION_JUICE = "果肉-柑橘汁/NFC"
DIRECTION_CONCENTRATE = "果肉-浓缩汁"
DIRECTION_VINEGAR_WINE = "果肉-果醋/果酒"
DIRECTION_SEGMENT = "果肉-橘瓣罐头"
DIRECTION_PULP_DRINK = "果肉-砂囊/果粒饮料"
DIRECTION_WHOLE_PRESERVE = "整果-果脯/蜜饯"
DIRECTION_WHOLE_DRY = "整果-冻干/烘干片"
DIRECTION_WHOLE_POWDER_TEA = "整果-果粉/果茶"
DIRECTION_WHOLE_MEDICINAL = "整果-药橘/咸柑橘/枳实"
DIRECTION_SEED = "种子-籽油/橘核"
DIRECTION_BYPRODUCT = "副产物-饲料/有机肥"


ALL_DIRECTIONS = [
    DIRECTION_PEEL,
    DIRECTION_SHRED,
    DIRECTION_PEEL_OIL,
    DIRECTION_PEEL_PECTIN,
    DIRECTION_PEEL_FLAVONOID,
    DIRECTION_JUICE,
    DIRECTION_CONCENTRATE,
    DIRECTION_VINEGAR_WINE,
    DIRECTION_SEGMENT,
    DIRECTION_PULP_DRINK,
    DIRECTION_WHOLE_PRESERVE,
    DIRECTION_WHOLE_DRY,
    DIRECTION_WHOLE_POWDER_TEA,
    DIRECTION_WHOLE_MEDICINAL,
    DIRECTION_SEED,
    DIRECTION_BYPRODUCT,
]

DIRECTION_PARTS = {
    DIRECTION_PEEL: "果皮",
    DIRECTION_SHRED: "果皮",
    DIRECTION_PEEL_OIL: "果皮",
    DIRECTION_PEEL_PECTIN: "果皮",
    DIRECTION_PEEL_FLAVONOID: "果皮",
    DIRECTION_JUICE: "果肉",
    DIRECTION_CONCENTRATE: "果肉",
    DIRECTION_VINEGAR_WINE: "果肉",
    DIRECTION_SEGMENT: "果肉",
    DIRECTION_PULP_DRINK: "果肉",
    DIRECTION_WHOLE_PRESERVE: "整果",
    DIRECTION_WHOLE_DRY: "整果",
    DIRECTION_WHOLE_POWDER_TEA: "整果",
    DIRECTION_WHOLE_MEDICINAL: "整果",
    DIRECTION_SEED: "种子",
    DIRECTION_BYPRODUCT: "副产物",
}

DIRECTION_EVIDENCE_TERMS = {
    DIRECTION_PEEL: ["陈皮", "广陈皮", "chenpi", "citri reticulatae", "陈化", "dried tangerine peel"],
    DIRECTION_SHRED: ["陈皮丝", "陈皮粉", "果皮粉", "peel powder", "particle size"],
    DIRECTION_PEEL_OIL: ["精油", "挥发油", "essential oil", "volatile oil", "柠檬烯", "limonene", "冷压", "蒸馏"],
    DIRECTION_PEEL_PECTIN: ["果胶", "pectin", "酯化度", "凝胶", "galacturonic"],
    DIRECTION_PEEL_FLAVONOID: ["黄酮", "flavonoid", "橙皮苷", "hesperidin", "柚皮苷", "naringin", "色素"],
    DIRECTION_JUICE: ["橙汁", "柑橘汁", "果汁", "nfc", "citrus juice", "orange juice", "榨汁"],
    DIRECTION_CONCENTRATE: ["浓缩汁", "浓缩果汁", "concentrated juice", "膜浓缩", "真空浓缩"],
    DIRECTION_VINEGAR_WINE: ["果醋", "果酒", "vinegar", "wine fermentation", "酒精发酵", "醋酸发酵"],
    DIRECTION_SEGMENT: ["橘瓣", "糖水橘瓣", "罐头", "canned citrus", "citrus segment"],
    DIRECTION_PULP_DRINK: ["砂囊", "果粒", "果肉饮料", "juice sac", "pulp beverage"],
    DIRECTION_WHOLE_PRESERVE: ["果脯", "蜜饯", "candied citrus", "preserved citrus"],
    DIRECTION_WHOLE_DRY: ["冻干", "烘干片", "干燥片", "freeze drying", "dried slice"],
    DIRECTION_WHOLE_POWDER_TEA: ["果粉", "果茶", "whole fruit powder", "citrus tea"],
    DIRECTION_WHOLE_MEDICINAL: ["枳实", "药橘", "咸柑橘", "medicinal citrus"],
    DIRECTION_SEED: ["种子", "籽油", "橘核", "seed oil", "citrus seed"],
    DIRECTION_BYPRODUCT: ["副产物", "果渣", "饲料", "有机肥", "by-product", "byproduct", "pomace", "citrus waste"],
}


@dataclass
class ScoreResult:
    direction: str
    # score is retained as an internal ordering value. User-facing output uses match_level.
    score: int
    reasons: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    match_level: str = "待评估"
    evidence_support: str = "未检索到直接支持"
    evidence_count: int = 0
    data_confidence: str = "低"


@dataclass
class QualityRisk:
    level: str
    item: str
    suggestion: str


def _contains(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_serious_decay(text: str) -> bool:
    text = text or ""
    negative_phrases = [
        "无明显霉",
        "未见霉",
        "没有霉",
        "无霉",
        "无明显腐烂",
        "未见腐烂",
        "没有腐烂",
    ]
    cleaned = text
    for phrase in negative_phrases:
        cleaned = cleaned.replace(phrase, "")
    return _contains(cleaned, ["霉", "腐烂", "霉斑", "发黑", "异味", "软烂"])


def _new_result(direction: str) -> ScoreResult:
    part = DIRECTION_PARTS.get(direction, "柑橘")
    return ScoreResult(
        direction=direction,
        score=40,
        reasons=[f"{part}候选方向，需结合产地、品种、检测结果、客户规格和小试数据复核。"],
    )


def _bump(results: dict[str, ScoreResult], directions: list[str], score: int, reason: str) -> None:
    for direction in directions:
        results[direction].score += score
        results[direction].reasons.append(reason)


def _risk(results: dict[str, ScoreResult], directions: list[str], note: str, score_delta: int = 0) -> None:
    for direction in directions:
        results[direction].score += score_delta
        results[direction].risk_notes.append(note)


def _evidence_documents(evidence: list[dict[str, Any]], terms: list[str]) -> int:
    documents: set[str] = set()
    lowered_terms = [term.lower() for term in terms]
    for index, item in enumerate(evidence):
        # Retrieval relevance is not evidence strength. Only fragments that pass
        # the deterministic direct-evidence policy may increase route scores.
        if effective_evidence_level(item) != DIRECT_EVIDENCE:
            continue
        text = " ".join(
            str(item.get(field) or "")
            for field in ["title", "category", "product", "topic", "keywords", "section", "chunk_text"]
        ).lower()
        if any(term in text for term in lowered_terms):
            documents.add(
                str(item.get("document_id") or item.get("source_file") or item.get("title") or index)
            )
    return len(documents)


def _data_confidence(batch: dict[str, Any], image_observation: str) -> str:
    fields = ["origin", "variety", "weight_kg", "brix", "acidity", "moisture", "customer_type"]
    available = sum(batch.get(field) not in ("", None) for field in fields)
    available += sum(batch.get(field) is True for field in ["pesticide", "heavy_metal", "microbe", "aflatoxin"])
    available += bool((image_observation or "").strip())
    if available >= 9:
        return "高"
    if available >= 5:
        return "中"
    return "低"


def _match_level(score: int) -> str:
    if score >= 75:
        return "优先评估"
    if score >= 60:
        return "重点小试"
    if score >= 48:
        return "条件性备选"
    return "暂不优先"


def score_processing_options(
    batch: dict[str, Any],
    image_observation: str,
    evidence: list[dict[str, Any]] | None = None,
) -> list[ScoreResult]:
    """Rank routes with auditable batch rules plus direct literature applicability."""
    origin = str(batch.get("origin", ""))
    variety = str(batch.get("variety", ""))
    customer_type = str(batch.get("customer_type", ""))
    text = origin + variety
    image_text = image_observation or ""
    brix = _to_float(batch.get("brix"))
    acidity = _to_float(batch.get("acidity"))
    moisture = _to_float(batch.get("moisture"))

    results = {direction: _new_result(direction) for direction in ALL_DIRECTIONS}

    if _contains(text, ["新会", "茶枝柑", "广陈皮", "陈皮"]):
        _bump(results, [DIRECTION_PEEL], 24, "产地或品种贴近陈皮、陈皮茶等果皮陈化加工场景。")
        _bump(results, [DIRECTION_SHRED], 18, "茶枝柑果皮可作为陈皮丝/粉等标准化原料候选。")
        _bump(
            results,
            [DIRECTION_PEEL_OIL, DIRECTION_PEEL_PECTIN, DIRECTION_PEEL_FLAVONOID],
            8,
            "柑橘果皮可进一步提取精油、果胶、黄酮或色素等功能性成分。",
        )

    if _contains(text, ["脐橙", "甜橙", "赣南", "橙"]):
        _bump(results, [DIRECTION_JUICE], 24, "品种或产地更贴近柑橘汁、NFC 饮料加工场景。")
        _bump(results, [DIRECTION_CONCENTRATE], 18, "橙类原料适合评估浓缩汁和后续调配用途。")
        _bump(results, [DIRECTION_SEGMENT, DIRECTION_PULP_DRINK], 12, "橙类果肉可评估橘瓣、砂囊或果粒饮料利用。")
        _bump(results, [DIRECTION_VINEGAR_WINE], 8, "果汁可进一步通过发酵转为果醋或低酒精果酒。")

    if _contains(text, ["金桔", "金橘", "四季桔", "小青橘", "柠檬", "枳实"]):
        _bump(results, [DIRECTION_WHOLE_MEDICINAL], 16, "小型柑橘或幼果更贴近药橘、咸柑橘或枳实等整果加工。")
        _bump(results, [DIRECTION_WHOLE_PRESERVE, DIRECTION_WHOLE_DRY], 10, "小型整果适合评估果脯、蜜饯、冻干或烘干片。")

    if _contains(text, ["柑", "橘", "橙", "柚", "柠檬"]):
        _bump(results, [DIRECTION_BYPRODUCT], 6, "柑橘皮渣、囊衣和果渣可作为饲料、有机肥或综合利用原料。")
        _bump(results, [DIRECTION_SEED], 4, "有籽批次可评估籽油、橘核等种子利用。")

    if customer_type == "陈皮经销商":
        _bump(results, [DIRECTION_PEEL], 20, "目标客户关注产地、批次、开皮、干燥、仓储和溯源。")
        _bump(results, [DIRECTION_SHRED], 10, "陈皮客户也可能接受陈皮丝/粉等标准化规格。")
        _risk(
            results,
            [DIRECTION_PEEL_OIL, DIRECTION_PEEL_PECTIN, DIRECTION_PEEL_FLAVONOID, DIRECTION_BYPRODUCT],
            "该客户类型通常不是精深提取或副产物利用的优先销售对象。",
            -4,
        )
    elif customer_type == "茶饮品牌":
        _bump(results, [DIRECTION_SHRED], 18, "茶饮品牌通常关注香气稳定、规格统一和使用便利。")
        _bump(results, [DIRECTION_WHOLE_DRY, DIRECTION_WHOLE_POWDER_TEA, DIRECTION_PEEL], 12, "茶饮客户可评估果茶、干片、陈皮茶等出品形态。")
        _bump(results, [DIRECTION_JUICE, DIRECTION_PULP_DRINK], 8, "茶饮客户也可能需要果汁基底或果粒口感原料。")
    elif customer_type == "食品加工厂":
        _bump(
            results,
            [DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_SEGMENT, DIRECTION_PULP_DRINK, DIRECTION_WHOLE_PRESERVE],
            14,
            "食品加工客户关注稳定供应、规格一致和可定制加工能力。",
        )
        _bump(
            results,
            [DIRECTION_PEEL_OIL, DIRECTION_PEEL_PECTIN, DIRECTION_PEEL_FLAVONOID, DIRECTION_BYPRODUCT],
            12,
            "食品加工厂可承接果皮提取、副产物综合利用或配料型产品开发。",
        )

    if brix is not None:
        if brix >= 11.5:
            _bump(
                results,
                [DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_VINEGAR_WINE, DIRECTION_WHOLE_PRESERVE],
                16,
                "糖度较高，适合作为果肉饮料、浓缩汁、发酵或蜜饯方向候选。",
            )
            _bump(results, [DIRECTION_SEGMENT, DIRECTION_PULP_DRINK, DIRECTION_WHOLE_DRY, DIRECTION_WHOLE_POWDER_TEA], 8, "糖度较高，有利于果肉和整果休闲食品风味。")
        elif brix < 9:
            _risk(
                results,
                [DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_VINEGAR_WINE, DIRECTION_SEGMENT, DIRECTION_PULP_DRINK, DIRECTION_WHOLE_PRESERVE],
                "糖度偏低，果肉饮料、浓缩汁、发酵和蜜饯方向需复核风味与配方。",
                -10,
            )
            _bump(results, [DIRECTION_PEEL_PECTIN, DIRECTION_BYPRODUCT], 4, "糖度偏低时可同步评估果皮果胶或副产物利用。")
    else:
        _risk(
            results,
            [DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_VINEGAR_WINE, DIRECTION_SEGMENT, DIRECTION_PULP_DRINK, DIRECTION_WHOLE_PRESERVE],
            "缺少糖度数据，果肉和整果甜味加工方向只能初步判断。",
            -4,
        )

    if acidity is not None:
        if acidity > 1.2:
            _risk(
                results,
                [DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_SEGMENT, DIRECTION_PULP_DRINK],
                "酸度偏高，需评估口感、糖酸比和配方平衡。",
                -8,
            )
            _bump(results, [DIRECTION_VINEGAR_WINE], 4, "酸度偏高时可评估发酵醋或配制型果酒适配性。")
        elif acidity < 0.4:
            _risk(results, [DIRECTION_VINEGAR_WINE], "酸度偏低，果醋/果酒发酵稳定性和风味需复核。", -4)
    else:
        _risk(
            results,
            [DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_VINEGAR_WINE],
            "缺少酸度数据，果汁、浓缩汁和发酵方向需补测糖酸比。",
            -3,
        )

    dry_directions = [DIRECTION_PEEL, DIRECTION_SHRED, DIRECTION_WHOLE_DRY, DIRECTION_WHOLE_POWDER_TEA]
    if moisture is not None and moisture > 20:
        _risk(results, dry_directions, "水分偏高，干燥、陈化、粉碎和仓储霉变风险需重点控制。", -10)
    elif moisture is None:
        _risk(results, dry_directions, "缺少水分数据，干燥和仓储型产品需补测水分。", -3)

    if _contains(image_text, ["机械伤", "破损", "裂果", "压伤"]):
        _risk(
            results,
            [DIRECTION_PEEL, DIRECTION_WHOLE_DRY, DIRECTION_SEGMENT],
            "外观破损会降低高等级陈皮原皮、整果干片或橘瓣罐头适配度。",
            -14,
        )
        _bump(
            results,
            [DIRECTION_SHRED, DIRECTION_JUICE, DIRECTION_CONCENTRATE, DIRECTION_PEEL_PECTIN, DIRECTION_BYPRODUCT],
            8,
            "轻微外观缺陷可考虑转向切丝粉碎、榨汁浓缩、果胶提取或副产物利用。",
        )

    if _has_serious_decay(image_text):
        for result in results.values():
            result.score -= 35
            result.risk_notes.append("存在疑似霉变或腐烂描述，必须人工复核、分选或剔除。")

    for direction in [DIRECTION_WHOLE_MEDICINAL, DIRECTION_SEED, DIRECTION_PEEL_FLAVONOID]:
        results[direction].risk_notes.append("涉及药食、提取物或功能性成分时，需单独复核资质、标签、法规和宣称边界。")

    evidence = evidence or []
    confidence = _data_confidence(batch, image_observation)
    for result in results.values():
        document_count = _evidence_documents(evidence, DIRECTION_EVIDENCE_TERMS[result.direction])
        result.evidence_count = document_count
        result.data_confidence = confidence
        if document_count >= 3:
            result.score += 9
            result.evidence_support = "较强（至少3篇直接相关文献）"
        elif document_count == 2:
            result.score += 6
            result.evidence_support = "中等（2篇直接相关文献）"
        elif document_count == 1:
            result.score += 3
            result.evidence_support = "有限（1篇直接相关文献）"
        else:
            result.evidence_support = "未检索到直接支持"
            result.risk_notes.append("本轮未检索到该路线的直接相关文献，不能仅凭规则排序进入生产。")
        if document_count:
            result.reasons.append(
                f"本轮检索到 {document_count} 篇与该路线直接相关的文献，已纳入路线排序；实验条件仍需原文复核和小试。"
            )
        result.score = max(0, min(100, result.score))
        result.match_level = _match_level(result.score)

    return sorted(results.values(), key=lambda item: item.score, reverse=True)


def check_quality_risks(batch: dict[str, Any], image_observation: str) -> list[QualityRisk]:
    risks: list[QualityRisk] = []
    image_text = image_observation or ""

    required_tests = {
        "pesticide": "农残检测",
        "heavy_metal": "重金属检测",
        "microbe": "微生物检测",
        "aflatoxin": "黄曲霉毒素检测",
    }
    for key, label in required_tests.items():
        status = batch.get(f"{key}_status")
        if status == "failed":
            risks.append(
                QualityRisk(
                    level="高",
                    item=f"{label}结果异常或不合格",
                    suggestion="该结果不能用于放行；应隔离批次、回查原始报告并由质控人员决定复检或处置。",
                )
            )
        elif status == "result_missing":
            risks.append(
                QualityRisk(
                    level="高",
                    item=f"{label}结果未明确",
                    suggestion="仅说明已检测或已有报告不足以放行，必须补充具体结果、限量依据和报告原件。",
                )
            )
        elif batch.get(key) is not True:
            risks.append(
                QualityRisk(
                    level="高",
                    item=f"缺少{label}",
                    suggestion="不能输出最终放行、可销售或可出厂结论，只能作为初步加工建议。",
                )
            )

    if _has_serious_decay(image_text):
        risks.append(
            QualityRisk(
                level="高",
                item="疑似霉变或腐烂",
                suggestion="需分选剔除、复检并由质控人员确认，Demo 不应给出合格结论。",
            )
        )

    brix = _to_float(batch.get("brix"))
    if brix is None:
        risks.append(
            QualityRisk(
                level="中",
                item="缺少糖度数据",
                suggestion="果汁、浓缩汁、果酒/果醋、蜜饯和果粉方向需补测糖度及糖酸比。",
            )
        )

    acidity = _to_float(batch.get("acidity"))
    if acidity is None:
        risks.append(
            QualityRisk(
                level="中",
                item="缺少酸度数据",
                suggestion="果肉饮料、浓缩汁和发酵方向需补测酸度，评估口感和稳定性。",
            )
        )

    moisture = _to_float(batch.get("moisture"))
    if moisture is None:
        risks.append(QualityRisk(level="中", item="缺少水分数据", suggestion="陈皮、干片、果粉和仓储风险只能初步判断。"))
    elif moisture > 20:
        risks.append(
            QualityRisk(
                level="中",
                item="水分偏高",
                suggestion="建议先补充干燥记录、复测水分并评估仓储霉变风险。",
            )
        )

    return risks
