"""Versioned field dictionary shared by the intake UI and server validation.

Required flags are workflow requirements, not universal legal obligations.
No production settings, assay limits or evidence conclusions are prefilled.
"""
from __future__ import annotations


def f(key, label, kind="text", required=False, unit="", options=None, **extra):
    return dict(key=key, label=label, type=kind, required=required, unit=unit,
                **({"options": options} if options else {}), **extra)


def n(key, label, unit="", required=False, minimum=0, maximum=None):
    return f(key, label, "number", required, unit, min=minimum,
             **({"max": maximum} if maximum is not None else {}))


def choice(key, label, options, required=False):
    return f(key, label, "select", required, options=options.split("|"))


def group(key, title, fields, hint="", repeat=False, required=False, declaration=False):
    return dict(key=key, title=title, fields=fields, hint=hint, repeat=repeat,
                required=required, declaration=declaration)


COMMON = [
    f("organization", "企业 / 合作社 / 农场名称", required=True),
    choice("entityType", "主体类型", "企业|合作社|家庭农场|个体种植户|科研 / 事业单位|其他", True),
    f("creditCode", "统一社会信用代码（适用时）"), f("address", "联系地址", required=True),
    f("contact", "业务联系人", required=True), f("phone", "联系电话", "tel"),
    f("recorder", "填报人", required=True), f("recordDate", "记录日期", "date", True),
    f("qualityOwner", "质量负责人"), f("certifications", "认证名称、编号及有效期"),
    f("source", "数据来源 / 原始记录编号", required=True),
]

TEST_FIELDS = [
    f("sample", "样品 / 批次编号", required=True), f("sampleDate", "采样日期", "date"),
    f("date", "检测日期", "date", True), f("item", "检测项目", required=True),
    f("result", "实测结果（保留未检出、＜检出限等表达）", required=True),
    f("unit", "结果单位", required=True), f("method", "检测方法 / 标准编号"),
    f("limit", "适用限值及依据（含产品类别）"), f("lab", "检测机构 / 实验室", required=True),
    f("reportNo", "检测报告编号", required=True), f("evidence", "对应附件名称 / 证据编号"),
    choice("conclusion", "报告记载结论", "合格|不合格|仅报告数值|待复核", True),
    f("reviewer", "企业复核人"),
]

CONSENT = group("consent", "数据使用与补充说明", [
    f("platformUse", "同意平台保存本次记录，用于产业数据整理和后续方案研究", "checkbox", True),
    f("statisticsUse", "允许纳入去标识化汇总统计", "checkbox"),
    f("matchingUse", "允许后续用于供需匹配（商业信息另行授权）", "checkbox"),
    f("reportUse", "允许本次记录用于工作报告", "checkbox"),
    f("notes", "补充说明 / 尚缺资料 / 不适用原因", "textarea"),
], "默认不公开联系人、配方、成本和附件。提交表示数据待复核，不代表已通过质量审核。")

SUPPLIER = [
    dict(title="主体与基地", groups=[group("profile", "主体信息", COMMON), group("base", "种植基地与品种", [
        f("baseName", "基地名称", required=True), f("plot", "地块编号", required=True),
        f("origin", "产地（省 / 市 / 县 / 乡镇）", required=True), f("coordinates", "经纬度"),
        n("altitude", "海拔", "m", minimum=-500), n("area", "种植面积", "亩", True),
        f("variety", "柑橘品种 / 品系", required=True), f("rootstock", "砧木"),
        f("seedlingSource", "苗木来源 / 批次"), n("treeAge", "树龄", "年"),
        n("density", "种植密度", "株/亩"), choice("mode", "种植方式", "常规|绿色生产|有机生产|设施种植|其他"),
        n("annualOutput", "年度产量", "吨"), n("yieldPerMu", "亩产", "kg/亩"),
        n("marketableRate", "商品果率", "%", maximum=100),
    ])]),
    dict(title="土壤与环境", groups=[group("environment", "土壤、灌溉与环境", [
        f("soilType", "土壤类型"), n("ph", "土壤 pH", maximum=14), n("organic", "有机质", "g/kg"),
        f("soilNpk", "土壤氮磷钾检测结果及单位"), f("soilReport", "土壤检测报告编号 / 日期"),
        f("waterSource", "灌溉水源"), f("waterReport", "水质报告编号 / 日期 / 结论"),
        f("irrigation", "灌溉方式"), f("irrigationFrequency", "灌溉频次"), n("waterAmount", "单次用水量", "m³/亩"),
        f("climate", "温度、降雨及观测周期"), f("facilities", "防虫、遮阳、排水和冷库设施"),
        f("weatherEvents", "霜冻、洪涝、高温等影响记录", "textarea"),
    ], "环境数据请注明观测时间和来源；没有实测值时留空。")]),
    dict(title="农业投入品", groups=[group("fertilizers", "肥料与土壤改良剂", [
        f("name", "产品名称 / 品牌", required=True), f("manufacturer", "生产企业"),
        f("supplier", "供应商 / 来源", required=True), f("batch", "产品批次"),
        f("registration", "登记 / 备案编号（适用时）"), f("composition", "N-P-K 配比及其他成分、含量", required=True),
        f("date", "使用日期", "date", True), f("stopDate", "停用日期", "date", True),
        f("stage", "生育阶段"), f("plot", "使用地块", required=True),
        n("quantity", "实际用量", required=True), f("unit", "用量单位（如 kg/亩）", required=True),
        f("dilution", "稀释倍数 / 工作液浓度"), f("method", "使用方法", required=True),
        f("operator", "操作人", required=True), f("evidence", "采购凭证 / 包装附件编号"),
    ], "依据农产品质量安全法第27条设计投入品名称、来源、用法、用量和使用 / 停用日期。", True, declaration=True),
    group("pesticides", "农药与病虫害防治", [
        f("pest", "病虫害 / 防治对象", required=True), f("name", "商品名 / 品牌", required=True),
        f("ingredient", "有效成分及含量", required=True), f("registration", "农药登记证号", required=True),
        f("manufacturer", "生产企业"), f("supplier", "供应商 / 来源", required=True), f("batch", "产品批次"),
        f("date", "使用日期", "date", True), f("stopDate", "停用日期", "date", True),
        f("plot", "施用地块", required=True), n("quantity", "实际用量", required=True),
        f("unit", "用量单位", required=True), f("dilution", "稀释倍数 / 浓度"),
        f("method", "使用方法", required=True), f("operator", "操作人", required=True),
        n("interval", "标签规定安全间隔期", "天"), f("weather", "施用时天气"),
        f("evidence", "标签 / 采购凭证 / 植保记录编号"),
    ], "逐次记录施用；安全间隔期从产品标签或适用规定录入，系统不预设施药剂量。", True, declaration=True)]),
    dict(title="田间与采收", groups=[group("fieldwork", "田间管理明细", [
        f("date", "作业日期", "date", True), f("plot", "地块", required=True),
        choice("operation", "作业环节", "灌溉|修剪|疏花疏果|套袋|除草|病虫害巡查|极端天气处置|其他", True),
        f("method", "作业方法与参数", required=True), n("quantity", "工作量 / 用量"), f("unit", "计量单位"),
        f("operator", "操作人", required=True), f("result", "观察结果 / 异常处置", "textarea"),
    ], repeat=True), group("harvest", "采收与原料批次", [
        f("batch", "原料批次号", required=True), f("date", "采收日期", "date", True),
        f("plots", "关联地块编号", required=True), f("method", "采收方式 / 成熟判断"),
        n("quantity", "本批采收量", required=True), choice("unit", "数量单位", "kg|吨", True),
        n("marketable", "商品果量（与采收量同单位）"), n("loss", "次果 / 损耗量（同单位）"),
        f("operator", "采收负责人", required=True), f("postharvest", "清洗、分选、预冷、保鲜等处理", "textarea"),
        f("treatmentMaterials", "采后处理用料、成分、用量及依据", "textarea"),
    ])]),
    dict(title="原料质量", groups=[group("quality", "原料品质档案", [
        f("grade", "等级 / 外观 / 缺陷比例", required=True), n("brix", "可溶性固形物", "°Brix", maximum=40),
        n("acidity", "可滴定酸", "%", maximum=100), n("ratio", "糖酸比"),
        n("juiceYield", "出汁率", "%", maximum=100), n("fruitWeight", "单果重", "g"),
        n("diameter", "果径", "mm"), n("firmness", "硬度", "N"),
        f("method", "品质测定方法 / 仪器 / 时间"), f("certificate", "承诺达标合格证编号（适用时）"),
        choice("testStatus", "检测资料状态", "已有检测资料|尚未检测|资料待补", True),
    ]), group("tests", "原料检测项目", TEST_FIELDS,
              "逐项录入农残、污染物、微生物及适用质量指标，保留原始检测表达；具体项目按原料用途确定。", True)]),
    dict(title="仓储与供应", groups=[group("storage", "仓储和运输", [
        f("warehouse", "仓库 / 库位"), n("temperature", "储存温度", "°C", minimum=-80),
        n("humidity", "相对湿度", "%", maximum=100), f("entryDate", "入库日期", "date"),
        f("packaging", "包装方式 / 规格"), f("transport", "运输方式 / 车辆编号"),
        n("transportTemperature", "运输温度", "°C", minimum=-80), n("duration", "运输时长", "小时"),
    ]), group("supply", "供应能力与商业条件", [
        n("available", "可供数量"), choice("unit", "数量单位", "kg|吨"),
        f("from", "供应开始日期", "date"), f("until", "供应结束日期", "date"),
        f("region", "可配送地区"), f("targetBuyer", "期望购买方 / 用途"),
        n("minimumOrder", "起订量（与可供数量同单位）"), f("price", "报价与口径（选填）"),
        f("conditions", "寄样、运输、验收及结算条件", "textarea"),
    ])]),
    dict(title="证据与提交", groups=[CONSENT]),
]

PROCESSOR = [
    dict(title="企业与产品", groups=[group("profile", "主体信息", COMMON + [
        f("license", "食品生产许可证编号 / 许可范围（适用时）"),
        f("licenseReason", "无需生产许可的业务情形说明（适用时）"),
        f("systems", "质量管理体系 / 认证"), n("capacity", "产能", "吨/日"),
    ]), group("product", "产品与生产任务", [
        f("name", "目标产品名称", required=True),
        choice("category", "产品类别", "NFC 果汁|浓缩汁|果干 / 果脯|果皮 / 陈皮制品|果胶|精油|其他", True),
        f("batch", "生产 / 成品批次号", required=True), f("date", "生产日期", "date", True),
        f("standard", "产品执行标准及版本", required=True), f("specification", "产品规格 / 质量目标", "textarea", True),
        n("planned", "计划产量", required=True), choice("unit", "产量单位", "kg|吨|L|件", True),
        f("shelfLife", "保质期"), f("storage", "贮存条件"), f("packaging", "包装规格 / 标签版本"),
        f("formula", "配方编号 / 版本"), f("customer", "目标客户 / 用途（选填）"),
    ])]),
    dict(title="原料接收", groups=[group("materials", "原料批次与进货查验", [
        f("batch", "供应端原料批次号", required=True), f("name", "原料品种 / 名称", required=True),
        f("origin", "产地", required=True), f("supplier", "供货者名称", required=True),
        f("address", "供货者地址"), f("phone", "供货者联系方式", "tel"),
        f("specification", "规格 / 品质等级", required=True), f("harvestDate", "采收 / 原料生产日期", "date"),
        f("shelfLife", "原料保质期 / 保存要求"), f("arrival", "进货日期", "date", True),
        n("quantity", "到货数量", required=True), choice("unit", "数量单位", "kg|吨", True),
        n("brix", "到货糖度", "°Brix", maximum=40), n("acidity", "到货酸度", "%", maximum=100),
        n("temperature", "到货温度", "°C", minimum=-80),
        f("evidence", "许可证 / 合格证明 / 检测报告编号", required=True),
        choice("acceptance", "进货查验结果", "接收|待验|拒收|让步接收（注明依据）", True),
        f("reason", "验收 / 让步接收依据"), f("receiver", "验收人", required=True),
        n("input", "实际投料量（与到货数量同单位）"),
    ], "同一成品可以关联多个供应批次；一条记录对应一个原料批次。食品安全法第50条涉及进货查验与凭证。", True, True)]),
    dict(title="辅料与包材", groups=[group("ingredients", "辅料、添加剂和加工助剂", [
        choice("type", "物料类型", "辅料|食品添加剂|加工助剂", True), f("name", "名称 / 成分", required=True),
        f("supplier", "供应商", required=True), f("batch", "物料批次", required=True),
        f("purpose", "使用目的"), n("quantity", "实际使用量", required=True), f("unit", "计量单位", required=True),
        n("ratio", "配方比例", "%", maximum=100), f("basis", "适用食品类别 / 用量依据"),
        f("arrival", "进货日期", "date"), f("expiry", "有效期至", "date"),
        f("evidence", "供应商资质 / 合格证明编号"), f("operator", "投料 / 复核人员"),
    ], "按产品适用类别核对添加剂使用范围及限量，不预填通用添加剂限值。", True, declaration=True),
    group("packaging", "食品接触包装材料", [
        f("name", "包材名称 / 规格", required=True), f("supplier", "供应商", required=True),
        f("batch", "包材批次", required=True), n("quantity", "使用数量", required=True),
        f("unit", "单位", required=True), f("evidence", "食品接触合规 / 合格证明编号"),
        f("arrival", "进货日期", "date"), f("inspection", "验收结果 / 验收人"),
    ], repeat=True)]),
    dict(title="工序与参数", groups=[group("process", "产线与工艺版本", [
        f("line", "产线名称 / 编号", required=True), f("sop", "SOP 编号 / 版本", required=True),
        f("approver", "SOP 批准人 / 生效日期"), f("operator", "生产负责人", required=True),
        f("start", "开始时间", "datetime-local"), f("end", "结束时间", "datetime-local"),
    ]), group("steps", "实际加工工序", [
        f("name", "工序名称", required=True), f("equipment", "设备名称 / 编号", required=True),
        f("start", "开始时间", "datetime-local", True), f("end", "结束时间", "datetime-local", True),
        f("sop", "工序 SOP / 记录编号"), n("input", "本工序投入量"), f("inputUnit", "投入单位"),
        n("output", "本工序产出量"), f("outputUnit", "产出单位"),
        f("operator", "操作人", required=True), f("reviewer", "复核人"),
        choice("ccp", "控制点类型", "一般工序|关键控制点|操作性前提方案"),
        f("deviation", "偏差与纠正措施", "textarea"),
    ], "工序可按实际流程新增；下方参数明细通过工序名称关联，支持一工序多参数。", True, True),
    group("parameters", "工艺参数实测明细", [
        f("step", "对应工序名称", required=True), f("name", "参数名称", required=True),
        f("target", "目标值 / 控制范围", required=True), f("actual", "实测值 / 记录摘要", required=True),
        f("unit", "单位", required=True), f("time", "测量时间 / 采样频率"),
        f("method", "测量方法 / 仪器"), f("basis", "参数依据 / SOP 位置", required=True),
        f("operator", "记录人"), f("evidence", "曲线 / 仪表记录附件编号"),
    ], "可记录温度、持续时间、压力、流量、转速、pH、糖度、筛孔、干燥水分等；保留目标和实测值的区别。", True, True)]),
    dict(title="卫生与质检", groups=[group("hygiene", "卫生、清洗与设备校准", [
        f("water", "生产用水来源 / 检测报告"), f("environment", "车间温湿度 / 环境监测记录"),
        f("personnel", "人员健康与培训记录编号"), f("foreignBody", "虫害 / 异物 / 金属检测记录"),
    ]), group("cleaning", "清洗、消毒和校准记录", [
        f("date", "记录日期", "date", True), f("equipment", "设备 / 区域 / 仪器", required=True),
        choice("type", "记录类型", "CIP 清洗|清洗消毒|仪器校准|环境检查|其他", True),
        f("agent", "用料名称 / 成分"), f("concentration", "用量 / 浓度及单位"),
        n("temperature", "温度", "°C", minimum=-80), n("duration", "持续时间", "min"),
        f("result", "验证结果", required=True), f("operator", "负责人", required=True),
        f("evidence", "记录 / 证书编号"),
    ], repeat=True), group("tests", "成品质检项目", TEST_FIELDS,
             "按产品录入感官、理化、微生物、污染物、包装密封等适用项目。数值以检测报告为准。", True, True),
    group("release", "成品检验与放行记录", [
        f("reportNo", "成品检验报告 / 合格证号", required=True),
        choice("conclusion", "企业质量部门结论", "待检|合格|不合格|待复核", True),
        f("date", "判定日期", "date"), f("reviewer", "质量负责人"),
        f("label", "标签及包装检查结果"), f("handling", "不合格 / 留样 / 复检处置", "textarea"),
    ])]),
    dict(title="产出与追溯", groups=[group("output", "产量、损耗与资源消耗", [
        n("rawMass", "原料总投入", "kg"), n("productMass", "成品净产量", "kg"),
        n("peel", "果皮产出", "kg"), n("pomace", "果渣产出", "kg"), n("loss", "损耗", "kg"),
        n("water", "用水量", "m³"), n("power", "用电量", "kWh"), n("steam", "蒸汽用量", "kg"),
        n("wastewater", "废水量", "m³"), n("hours", "设备运行时长", "小时"),
        f("byproduct", "副产品去向 / 废弃物处理"), f("cost", "成本及统计口径（选填）"),
    ], "得率只在原料总投入与成品净产量均有有效 kg 数值时计算。"),
    group("shipments", "成品出库与销售追溯", [
        f("batch", "成品批次号", required=True), f("date", "出库 / 销售日期", "date", True),
        n("quantity", "数量", required=True), f("unit", "单位 / 规格", required=True),
        f("customer", "购货者名称", required=True), f("address", "购货者地址"), f("phone", "购货者联系方式", "tel"),
        f("warehouse", "仓库 / 库位"), f("transport", "运输条件 / 承运记录"),
        f("certificate", "出厂合格证明编号"), f("complaint", "投诉 / 召回 / 处理记录", "textarea"),
    ], "按食品安全法第51条保留出厂检验、销售及购货者记录。尚未出库可不添加。", True)]),
    dict(title="证据与提交", groups=[CONSENT]),
]

STANDARDS = [
    dict(title="农产品质量安全法 · 第27、29、39条", scope="供应端", version="2022年修订，2023年施行",
         note="涉及适用主体的投入品与生产记录、质量检测、承诺达标合格证；生产记录至少保存二年。",
         url="https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_f5a0c2c6c3724a6aad91645043b012ce.html"),
    dict(title="食品安全法 · 第46、50—52条", scope="生产端", version="2025年修正",
         note="用于原料查验、生产控制、出厂检验和销售追溯字段设计。记录保存期限按产品与适用条款确定。",
         url="https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=104105"),
    dict(title="GB 14881—2025 食品生产通用卫生规范", scope="生产端", version="2026-09-02实施",
         note="生产卫生、设施设备、过程控制与记录。已更新原页面的2013版入口。",
         url="https://www.nhc.gov.cn/sps/c100088/202509/5dc5e1e2b26d4d27a7913b9e71bbe931.shtml"),
    dict(title="GB 2760—2024 食品添加剂使用标准", scope="生产端", version="按适用食品类别核对",
         note="记录添加剂名称、用途、用量、批次及适用依据。",
         url="https://www.nhc.gov.cn/sps/c100088/202403/bda120e678df4a49a8beb90852559d7c.shtml"),
    dict(title="GB 2762—2025 食品中污染物限量", scope="两端", version="2026-09-02实施",
         note="按产品类别确定适用项目与限值，检测结果保留单位、方法和报告来源。",
         url="https://www.nhc.gov.cn/sps/c100088/202509/5dc5e1e2b26d4d27a7913b9e71bbe931.shtml"),
    dict(title="GB 2763—2026 食品中农药最大残留限量", scope="两端", version="2026-03-01实施",
         note="已替代GB 2763—2021及GB 2763.1—2022；按柑橘类别、具体农药核对检测依据。",
         url="https://www.nhc.gov.cn/sps/c100088/202602/c0c4a9266f7e43cda1bf3bec59fc2786.shtml"),
]


def intake_schema():
    return dict(version=1, reviewed="2026-09-07", sides={
        "supplier": dict(title="供应端信息收集", subtitle="从种植投入到采收品质，记录每一批柑橘的来源", steps=SUPPLIER),
        "processor": dict(title="生产端信息收集", subtitle="从原料接收到成品质检，记录每一批产品的加工过程", steps=PROCESSOR),
    }, standards=STANDARDS)
