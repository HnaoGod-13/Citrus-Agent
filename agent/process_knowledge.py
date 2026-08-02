from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any, Callable

from .processing_config import (
    PROCESS_CONTEXT_EVIDENCE_LIMIT,
    PROCESS_CONTEXT_PARAMETER_LIMIT,
    PROCESS_CONTEXT_TOKEN_LIMIT,
    PROCESS_EVIDENCE_TOP_K,
    PROCESS_PARAMETER_LIMIT,
    PROCESS_SUBQUERY_TOP_K,
)
from .rag import comprehensive_search_knowledge


SearchFunction = Callable[..., list[dict[str, Any]]]

PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "陈皮": ("陈皮", "广陈皮", "橘皮", "柑橘果皮", "chenpi", "dried tangerine peel"),
    "柑橘汁": ("柑橘汁", "橙汁", "果汁", "NFC", "榨汁", "orange juice", "citrus juice"),
    "浓缩汁": ("浓缩汁", "浓缩果汁", "concentrated juice"),
    "精油": ("精油", "挥发油", "essential oil", "volatile oil"),
    "果胶": ("果胶", "pectin"),
    "果酒/果醋": ("果酒", "果醋", "wine", "vinegar"),
    "果脯/蜜饯": ("果脯", "蜜饯", "candied citrus"),
    "柑橘干片": ("干片", "烘干片", "冻干", "dried slice", "freeze-dried"),
}

PRODUCT_CATEGORY = {
    "陈皮": "陈皮",
    "柑橘汁": "橙汁",
    "浓缩汁": "橙汁",
    "精油": "精油",
    "果胶": "果胶",
}

SCALE_ALIASES = {
    "lab": ("实验室", "实验规模", "小试", "bench scale", "laboratory", "lab-scale"),
    "pilot": ("中试", "放大试验", "pilot", "pilot-scale"),
    "industrial": ("工业", "量产", "生产线", "commercial", "industrial", "factory"),
}

EQUIPMENT_ALIASES = (
    "清洗机", "榨汁机", "破碎机", "压榨机", "过滤器", "离心机", "均质机", "脱气机",
    "杀菌机", "灌装机", "热风干燥箱", "真空干燥机", "冻干机", "冷库", "蒸发器",
    "膜设备", "发酵罐", "centrifuge", "homogenizer", "pasteurizer", "evaporator",
)

QUALITY_TERMS = (
    "可溶性固形物", "糖度", "酸度", "糖酸比", "水分", "水分活度", "色差", "浊度",
    "出汁率", "维生素C", "总酚", "黄酮", "菌落总数", "霉菌", "酵母", "感官",
    "Brix", "titratable acidity", "turbidity", "yield", "moisture", "water activity",
)

PARAMETER_REQUEST_TERMS = (
    "温度", "时间", "pH", "料液比", "浓度", "压力", "转速", "流量", "酶用量",
    "添加剂用量", "水分", "糖度", "酸度", "temperature", "time", "ratio",
    "concentration", "pressure", "speed", "flow", "dosage", "moisture", "Brix",
)

STEP_ALIASES: dict[str, tuple[str, ...]] = {
    "原料验收": ("原料验收", "原料筛选", "分选", "挑选", "成熟度", "raw material", "sorting"),
    "清洗消毒": ("清洗", "消毒", "冲洗", "wash", "washing", "sanitize", "disinfection"),
    "去皮/取皮": ("去皮", "取皮", "开皮", "peeling", "peeled"),
    "破碎/榨汁": ("破碎", "榨汁", "压榨", "打浆", "crushing", "juicing", "pressing", "extraction"),
    "护色": ("护色", "抗坏血酸", "褐变", "browning", "ascorbic acid"),
    "酶解": ("酶解", "果胶酶", "纤维素酶", "enzyme", "enzymatic", "pectinase"),
    "澄清": ("澄清", "clarification", "flotation", "fining"),
    "过滤/离心": ("过滤", "离心", "超滤", "微滤", "filtration", "centrifug", "ultrafiltration"),
    "均质": ("均质", "homogenization", "homogenisation", "HPH"),
    "脱气": ("脱气", "deaeration", "de-aeration"),
    "浓缩": ("浓缩", "蒸发", "膜浓缩", "concentration", "evaporation"),
    "杀菌": ("杀菌", "巴氏", "灭菌", "pasteur", "steriliz", "thermal treatment", "high pressure processing", "HHP", "thermosonication", "ultrasound", "cold plasma", "electric field"),
    "干燥": ("干燥", "烘干", "晒干", "冻干", "drying", "dehydration", "freeze-drying"),
    "陈化": ("陈化", "陈放", "aging", "ageing", "maturation"),
    "发酵": ("发酵", "fermentation"),
    "包装/灌装": ("包装", "灌装", "封口", "packaging", "filling", "bottling"),
    "储藏": ("储藏", "贮藏", "保存", "货架期", "storage", "shelf life"),
}

METHOD_TAGS: dict[str, tuple[str, ...]] = {
    "热风": ("热风", "hot air"),
    "真空": ("真空", "vacuum"),
    "冻干": ("冻干", "freeze-dry", "freeze dry", "lyophil"),
    "喷雾": ("喷雾干燥", "spray dry"),
    "高压": ("高压处理", "高压均质", "high pressure", "high-pressure", "MPa", "HPP", "HPH"),
    "膜处理": ("超滤", "微滤", "反渗透", "membrane", "ultrafiltration", "microfiltration"),
    "热处理": ("热处理", "巴氏", "thermal treatment", "pasteur"),
    "超声/热超声": ("超声", "ultrasound", "thermosonication", "sonication"),
    "冷等离子体": ("冷等离子体", "cold plasma"),
    "电场处理": ("电场", "electric field"),
    "辐照": ("辐照", "irradiation"),
}

PROCESS_DATA_TERMS = tuple(
    term for terms in STEP_ALIASES.values() for term in terms
) + (
    "温度", "时间", "压力", "转速", "浓度", "料液比", "添加量", "流量", "pH",
    "temperature", "time", "pressure", "speed", "concentration", "ratio", "dosage", "flow",
)

ANALYTICAL_TITLE_TERMS = (
    "dna", "pcr", "barcoding", "metabolomic", "metabonomic", "nmr", "chromatograph",
    "mass spectrom", "spectroscopic", "marker", "aroma active compounds", "cell line", "hepg2",
    "基因", "代谢组", "指纹图谱", "色谱", "质谱", "细胞",
)

ANALYTICAL_SENTENCE_TERMS = (
    "was measured", "were measured", "was analyzed", "were analyzed", "was analysed", "were analysed",
    "methodology", "colorimeter", "spectrophot", "chromatograph", "enzyme activity", "assay",
    "experimental data", "fitted to the equation", "sample preparation", "adjusted to ph", "was monitored", "were monitored",
    "测定", "检测方法", "分析方法", "酶活性", "色差仪", "分光光度", "色谱", "质谱",
)

ALLOWED_STEPS = {
    "陈皮": {"原料验收", "清洗消毒", "去皮/取皮", "干燥", "陈化", "包装/灌装", "储藏"},
    "柑橘汁": {"原料验收", "清洗消毒", "破碎/榨汁", "护色", "酶解", "澄清", "过滤/离心", "均质", "脱气", "杀菌", "包装/灌装", "储藏"},
    "浓缩汁": {"原料验收", "清洗消毒", "破碎/榨汁", "护色", "酶解", "澄清", "过滤/离心", "浓缩", "均质", "脱气", "杀菌", "包装/灌装", "储藏"},
}

UNIT_PATTERN = r"(?:°\s*C|°C|℃|K|MPa|kPa|Pa|bar|psi|rpm|r/min|mL/min|L/min|kg/h|L/h|h|min|s|d|小时|分钟|秒|天|%|mg/L|g/L|mg/kg|g/kg|U/g|U/mL|IU/mL|°Brix|Brix)"
NUMBER_PATTERN = r"(?<![A-Za-z0-9])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
RANGE_SEPARATOR = r"(?:\s*(?:-|–|—|~|～|至|到)\s*)"


PARAMETER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pH", re.compile(rf"(?i)\bpH\s*(?:值|of|=|:|为|was|at)?\s*(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?")),
    ("温度", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>[°º]\s*[Cc]|℃|K(?![A-Za-z]))")),
    ("压力", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>MPa|Mpa|kPa|KPa|Pa|bar|psi)(?![A-Za-z])", re.I)),
    ("转速", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>rpm|r/min)", re.I)),
    ("流量", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>mL/min|L/min|kg/h|L/h)", re.I)),
    ("可溶性固形物", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>°Brix|Brix)", re.I)),
    ("时间", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>小时|分钟|秒|天|h|hr|hrs|min|mins|s|sec|secs|d|day|days)(?![A-Za-z])", re.I)),
    ("用量/浓度", re.compile(rf"(?P<value>{NUMBER_PATTERN})(?:{RANGE_SEPARATOR}(?P<end>{NUMBER_PATTERN}))?\s*(?P<unit>%|mg/L|g/L|mg/kg|g/kg|U/g|U/mL|IU/mL)", re.I)),
    ("料液比", re.compile(rf"(?i)(?:料液比|固液比|material.{{0,8}}liquid ratio|solid.{{0,8}}liquid ratio)\s*(?:为|=|:)?\s*(?P<value>{NUMBER_PATTERN})\s*[:∶]\s*(?P<end>{NUMBER_PATTERN})")),
)

MISSING_UNIT_PATTERN = re.compile(
    rf"(?P<name>酶(?:添加)?量|添加剂(?:添加)?量|浓度|温度|时间|压力|转速|流量|enzyme dosage|concentration|temperature|time|pressure)"
    rf"\s*(?:为|是|=|:|was|of)?\s*(?P<value>{NUMBER_PATTERN})(?!\s*{UNIT_PATTERN})",
    re.I,
)


ROUTE_STEPS = {
    "陈皮": ["原料验收", "分选", "清洗", "开皮取皮", "干燥", "回软/整理", "陈化", "分级检测", "包装", "储藏"],
    "柑橘汁": ["原料验收", "分选", "清洗消毒", "破碎/榨汁", "护色", "酶解/澄清", "过滤", "糖酸调整", "均质", "脱气", "杀菌", "灌装包装", "储藏"],
    "浓缩汁": ["原料验收", "清洗分选", "破碎/榨汁", "澄清过滤", "浓缩", "均质脱气", "杀菌灌装", "储藏"],
}

STEP_OPERATIONS = {
    "原料验收": "核对品种、产地、成熟度、外观、可溶性固形物、酸度和安全检测；不合格原料隔离。",
    "分选": "剔除霉变、腐烂、异味、严重机械伤及混入异物的果实。",
    "清洗": "去除泥沙与表面杂质；消毒剂种类和浓度必须按适用法规及企业验证确定。",
    "清洗消毒": "清洗后采用经验证的消毒程序，并控制残留及交叉污染。",
    "开皮取皮": "按目标产品取皮，控制果肉残留、破损和批次混合。",
    "破碎/榨汁": "采用与原料和设备匹配的破碎或榨汁方式，记录出汁率及苦味物质带入风险。",
    "护色": "减少氧暴露并按证据决定是否采用护色剂；没有直接证据时不指定添加量。",
    "酶解/澄清": "依据目标浊度和口感选择酶解或澄清；温度、时间和用量必须成组验证。",
    "过滤": "按目标浊度选择过滤或离心，监控通量、压差和可溶性固形物损失。",
    "糖酸调整": "先测可溶性固形物、可滴定酸和糖酸比，再按产品标准及配方审批调整。",
    "均质": "依据悬浮稳定性和设备能力确定压力及循环次数，避免过度升温。",
    "脱气": "降低溶解氧，减缓氧化和香气损失；真空度和时间需设备验证。",
    "杀菌": "按目标微生物、pH、包装和冷链条件验证杀菌强度，不跨产品套用参数。",
    "干燥": "按干燥方式控制温度、时间、终点水分和外观；不同设备参数不可直接互换。",
    "回软/整理": "均衡水分并整理形态，防止局部返潮；目前缺少证据时由企业SOP定参。",
    "陈化": "建立温湿度、虫霉监测和翻仓记录，陈化年限与质量结论需可追溯。",
    "分级检测": "按目标产品检测感官、理化、微生物及食品安全指标后分级。",
    "灌装包装": "采用与杀菌和储藏方案匹配的灌装及阻隔包装，记录密封完整性。",
    "包装": "使用防潮、避光且适配产品的包装，记录批号和密封完整性。",
    "储藏": "按经验证的温湿度和避光要求储藏，货架期必须由稳定性或法规依据支持。",
}

EQUIPMENT_MAP = {
    "陈皮": [
        {"primary": "分选台/输送分选线", "alternative": "食品级人工分选台", "stage": "原料验收与分选"},
        {"primary": "清洗机", "alternative": "可控流量喷淋槽", "stage": "清洗"},
        {"primary": "开皮/取皮工位", "alternative": "食品级手工开皮工具", "stage": "开皮取皮"},
        {"primary": "可控温湿干燥设备", "alternative": "热风、真空或冻干设备须分别验证", "stage": "干燥"},
        {"primary": "温湿度记录仓", "alternative": "带连续记录仪的洁净储藏间", "stage": "陈化储藏"},
    ],
    "柑橘汁": [
        {"primary": "分选清洗线", "alternative": "分选台+喷淋清洗槽", "stage": "验收与清洗"},
        {"primary": "柑橘榨汁机", "alternative": "破碎机+食品级压榨机", "stage": "榨汁"},
        {"primary": "酶解/澄清罐", "alternative": "带温控和搅拌的食品级罐", "stage": "酶解澄清"},
        {"primary": "过滤器/离心机", "alternative": "按目标浊度选择板框、膜过滤或离心", "stage": "固液分离"},
        {"primary": "均质机、脱气机", "alternative": "设备缺失时须通过对照小试评估稳定性和氧化风险", "stage": "稳定化"},
        {"primary": "连续杀菌及无菌/热灌装线", "alternative": "批式杀菌仅可在热穿透验证后采用", "stage": "杀菌灌装"},
    ],
    "浓缩汁": [
        {"primary": "榨汁与澄清设备", "alternative": "破碎压榨+过滤/离心", "stage": "取汁澄清"},
        {"primary": "真空蒸发器或膜浓缩设备", "alternative": "两种路线参数与产品风味影响不可直接互换", "stage": "浓缩"},
        {"primary": "杀菌灌装线", "alternative": "批式设备须完成热穿透和密封验证", "stage": "稳定化包装"},
    ],
}

QUALITY_CHECKS = {
    "陈皮": ["感官与外观分级", "终点水分/水分活度", "挥发性成分或特征成分（按用途）", "霉菌与微生物", "农残与重金属", "虫害和仓储霉变记录"],
    "柑橘汁": ["可溶性固形物（°Brix）", "可滴定酸与糖酸比", "pH", "色泽和浊度/悬浮稳定性", "出汁率", "维生素C或香气保留（按目标）", "菌落总数、霉菌和酵母", "包装密封与储藏稳定性"],
    "浓缩汁": ["可溶性固形物（°Brix）", "可滴定酸和pH", "黏度与色泽", "复水稳定性", "微生物", "包装密封与储藏稳定性"],
}


def _text(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if value not in (None, ""))


def _contains(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _first_product(text: str) -> str:
    lower = text.lower()
    for product, aliases in PRODUCT_ALIASES.items():
        if any(alias.lower() in lower for alias in aliases):
            return product
    return "柑橘加工品"


def _scale(text: str) -> str:
    lower = text.lower()
    for scale, aliases in SCALE_ALIASES.items():
        if any(alias.lower() in lower for alias in aliases):
            return scale
    return "unknown"


def analyze_processing_intent(
    user_text: str,
    batch: dict[str, Any] | None = None,
    direction: str = "",
) -> dict[str, Any]:
    """Extract processing facets deterministically without another model call."""
    batch = batch or {}
    combined = _text(user_text, direction, batch.get("variety"), batch.get("origin"), batch.get("customer_type"))
    targets = [product for product, aliases in PRODUCT_ALIASES.items() if _contains(combined, aliases)]
    if not targets:
        inferred = _first_product(direction)
        targets = [inferred] if inferred != "柑橘加工品" else []
    operations = [step for step, aliases in STEP_ALIASES.items() if _contains(combined, aliases)]
    quality_goals = [term for term in QUALITY_TERMS if term.lower() in combined.lower()]
    equipment = [term for term in EQUIPMENT_ALIASES if term.lower() in combined.lower()]
    raw_material = _text(batch.get("origin"), batch.get("variety")) or "柑橘原料（品种待确认）"
    return {
        "raw_material": raw_material,
        "origin": str(batch.get("origin") or ""),
        "variety": str(batch.get("variety") or ""),
        "maturity": str(batch.get("maturity") or batch.get("ripeness") or ""),
        "target_products": targets,
        "primary_product": targets[0] if targets else "柑橘加工品",
        "operations": operations,
        "parameter_targets": [term for term in PARAMETER_REQUEST_TERMS if term.lower() in combined.lower()],
        "scale": _scale(combined),
        "equipment": equipment,
        "quality_goals": quality_goals,
        "user_request": user_text.strip(),
    }


def build_processing_subquestions(intent: dict[str, Any]) -> list[dict[str, Any]]:
    product = str(intent.get("primary_product") or "柑橘加工品")
    raw = str(intent.get("raw_material") or "柑橘")
    category = PRODUCT_CATEGORY.get(product)
    common = f"{raw} {product} 材料与方法 工艺参数 实验条件 结果 quality"
    specs = [
        {"id": "route", "facet": "工艺路线", "query": f"{common} 完整工艺流程 process flow unit operation", "category": category},
        {"id": "raw", "facet": "原料要求", "query": f"{common} 原料 成熟度 可溶性固形物 酸度 水分 raw material maturity Brix acidity", "category": category},
        {"id": "pretreatment", "facet": "前处理", "query": f"{common} 分选 清洗 消毒 去皮 破碎 护色 pretreatment washing crushing", "category": category},
        {"id": "parameters", "facet": "加工参数", "query": f"{common} 温度 时间 pH 料液比 压力 转速 酶用量 concentration temperature time pressure", "category": category},
        {"id": "quality", "facet": "质量评价", "query": f"{common} 质量指标 感官 色泽 得率 微生物 stability quality evaluation", "category": category},
        {"id": "packaging", "facet": "包装储藏", "query": f"{common} 包装 灌装 储藏 温度 货架期 packaging storage shelf life", "category": category},
        {"id": "safety", "facet": "安全控制", "query": f"{common} 食品安全 HACCP 微生物 农残 重金属 标准 safety", "category": category},
        {"id": "byproduct", "facet": "副产物", "query": f"{raw} {product} 果皮 果渣 废水 副产物 综合利用 byproduct waste valorization", "category": None},
    ]
    if product == "陈皮":
        specs.insert(3, {"id": "drying", "facet": "干燥", "query": f"{raw} 陈皮 柑橘果皮 热风 真空 冻干 温度 时间 终点水分 drying temperature time moisture methods", "category": "陈皮"})
        specs.insert(4, {"id": "aging", "facet": "陈化", "query": f"{raw} 陈皮 陈化 仓储 温度 湿度 年限 黄酮 挥发油 aging storage methods results", "category": "陈皮"})
    elif product in {"柑橘汁", "浓缩汁"}:
        specs.insert(3, {"id": "clarification", "facet": "酶解澄清", "query": f"{raw} 橙汁 果汁 果胶酶 酶解 澄清 温度 时间 用量 filtration clarification pectinase methods", "category": "橙汁"})
        specs.insert(4, {"id": "homogenization", "facet": "均质脱气", "query": f"{raw} 橙汁 NFC 高压均质 脱气 压力 循环 温度 悬浮稳定 homogenization pressure deaeration methods", "category": "橙汁"})
        specs.insert(5, {"id": "stabilization", "facet": "杀菌稳定化", "query": f"{raw} 橙汁 杀菌 温度 时间 微生物 热处理 高压 冷等离子 pasteurization microbial inactivation methods", "category": "橙汁"})
    return specs[:12]


def _parameter_signal(text: str) -> float:
    unit_hits = len(re.findall(rf"{NUMBER_PATTERN}\s*{UNIT_PATTERN}", text, re.I))
    named_hits = sum(1 for term in PROCESS_DATA_TERMS if term.lower() in text.lower())
    return min(1.0, unit_hits * 0.12 + named_hits * 0.025)


def _processing_rerank(item: dict[str, Any], spec: dict[str, Any], intent: dict[str, Any]) -> float:
    text = _text(item.get("title"), item.get("section"), item.get("chunk_text"))
    section = str(item.get("section") or "").lower()
    base = min(1.0, float(item.get("match_score") or 0) / 100.0)
    parameter_signal = _parameter_signal(text)
    methods = 1.0 if any(term in section for term in ("方法", "materials", "methods", "工艺")) else 0.0
    results = 1.0 if any(term in section for term in ("结果", "result", "讨论", "discussion")) else 0.0
    facet_terms = [term for term in re.split(r"\s+", str(spec.get("query") or "")) if len(term) > 1]
    facet_match = min(1.0, sum(term.lower() in text.lower() for term in facet_terms) / max(min(len(facet_terms), 10), 1))
    product = str(intent.get("primary_product") or "")
    product_match = 1.0 if _contains(text, PRODUCT_ALIASES.get(product, (product,))) else 0.0
    background_penalty = 0.18 if parameter_signal == 0 and not methods and not results else 0.0
    return 0.36 * base + 0.25 * parameter_signal + 0.13 * methods + 0.09 * results + 0.09 * facet_match + 0.08 * product_match - background_penalty


def _product_relevant(title: str, text: str, product: str, facet: str) -> bool:
    lower = text.lower()
    title_lower = title.lower()
    citrus = _contains(lower, ("柑橘", "柑", "橘", "橙", "citrus", "orange", "mandarin", "tangerine", "chachi"))
    citrus_title = _contains(title_lower, ("柑橘", "柑", "橘", "橙", "citrus", "orange", "mandarin", "tangerine", "chachi"))
    if facet == "副产物":
        return citrus and citrus_title
    if product in {"柑橘汁", "浓缩汁"}:
        juice = _contains(lower, ("果汁", "橙汁", "柑橘汁", "juice", "nfc", "concentrate"))
        juice_title = _contains(title_lower, ("果汁", "橙汁", "柑橘汁", "juice", "nfc", "concentrate"))
        return citrus and juice and (citrus_title or juice_title)
    if product == "陈皮":
        return _contains(title_lower, PRODUCT_ALIASES["陈皮"]) or (
            citrus and citrus_title and _contains(lower, ("果皮", "橘皮", "peel", "pericarp"))
        )
    aliases = PRODUCT_ALIASES.get(product)
    return (_contains(lower, aliases) and _contains(title_lower, aliases)) if aliases else (citrus and citrus_title)


def retrieve_processing_evidence(
    intent: dict[str, Any],
    product_filter: str = "柑橘",
    top_k: int = PROCESS_EVIDENCE_TOP_K,
    search_fn: SearchFunction = comprehensive_search_knowledge,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Retrieve each process facet independently, then rerank and diversify evidence."""
    specs = build_processing_subquestions(intent)
    per_facet: list[list[dict[str, Any]]] = []
    for spec in specs:
        try:
            items = search_fn(
                query=str(spec["query"]),
                product_filter=product_filter,
                category_filter=spec.get("category"),
                top_k=PROCESS_SUBQUERY_TOP_K,
            )
        except TypeError:
            items = search_fn(str(spec["query"]), product_filter, PROCESS_SUBQUERY_TOP_K)
        ranked = []
        for source in items:
            item = dict(source)
            source_title = str(item.get("title") or "")
            source_text = _text(source_title, item.get("chunk_text"))
            if not _product_relevant(source_title, source_text, str(intent.get("primary_product") or ""), str(spec["facet"])):
                continue
            if (
                any(term in source_title.lower() for term in ANALYTICAL_TITLE_TERMS)
                and spec["facet"] in {"工艺路线", "前处理", "加工参数", "干燥", "陈化", "包装储藏"}
            ):
                continue
            score = _processing_rerank(item, spec, intent)
            item["processing_score"] = round(max(0.0, score) * 100, 3)
            item["processing_facet"] = spec["facet"]
            item["processing_subquestion_id"] = spec["id"]
            item["parameter_scope_eligible"] = spec["facet"] != "副产物"
            item["retrieval_method"] = "processing_faceted_hybrid+" + str(item.get("retrieval_method") or "hybrid")
            if score >= 0.16:
                ranked.append(item)
        ranked.sort(key=lambda row: float(row.get("processing_score") or 0), reverse=True)
        per_facet.append(ranked)

    selected: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    document_counts: Counter[str] = Counter()

    def add(item: dict[str, Any]) -> bool:
        chunk_id = str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page') or item.get('page_start')}")
        document_id = str(item.get("document_id") or item.get("source_file") or item.get("title"))
        if chunk_id in seen_chunks or document_counts[document_id] >= 2:
            return False
        seen_chunks.add(chunk_id)
        document_counts[document_id] += 1
        selected.append(item)
        return True

    for items in per_facet:
        if items:
            add(items[0])
        if len(selected) >= top_k:
            return selected[:top_k], specs
    pool = sorted((item for items in per_facet for item in items), key=lambda row: float(row.get("processing_score") or 0), reverse=True)
    for item in pool:
        add(item)
        if len(selected) >= top_k:
            break
    return selected, specs


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;])|(?<=[A-Za-z\)])\.(?=\s+[A-Z])|\n+", text)
        if part.strip()
    ]


def _infer_step(text: str, position: int | None = None) -> str:
    lower = text.lower()
    matches: list[tuple[int, int, str]] = []
    for step, aliases in STEP_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.lower()
            start = 0
            while (found := lower.find(alias_lower, start)) >= 0:
                distance = found if position is None else abs(found - position)
                # Prefer an operation named just before its parameter.
                direction_penalty = 0 if position is None or found <= position else 18
                matches.append((distance + direction_penalty, found, step))
                start = found + max(1, len(alias_lower))
    return min(matches)[2] if matches else "未明确单元操作"


def _infer_parameter_name(default: str, sentence: str, start: int) -> str:
    nearby = sentence[max(0, start - 70): start + 80].lower()
    if default == "用量/浓度":
        if any(term in nearby for term in ("moisture", "水分", "含水率")):
            return "水分"
        if any(term in nearby for term in ("acid", "acidity", "酸度")):
            return "酸度"
        if any(term in nearby for term in ("yield", "得率", "出汁率")):
            return "得率"
        dosage_signal = any(term in nearby for term in ("用量", "添加量", "剂量", "浓度", "dosage", "dose", "concentration", "added", "使用", "used"))
        if dosage_signal and any(term in nearby for term in ("enzyme", "酶", "pectinase", "cellulase")):
            return "酶用量"
        if dosage_signal and any(term in nearby for term in ("添加剂", "抗坏血酸", "ascorbic", "nisin", "防腐", "稳定剂")):
            return "添加剂用量"
        return "浓度" if dosage_signal else ""
    return default


def _infer_raw_material(text: str, fallback: str) -> str:
    aliases = (
        "茶枝柑", "新会柑", "脐橙", "甜橙", "温州蜜柑", "南丰蜜桔", "沃柑", "柠檬", "柚",
        "orange", "mandarin", "tangerine", "chachi", "lemon", "grapefruit", "pomelo",
        "citrus", "carrot", "apple", "strawberry", "milk", "almond", "pineapple", "grape", "mango", "maqui",
        "胡萝卜", "苹果", "草莓", "牛奶", "杏仁", "菠萝", "葡萄", "芒果",
    )
    lower = text.lower()
    found = [alias for alias in aliases if alias.lower() in lower]
    if found and any(alias.lower() in fallback.lower() for alias in found):
        return fallback
    return "、".join(found[:3]) if found else fallback


def _infer_method(text: str) -> str:
    lower = text.lower()
    return "/".join(tag for tag, aliases in METHOD_TAGS.items() if any(alias.lower() in lower for alias in aliases)) or "未标明方法"


def _material_compatible(source_raw: str, target_raw: str) -> bool:
    non_citrus = (
        "carrot", "apple", "strawberry", "milk", "almond", "pineapple", "grape", "mango", "maqui",
        "胡萝卜", "苹果", "草莓", "牛奶", "杏仁", "菠萝", "葡萄", "芒果",
    )
    source_lower = source_raw.lower()
    target_lower = target_raw.lower()
    return not any(term in source_lower and term not in target_lower for term in non_citrus)


def _source_location(item: dict[str, Any]) -> str:
    section = str(item.get("section") or "正文")
    start = item.get("page") or item.get("page_start")
    end = item.get("page_end")
    if start and end and str(start) != str(end):
        return f"{section}，第{start}-{end}页"
    return f"{section}，第{start}页" if start else f"{section}，页码未标注"


def _step_allowed(product: str, step: str) -> bool:
    allowed = ALLOWED_STEPS.get(product)
    return step != "未明确单元操作" and (allowed is None or step in allowed)


def _parameter_id(record: dict[str, Any]) -> str:
    seed = "|".join(str(record.get(key) or "") for key in (
        "source_id", "source_location", "process_step", "parameter_name", "value", "unit", "conditions"
    ))
    return "par_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _effect_sentence(sentences: list[str], index: int) -> str:
    candidates = sentences[index:index + 2]
    for sentence in candidates:
        if _contains(sentence, ("提高", "降低", "改善", "影响", "增加", "减少", "保持", "yield", "quality", "color", "stability", "increased", "decreased", "effect")):
            return sentence[:360]
    return "文献片段未明确报告该参数对质量的单独影响。"


def extract_processing_parameters(
    evidence: list[dict[str, Any]],
    intent: dict[str, Any],
    limit: int = PROCESS_PARAMETER_LIMIT,
) -> list[dict[str, Any]]:
    """Conservatively extract directly reported process conditions with provenance."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    product = str(intent.get("primary_product") or "柑橘加工品")
    fallback_raw = str(intent.get("raw_material") or "柑橘原料")
    for item in evidence:
        if item.get("parameter_scope_eligible") is False:
            continue
        title_lower = str(item.get("title") or "").lower()
        if any(term in title_lower for term in ANALYTICAL_TITLE_TERMS):
            continue
        chunk_text = str(item.get("chunk_text") or "")
        sentences = _sentences(chunk_text)
        section = str(item.get("section") or "正文")
        direct_section = any(term in section.lower() for term in ("方法", "materials", "methods", "结果", "result", "工艺"))
        for sentence_index, sentence in enumerate(sentences):
            if len(sentence) > 1600:
                sentence = sentence[:1600]
            process_signal = _contains(sentence, PROCESS_DATA_TERMS)
            for default_name, pattern in PARAMETER_PATTERNS:
                for match in pattern.finditer(sentence):
                    if not process_signal and default_name not in {"pH", "可溶性固形物", "料液比"}:
                        continue
                    value = match.group("value").replace(",", "")
                    end_raw = match.groupdict().get("end")
                    end = end_raw.replace(",", "") if end_raw else None
                    unit = (match.groupdict().get("unit") or "").replace("º", "°").replace("° C", "°C")
                    parameter_name = _infer_parameter_name(default_name, sentence, match.start())
                    if not parameter_name:
                        continue
                    if parameter_name == "pH" and not (0 <= float(value) <= 14 and (not end or 0 <= float(end) <= 14)):
                        continue
                    if parameter_name == "pH" and product in {"柑橘汁", "浓缩汁"} and not (1.5 <= float(value) <= 6.5):
                        continue
                    if parameter_name == "温度" and (float(value) > 130 or (end and float(end) > 130)):
                        continue
                    if parameter_name == "时间" and unit.lower() in {"h", "hr", "hrs"}:
                        tail = sentence[match.end():match.end() + 4]
                        if re.match(r"\s*z", tail, re.I):
                            continue
                    step = _infer_step(sentence, match.start())
                    if step == "未明确单元操作":
                        step = _infer_step(str(item.get("title") or ""))
                    analytical_context = _contains(sentence, ANALYTICAL_SENTENCE_TERMS)
                    confidence = 0.76 if direct_section else 0.62
                    if step == "未明确单元操作":
                        confidence -= 0.16
                    conditions = sentence[:520]
                    method = _infer_method(sentence)
                    if method == "未标明方法":
                        method = _infer_method(str(item.get("title") or ""))
                    record = {
                        "product": product,
                        "raw_material": _infer_raw_material(_text(item.get("title"), sentence), fallback_raw),
                        "process_step": step,
                        "parameter_name": parameter_name,
                        "value": value if not end else "",
                        "unit": unit,
                        "range": f"{value}–{end}" if end else "",
                        "conditions": conditions,
                        "scale": _scale(_text(item.get("title"), chunk_text)),
                        "effect_on_quality": _effect_sentence(sentences, sentence_index),
                        "source_id": str(item.get("document_id") or item.get("source_file") or item.get("chunk_id") or ""),
                        "source_location": _source_location(item),
                        "confidence": round(max(0.05, min(0.95, confidence)), 2),
                        "title": str(item.get("title") or "未命名文献"),
                        "year": str(item.get("year") or "年份未知"),
                        "process_method": method,
                        "evidence_type": "文献直接报告",
                        "unit_missing": False,
                        "eligible_for_recommendation": _step_allowed(product, step) and parameter_name != "得率" and not analytical_context,
                        "analytical_context": analytical_context,
                    }
                    record["parameter_id"] = _parameter_id(record)
                    if record["parameter_id"] not in seen:
                        records.append(record)
                        seen.add(record["parameter_id"])
                    if len(records) >= limit:
                        return records
            for match in MISSING_UNIT_PATTERN.finditer(sentence):
                name = match.group("name")
                # A valid unit may begin after a punctuation/space sequence that the negative lookahead missed.
                tail = sentence[match.end():match.end() + 16]
                if re.match(rf"\s*{UNIT_PATTERN}", tail, re.I):
                    continue
                parameter_name = "酶用量" if "酶" in name or "enzyme" in name.lower() else name
                record = {
                    "product": product,
                    "raw_material": _infer_raw_material(_text(item.get("title"), sentence), fallback_raw),
                    "process_step": _infer_step(sentence, match.start()),
                    "parameter_name": parameter_name,
                    "value": match.group("value"),
                    "unit": "",
                    "range": "",
                    "conditions": sentence[:520],
                    "scale": _scale(_text(item.get("title"), chunk_text)),
                    "effect_on_quality": "单位缺失，不能据此形成生产建议。",
                    "source_id": str(item.get("document_id") or item.get("source_file") or item.get("chunk_id") or ""),
                    "source_location": _source_location(item),
                    "confidence": 0.2,
                    "title": str(item.get("title") or "未命名文献"),
                    "year": str(item.get("year") or "年份未知"),
                    "process_method": _infer_method(sentence),
                    "evidence_type": "文献直接报告（单位缺失）",
                    "unit_missing": True,
                    "eligible_for_recommendation": False,
                }
                record["parameter_id"] = _parameter_id(record)
                if record["parameter_id"] not in seen:
                    records.append(record)
                    seen.add(record["parameter_id"])
                if len(records) >= limit:
                    return records
    return records


def _numeric_interval(record: dict[str, Any]) -> tuple[float, float] | None:
    try:
        if record.get("range"):
            values = re.findall(NUMBER_PATTERN, str(record["range"]))
            if len(values) >= 2:
                return min(float(values[0]), float(values[1])), max(float(values[0]), float(values[1]))
        if record.get("value") not in (None, ""):
            value = float(record["value"])
            return value, value
    except (TypeError, ValueError):
        return None
    return None


def _ranges_consistent(intervals: list[tuple[float, float]]) -> bool:
    if len(intervals) < 2:
        return True
    low = max(item[0] for item in intervals)
    high = min(item[1] for item in intervals)
    if low <= high:
        return True
    overall_low = min(item[0] for item in intervals)
    overall_high = max(item[1] for item in intervals)
    span = max(overall_high - overall_low, abs(overall_high) * 0.05, 1e-9)
    smallest_gap = min(abs(a[0] - b[1]) for a in intervals for b in intervals if a is not b)
    return smallest_gap / span <= 0.18


def aggregate_parameter_evidence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-check records without mixing product, material, method or scale."""
    grouped: defaultdict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            str(record.get("product") or ""),
            str(record.get("raw_material") or ""),
            str(record.get("process_step") or ""),
            str(record.get("parameter_name") or ""),
            str(record.get("unit") or ""),
            str(record.get("scale") or "unknown"),
            str(record.get("process_method") or "未标明方法"),
        )
        grouped[key].append(record)
    aggregates: list[dict[str, Any]] = []
    for key, items in grouped.items():
        product, raw, step, name, unit, scale, method = key
        source_ids = list(dict.fromkeys(str(item.get("source_id") or "") for item in items if item.get("source_id")))
        eligible = [item for item in items if item.get("eligible_for_recommendation") and not item.get("unit_missing")]
        intervals = [interval for item in eligible if (interval := _numeric_interval(item)) is not None]
        consistent = _ranges_consistent(intervals)
        conflict = len(intervals) >= 2 and not consistent
        if not unit and name != "pH":
            trust = "低可信度"
            recommendation = "单位缺失，不形成推荐参数"
        elif conflict:
            trust = "低可信度"
            recommendation = "文献参数冲突，保留各方案并按条件开展对照小试"
        elif len(source_ids) >= 2 and len(eligible) >= 2:
            trust = "高可信度"
            recommendation = f"{min(item[0] for item in intervals):g}–{max(item[1] for item in intervals):g} {unit}" if intervals else "多篇文献一致支持"
        elif eligible:
            trust = "中可信度"
            item = eligible[0]
            reported = item.get("range") or item.get("value")
            recommendation = f"{reported} {unit}".strip() + "（单篇文献直接报告，需小试验证）"
        else:
            trust = "低可信度"
            recommendation = "现有知识库证据不足"
        alternatives = [
            {
                "reported": f"{item.get('range') or item.get('value')} {item.get('unit') or '[单位缺失]'}".strip(),
                "conditions": item.get("conditions"),
                "scale": item.get("scale"),
                "source_id": item.get("source_id"),
                "source_location": item.get("source_location"),
                "title": item.get("title"),
                "year": item.get("year"),
            }
            for item in items
        ]
        aggregates.append({
            "product": product,
            "raw_material": raw,
            "process_step": step,
            "parameter_name": name,
            "unit": unit,
            "scale": scale,
            "process_method": method,
            "recommended_range": recommendation,
            "confidence_level": trust,
            "confidence": round(sum(float(item.get("confidence") or 0) for item in items) / max(len(items), 1), 2),
            "source_ids": source_ids,
            "evidence_count": len(items),
            "conflict": conflict,
            "alternatives": alternatives,
            "basis_type": "多文献归纳" if len(source_ids) >= 2 and not conflict else "文献直接报告",
            "applicability": f"原料：{raw}；规模：{scale}；方法：{method}",
            "recommendable": bool(eligible),
            "effect_summary": next(
                (
                    str(item.get("effect_on_quality"))
                    for item in items
                    if item.get("effect_on_quality")
                    and "未明确报告" not in str(item.get("effect_on_quality"))
                ),
                "文献片段未把该参数对质量的影响单独量化，改变参数前需做对照小试。",
            ),
        })
    trust_order = {"高可信度": 0, "中可信度": 1, "低可信度": 2}
    aggregates.sort(key=lambda row: (trust_order.get(str(row["confidence_level"]), 3), str(row["process_step"]), str(row["parameter_name"])))
    return aggregates


def _step_matches(route_step: str, evidence_step: str) -> bool:
    route_terms = set(re.split(r"[/、]", route_step))
    evidence_terms = set(re.split(r"[/、]", evidence_step))
    return bool(route_terms & evidence_terms) or route_step in evidence_step or evidence_step in route_step


def build_parameterized_process_plan(
    intent: dict[str, Any],
    parameter_groups: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    product = str(intent.get("primary_product") or "柑橘加工品")
    target_raw = str(intent.get("raw_material") or "")
    flow = ROUTE_STEPS.get(product, ["原料验收", "分选", "清洗", "前处理", "核心加工", "稳定化", "包装", "储藏"])
    rows: list[dict[str, Any]] = []
    for step in flow:
        matching = [
            group
            for group in parameter_groups
            if group.get("recommendable")
            and _material_compatible(str(group.get("raw_material") or ""), target_raw)
            and _step_matches(step, str(group.get("process_step") or ""))
        ]
        sources = list(dict.fromkeys(source for group in matching for source in group.get("source_ids", [])))
        rows.append({
            "step": step,
            "operation": STEP_OPERATIONS.get(step, "按该单元操作的企业SOP执行，并记录输入、输出、设备和偏差。"),
            "parameters": [
                {
                    "name": group["parameter_name"],
                    "recommendation": group["recommended_range"],
                    "confidence": group["confidence_level"],
                    "scale": group["scale"],
                    "method": group["process_method"],
                    "raw_material": group["raw_material"],
                    "conflict": group["conflict"],
                }
                for group in matching[:6]
            ],
            "parameter_status": "有文献参数，仍需核对适用条件" if matching else "现有知识库证据不足，不填入数值",
            "key_control": "不得跨品种、设备、工艺方法或生产规模直接套用参数；关键偏差须记录并复核。",
            "source_ids": sources,
        })
    evidence_ids = list(dict.fromkeys(str(item.get("document_id") or item.get("source_file") or item.get("chunk_id") or "") for item in evidence))
    return {
        "product": product,
        "raw_material": intent.get("raw_material"),
        "scale": intent.get("scale") or "unknown",
        "flow": flow,
        "rows": rows,
        "evidence_ids": evidence_ids,
        "parameter_count": sum(len(row["parameters"]) for row in rows),
        "unresolved_steps": [row["step"] for row in rows if not row["parameters"]],
        "equipment": EQUIPMENT_MAP.get(product, []),
        "quality_checks": QUALITY_CHECKS.get(product, ["感官", "理化指标", "微生物", "食品安全项目", "包装和储藏稳定性"]),
        "byproduct_guidance": (
            "果肉可另行评估果汁或发酵利用；籽、残余果皮和清洗废水分流记录，未经安全评价不得直接进入食品链。"
            if product == "陈皮"
            else "果皮、籽和果渣应分流称量，可另行检索精油、果胶、膳食纤维或饲料/堆肥路线；不合格霉变原料不得混入副产物食品路线。"
        ),
    }


def format_processing_context(
    intent: dict[str, Any],
    parameter_groups: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    """Token-bounded, source-preserving context for the existing answer model."""
    lines: list[str] = []
    used_tokens = 0

    def add(line: str, *, required: bool = False) -> bool:
        nonlocal used_tokens
        estimated = max(1, (len(line) + 2) // 3)
        if not required and used_tokens + estimated > PROCESS_CONTEXT_TOKEN_LIMIT:
            return False
        lines.append(line)
        used_tokens += estimated
        return True

    add("【加工意图】", required=True)
    add(
        f"原料：{intent.get('raw_material') or '待确认'}；目标产品：{intent.get('primary_product') or '待确认'}；规模：{intent.get('scale') or 'unknown'}；现有设备：{'、'.join(intent.get('equipment') or []) or '未提供'}",
        required=True,
    )
    add("【结构化参数证据】", required=True)
    for index, group in enumerate(parameter_groups[:PROCESS_CONTEXT_PARAMETER_LIMIT], 1):
        source_text = "、".join(group.get("source_ids") or []) or "无"
        if not add(
            f"[参数{index}] {group.get('process_step')}/{group.get('parameter_name')}：{group.get('recommended_range')}；"
            f"{group.get('confidence_level')}；{group.get('applicability')}；证据ID：{source_text}；"
            f"证据性质：{group.get('basis_type')}；冲突：{'是' if group.get('conflict') else '否'}"
        ):
            break
    if not parameter_groups:
        add("未提取到含完整单位、条件和来源的可靠工艺参数；不得自行补数值。", required=True)
    add("【参数证据片段】")
    for index, item in enumerate(evidence[:PROCESS_CONTEXT_EVIDENCE_LIMIT], 1):
        source_id = str(item.get("document_id") or item.get("source_file") or item.get("chunk_id") or "")
        location = _source_location(item)
        excerpt = re.sub(r"\s+", " ", str(item.get("chunk_text") or "")).strip()[:560]
        if not add(f"[加工文献{index}] ID={source_id}；{item.get('title') or '未命名'}；{item.get('year') or '年份未知'}；{location}；片段：{excerpt}"):
            break
    return "\n".join(lines)
