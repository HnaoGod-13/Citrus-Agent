from __future__ import annotations

import re
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

PROCESSING_PROFILES = {
    DIRECTION_PEEL: {
        "product_form": "分级陈皮或陈皮茶原料",
        "core_operation": "按批次完成开皮、干燥、分级和隔离陈化，避免不同产地、品种和处理日期混批。",
        "pilot_parameters": ["开皮规格", "干燥方式及温度/时间", "干燥终点水分", "仓储温湿度与陈化周期"],
        "release_checks": ["外观、气味与霉变复核", "水分与微生物", "批次来源和仓储记录完整性"],
    },
    DIRECTION_SHRED: {
        "product_form": "陈皮丝或陈皮粉标准化原料",
        "core_operation": "将合格果皮干燥后切丝或粉碎，按目标规格筛分，并控制异物和交叉污染。",
        "pilot_parameters": ["干燥终点水分", "切丝宽度或粉体粒径", "筛网规格", "包装阻湿性能"],
        "release_checks": ["粒径/丝宽与均匀度", "异物与金属风险", "水分、微生物与风味"],
    },
    DIRECTION_PEEL_OIL: {
        "product_form": "柑橘果皮精油或香精原料",
        "core_operation": "在果皮清洗破碎后比较冷压与蒸馏路线，完成油水分离和必要的后处理。",
        "pilot_parameters": ["原料粒径", "冷压压力或蒸馏条件", "油水分离条件", "避光储存条件"],
        "release_checks": ["得油率与感官", "水分/杂质与稳定性", "目标用途对应的成分和合规要求"],
    },
    DIRECTION_PEEL_PECTIN: {
        "product_form": "果胶或膳食纤维原料",
        "core_operation": "对皮渣进行破碎和提取小试，比较酸提或酶提路径，再完成过滤、浓缩、分离和干燥。",
        "pilot_parameters": ["原料粒径", "提取方式、pH、料液比与时间", "浓缩终点", "干燥条件"],
        "release_checks": ["得率、纯度与凝胶性能", "残留物与微生物", "目标食品用途的规格符合性"],
    },
    DIRECTION_PEEL_FLAVONOID: {
        "product_form": "果皮黄酮/色素提取物",
        "core_operation": "完成果皮干燥粉碎、提取、纯化、浓缩和制粉小试，溶剂路线必须单独做残留与用途评审。",
        "pilot_parameters": ["粉体粒径", "提取介质、料液比与时间", "纯化浓缩条件", "干燥条件"],
        "release_checks": ["目标成分含量与批次一致性", "溶剂残留或相关安全指标", "产品用途与标签合规性"],
    },
    DIRECTION_JUICE: {
        "product_form": "NFC 柑橘汁或果汁基料",
        "core_operation": "经清洗分选后及时榨汁，完成过滤或均质、杀菌与灌装，并减少等待造成的风味和微生物风险。",
        "pilot_parameters": ["出汁率", "过滤精度或均质条件", "杀菌温度/时间组合", "灌装和冷却条件"],
        "release_checks": ["糖度、酸度与感官", "微生物", "包装密封性与货架期稳定性"],
    },
    DIRECTION_CONCENTRATE: {
        "product_form": "柑橘浓缩汁或调配基料",
        "core_operation": "先获得合格原汁，再比较低温真空、冷冻或膜浓缩路线，控制风味损失和浓缩终点。",
        "pilot_parameters": ["原汁澄清度", "浓缩方式、温度与真空度", "目标浓缩倍数/糖度", "复配与杀菌条件"],
        "release_checks": ["可溶性固形物、酸度与黏度", "色泽风味与复溶性", "微生物和储藏稳定性"],
    },
    DIRECTION_VINEGAR_WINE: {
        "product_form": "柑橘果醋或发酵果酒基料",
        "core_operation": "在原汁澄清和糖酸校正后进行受控接种发酵，记录全过程批次、温度、时间和异常状态。",
        "pilot_parameters": ["初始糖酸比", "菌种与接种量", "发酵温度/时间", "终点酸度或酒精度"],
        "release_checks": ["发酵终点与感官", "微生物和稳定性", "酒类/食醋产品资质与标签要求"],
    },
    DIRECTION_SEGMENT: {
        "product_form": "橘瓣罐头或糖水橘瓣",
        "core_operation": "完成去皮分瓣、去囊衣和分级装罐，控制橘瓣完整度，再经加液、密封和杀菌形成稳定产品。",
        "pilot_parameters": ["去囊衣方式", "橘瓣分级规格", "糖液浓度与装罐量", "杀菌温度/时间组合"],
        "release_checks": ["橘瓣完整度、净含量与感官", "密封性", "商业无菌与货架期观察"],
    },
    DIRECTION_PULP_DRINK: {
        "product_form": "砂囊、果粒或果肉饮料原料",
        "core_operation": "分离合格砂囊或果粒后进行配方小试、均质、杀菌和灌装，重点观察悬浮稳定与口感。",
        "pilot_parameters": ["果粒规格与添加量", "糖酸配比", "均质条件", "杀菌和灌装条件"],
        "release_checks": ["糖度、酸度、口感与沉淀", "微生物", "包装密封和货架期稳定性"],
    },
    DIRECTION_WHOLE_PRESERVE: {
        "product_form": "果脯或蜜饯",
        "core_operation": "整果清洗预处理后开展糖渍或蜂蜜腌制小试，再低温干燥并按成品规格分级。",
        "pilot_parameters": ["预处理方式", "糖渍液浓度与时间", "干燥温度/时间", "终点水分或水分活度"],
        "release_checks": ["水分/水分活度与感官", "微生物", "食品添加剂、标签和包装符合性"],
    },
    DIRECTION_WHOLE_DRY: {
        "product_form": "柑橘冻干片或烘干片",
        "core_operation": "整果清洗切片后比较冻干与烘干工艺，控制切片厚度、色泽风味和终点含水状态。",
        "pilot_parameters": ["切片厚度", "护色预处理", "冻干或烘干曲线", "终点水分与包装阻湿性"],
        "release_checks": ["片形、色泽、脆度与风味", "水分和微生物", "包装密封与吸潮稳定性"],
    },
    DIRECTION_WHOLE_POWDER_TEA: {
        "product_form": "柑橘果粉或果茶原料",
        "core_operation": "经切片干燥后粉碎筛分，并按目标饮用场景完成拼配或制茶小试。",
        "pilot_parameters": ["干燥终点", "粉体粒径", "拼配比例", "冲泡条件与包装阻湿性"],
        "release_checks": ["粒径、溶散/冲泡表现与风味", "水分、异物和微生物", "配料与标签合规性"],
    },
    DIRECTION_WHOLE_MEDICINAL: {
        "product_form": "药橘、咸柑橘或枳实类候选原料",
        "core_operation": "按拟定用途完成盐渍、蒸煮或干燥小试；在确认药材或食品属性前只作为候选路线管理。",
        "pilot_parameters": ["原料成熟度和规格", "盐渍/蒸煮/干燥条件", "分级标准", "储藏条件"],
        "release_checks": ["性状、水分与相关成分", "污染物和微生物", "产品属性、生产资质与适用法规"],
    },
    DIRECTION_SEED: {
        "product_form": "籽油或橘核候选原料",
        "core_operation": "从合格批次分离种子并清洗干燥，再比较压榨或萃取路线；药材分级与油脂路线分开管理。",
        "pilot_parameters": ["种子含水率", "压榨或萃取条件", "精炼条件", "储藏避光与充氮条件"],
        "release_checks": ["得油率、酸价/过氧化值或药材性状", "污染物与溶剂残留", "用途和资质合规性"],
    },
    DIRECTION_BYPRODUCT: {
        "product_form": "饲料、有机肥或综合利用中间料",
        "core_operation": "将皮渣、囊衣和果渣分类收集，完成去杂和干燥/发酵小试，禁止与不合格霉变原料混用。",
        "pilot_parameters": ["原料分类与含水率", "干燥或发酵条件", "配方比例", "储运条件"],
        "release_checks": ["安全指标和腐败风险", "营养/肥效小试结果", "目标去向对应的法规与接收标准"],
    },
}

DEFAULT_PROCESSING_PROFILE = {
    "product_form": "待确认加工产品",
    "core_operation": "按推荐流程开展小试，所有关键参数由文献、企业 SOP 和小试结果共同确认。",
    "pilot_parameters": ["原料规格", "设备能力", "时间/温度等关键工艺参数", "包装与储藏条件"],
    "release_checks": ["感官与理化指标", "食品安全项目", "包装、标签与追溯记录"],
}


def check_compliance(text: str) -> list[str]:
    issues = []
    for word in FORBIDDEN_CLAIMS:
        if word in text:
            issues.append(f"发现高风险宣传词：{word}")
    return issues


def processing_flow(direction: str) -> list[str]:
    return FLOW_MAP.get(direction, ["原料验收", "分选", "小试", "检测复核", "人工确认"])


def _item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def build_processing_plan(
    batch: dict[str, Any],
    direction: str,
    quality_risks: list[QualityRisk],
    image_observation: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a batch-aware pilot plan without inventing unsupported production parameters."""
    profile = PROCESSING_PROFILES.get(direction, DEFAULT_PROCESSING_PROFILE)
    evidence = evidence or []
    flow = processing_flow(direction)
    batch_labels = {
        "batch_id": "批次号",
        "origin": "产地",
        "variety": "品种",
        "harvest_date": "采收时间",
        "weight_kg": "重量（kg）",
        "brix": "糖度",
        "acidity": "酸度",
        "moisture": "水分",
        "customer_type": "目标客户",
    }
    basis = [
        f"{label}：{batch.get(key)}"
        for key, label in batch_labels.items()
        if batch.get(key) not in (None, "")
    ]
    if image_observation:
        basis.append(f"外观初筛：{image_observation}")
    if not basis:
        basis.append("当前未录入可用于细化方案的批次字段")

    missing_tests = [
        label
        for key, label in {
            "pesticide": "农残检测",
            "heavy_metal": "重金属检测",
            "microbe": "微生物检测",
            "aflatoxin": "黄曲霉毒素检测",
        }.items()
        if not batch.get(key)
    ]
    risk_controls = [
        f"[{_item_value(risk, 'level', '提示')}] {_item_value(risk, 'item', '风险项')}："
        f"{_item_value(risk, 'suggestion', '需人工复核')}"
        for risk in quality_risks
    ]

    core_steps = flow[2:-2] or flow[1:-1] or flow
    stages = [
        {
            "name": "01 原料准入与隔离",
            "steps": flow[:1],
            "operation": "核对批次、产地、品种、采收/到货信息和供应商资料；未完成关键检测的原料先隔离标识，不进入正式生产放行。",
            "control": "照片和人工描述只用于外观初筛；疑似霉变、腐烂、异味或严重破损原料应剔除并交由质控复核。",
            "record": "原料验收单、不合格处置单、批次标识与取样记录。",
        },
        {
            "name": "02 分选与前处理",
            "steps": flow[1:2] or flow[:1],
            "operation": "按产品目标完成分选、去杂、清洗或基础预处理；合格料、不合格料及不同批次使用独立容器和状态标识。",
            "control": "确认用水、接触面、人员卫生和异物控制满足企业要求，并记录原料投入量、剔除量与损耗。",
            "record": "分选/清洗记录、投入产出记录、设备清洁记录。",
        },
        {
            "name": "03 核心加工与小试定参",
            "steps": core_steps,
            "operation": str(profile["core_operation"]),
            "control": (
                "优先回查本报告检索到的原文实验对象、方法和结果，再结合设备能力设计小试；"
                "温度、时间、浓度、料液比等数值只有在适用条件一致并经企业 SOP 复核后才能转为生产参数。"
            ),
            "record": "小试配方、关键参数、设备状态、过程取样和偏差记录。",
        },
        {
            "name": "04 稳定化、包装与留样",
            "steps": flow[-2:] if len(flow) > 1 else flow,
            "operation": "完成路线规定的稳定化、分级或包装操作，建立成品批号；按储藏要求避光、防潮、冷藏或常温隔离存放。",
            "control": "包装材料、密封性、净含量和储藏条件须与产品属性匹配，未经验证不得直接承诺货架期。",
            "record": "包装记录、成品批记录、留样记录和仓储条件记录。",
        },
        {
            "name": "05 成品检测与人工放行",
            "steps": ["检测汇总", "人工放行", "归档追溯"],
            "operation": "汇总过程记录、成品指标、食品安全检测和客户规格，完成偏差评估后由授权人员决定放行、返工或报废。",
            "control": "检测缺失时只能保留为候选小试方案，不能输出可销售、可出厂或符合标准的结论。",
            "record": "检测报告、放行/返工/报废审批、客户规格确认和全链路追溯档案。",
        },
    ]

    return {
        "direction": direction,
        "product_form": profile["product_form"],
        "status": "演示加工方案｜待小试、文献与企业 SOP 复核",
        "basis": basis,
        "flow": flow,
        "stages": stages,
        "pilot_parameters": list(profile["pilot_parameters"]),
        "release_checks": list(profile["release_checks"]),
        "missing_data": [
            *missing_tests,
            (
                "对已检索文献的原文、页码、实验条件和适用边界完成人工复核"
                if evidence
                else "真实文献、适用标准或企业 SOP"
            ),
            "客户成品规格、包装和交付要求",
        ],
        "evidence_basis": [
            {
                "citation": f"文献{index}",
                "title": item.get("title"),
                "year": item.get("year"),
                "category": item.get("category") or item.get("product"),
                "page": item.get("page") or item.get("page_start"),
            }
            for index, item in enumerate(evidence[:12], 1)
        ],
        "risk_controls": risk_controls or ["暂未触发额外高风险项，仍需质控人员按批次复核。"],
    }


def processing_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        f"主推方向：**{plan['direction']}**",
        f"目标产品：**{plan['product_form']}**",
        f"方案状态：{plan['status']}",
        "",
        "### 5.1 全流程",
        "",
        " → ".join(plan["flow"]),
        "",
        "### 5.2 分阶段执行方案",
        "",
    ]
    for stage in plan["stages"]:
        lines.extend(
            [
                f"#### {stage['name']}",
                f"- 对应工序：{' → '.join(stage['steps'])}",
                f"- 操作要点：{stage['operation']}",
                f"- 质控要求：{stage['control']}",
                f"- 必留记录：{stage['record']}",
                "",
            ]
        )
    lines.extend(
        [
            "### 5.3 小试与放行清单",
            "",
            f"- 待小试确定：{'；'.join(plan['pilot_parameters'])}。",
            f"- 成品复核：{'；'.join(plan['release_checks'])}。",
            f"- 当前待补：{'；'.join(plan['missing_data'])}。",
            f"- 风险边界：{'；'.join(plan['risk_controls'])}",
        ]
    )
    return "\n".join(lines)


def _md_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "\\|").strip()


def parameterized_plan_markdown(
    parameterized_plan: dict[str, Any] | None,
    parameter_groups: list[dict[str, Any]] | None,
    processing_intent: dict[str, Any] | None,
) -> str:
    if not parameterized_plan:
        return (
            "### 5.4 文献参数化执行表\n\n"
            "现有知识库证据不足，或本轮未识别到明确目标产品；不填入无依据数值。"
        )
    intent = processing_intent or {}
    groups = parameter_groups or []
    lines = [
        "### 5.4 加工目标与适用性判断",
        "",
        f"- 目标产品：{parameterized_plan.get('product') or '待确认'}。",
        f"- 原料：{parameterized_plan.get('raw_material') or '待确认'}。",
        f"- 目标规模：{parameterized_plan.get('scale') or 'unknown'}；unknown 表示文献或用户输入未明确规模，不能直接按工业参数使用。",
        f"- 用户已说明设备：{'、'.join(intent.get('equipment') or []) or '未提供'}。",
        "- 参数证据分为文献直接报告、多文献归纳和工程配置提示；工程配置提示不作为文献参数。",
        "",
        "### 5.5 推荐工艺流程",
        "",
        " → ".join(str(step) for step in parameterized_plan.get("flow", [])),
        "",
        "### 5.6 详细操作参数",
        "",
        "| 步骤 | 操作说明 | 推荐参数/证据状态 | 适用条件 | 关键控制点 | 证据来源 |",
        "|---|---|---|---|---|---|",
    ]
    for row in parameterized_plan.get("rows", []):
        params = row.get("parameters") or []
        if params:
            parameter_text = "；".join(
                f"{item.get('name')}={item.get('recommendation')}（{item.get('confidence')}）"
                for item in params
            )
            applicability = "；".join(
                f"原料={item.get('raw_material') or '未明确'}，规模={item.get('scale')}，方法={item.get('method')}"
                for item in params
            )
        else:
            parameter_text = str(row.get("parameter_status") or "现有知识库证据不足")
            applicability = "需结合原料、设备和规模补充证据"
        lines.append(
            "| " + " | ".join(
                _md_cell(value)
                for value in (
                    row.get("step"),
                    row.get("operation"),
                    parameter_text,
                    applicability,
                    row.get("key_control"),
                    "、".join(row.get("source_ids") or []) or "无直接参数证据",
                )
            ) + " |"
        )
    lines.extend(["", "参数设置理由与变化影响：", ""])
    if groups:
        for group in groups[:30]:
            conflict_note = "；存在冲突，禁止合并成单一范围" if group.get("conflict") else ""
            lines.append(
                f"- **{group.get('process_step')}—{group.get('parameter_name')}**："
                f"{group.get('recommended_range')}，{group.get('confidence_level')}；"
                f"适用条件为 {group.get('applicability')}；{group.get('effect_summary')}"
                f"；来源 {('、'.join(group.get('source_ids') or [])) or '无'}{conflict_note}。"
            )
    else:
        lines.append("- 未提取到单位、适用条件和来源均完整的参数，所有数值保持空缺，需补充文献或开展小试。")
    lines.extend(["", "### 5.7 设备需求及替代设备", ""])
    for item in parameterized_plan.get("equipment", []):
        lines.append(f"- {item.get('stage')}：{item.get('primary')}；替代方案：{item.get('alternative')}。")
    if not parameterized_plan.get("equipment"):
        lines.append("- 设备配置待目标产品和规模确认后确定。")
    lines.extend(["", "### 5.8 质量控制、包装储藏与副产物", ""])
    lines.append("- 建议监测指标：" + "、".join(parameterized_plan.get("quality_checks") or []) + "。")
    lines.append(
        "- 包装、储藏和保质期：仅采用参数表中有直接来源且条件匹配的数值；没有稳定性或法规依据时不得承诺保质期。"
    )
    lines.append("- 副产物与废弃物：" + str(parameterized_plan.get("byproduct_guidance") or "分流、称量并依法合规处置。"))
    unresolved = parameterized_plan.get("unresolved_steps") or []
    lines.append("- 仍缺可靠参数的步骤：" + ("、".join(unresolved) if unresolved else "无；但仍需完成企业小试和放大验证") + "。")
    return "\n".join(lines)


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
        line = (
            f"- {item.direction}：{item.match_level}；文献支持：{item.evidence_support}；"
            f"数据置信度：{item.data_confidence}。原因：{'；'.join(item.reasons)}{risk_text}"
        )
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
    processing_plan: dict[str, Any] | None = None,
    processing_intent: dict[str, Any] | None = None,
    process_parameters: list[dict[str, Any]] | None = None,
    parameter_groups: list[dict[str, Any]] | None = None,
    parameterized_plan: dict[str, Any] | None = None,
) -> str:
    top = scores[0]
    second = scores[1] if len(scores) > 1 else None
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    evidence_lines = []
    for index, item in enumerate(evidence, 1):
        page = item.get("page") or item.get("page_start")
        locator = f"第 {page} 页" if page else "页码未标注"
        category = item.get("category") or item.get("product") or "未分类"
        section = item.get("section") or "正文"
        source = item.get("publication") or item.get("doi") or item.get("source_file") or "本地文献"
        excerpt = re.sub(r"\s+", " ", str(item.get("chunk_text") or "")).strip()
        if len(excerpt) > 760:
            excerpt = excerpt[:760].rstrip() + "…"
        evidence_lines.append(
            f"{index}. **[文献{index}] {item.get('title') or '未命名文献'}**"
            f"（{item.get('year') or '年份未知'}；{category}；{section}；{locator}；{source}）\n"
            f"   - 可用于本轮复核的证据片段：{excerpt}"
        )
    if not evidence_lines:
        evidence_lines.append("未检索到足够相关的文献片段，需要补充真实文献、标准或企业 SOP。")

    score_text = _grouped_score_lines(scores)
    alternative = f"备选方向为：**{second.direction}**，适配等级 **{second.match_level}**。" if second else ""
    processing_plan = processing_plan or build_processing_plan(
        batch,
        top.direction,
        quality_risks,
        image_observation,
        evidence,
    )
    process_plan_text = processing_plan_markdown(processing_plan)
    parameterized_text = parameterized_plan_markdown(
        parameterized_plan,
        parameter_groups,
        processing_intent,
    )
    risk_lines = _risk_lines(quality_risks)

    report = f"""# 柑橘批次智能决策报告

生成时间：{now}

## 1. 结论摘要

当前建议优先考虑：**{top.direction}**，适配等级 **{top.match_level}**；文献支持为 **{top.evidence_support}**；数据置信度为 **{top.data_confidence}**。{alternative}

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

## 4. 加工路线分级排序

以下等级用于比较路线优先级，不是生产成功率或合格概率；内部排序值不对外展示。

{score_text}

## 5. 完整加工流程（方案）

{process_plan_text}

{parameterized_text}

进入正式生产前，应补齐关键检测、批次记录、操作记录和留样记录；若用于对外销售，还需由质控、法规或业务负责人确认。涉及中药材、保健品、提取物、日化或饲料肥料用途时，需单独复核生产资质、标签和适用法规。

## 6. 质控风险与人工复核

{chr(10).join(risk_lines)}

## 7. 文献依据与应用边界

{chr(10).join(evidence_lines)}

应用原则：优先使用与本批次原料部位、目标产品和工艺问题直接对应的结果或结论；涉及具体参数时还要核对研究对象、设备、料液比和评价指标。体外、动物、网络药理及相关性研究仅能作为研究线索，不得直接外推为人体功效或生产放行依据。企业 SOP、检测报告和法规标准仍需单独归档。

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
