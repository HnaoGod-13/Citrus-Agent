from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PlanStep:
    order: int
    name: str
    tool_key: str
    required: bool
    purpose: str


def build_controlled_plan(batch: dict[str, Any], image_observation: str, product_filter: str) -> list[PlanStep]:
    """Create a deterministic plan so food-safety checks cannot be skipped."""
    batch_id = batch.get("batch_id") or "当前批次"
    observation_note = "包含外观输入" if image_observation else "未提供外观输入"
    return [
        PlanStep(1, "识别业务场景", "product_classifier", True, f"确认 {batch_id} 的产品范围和检索过滤条件。"),
        PlanStep(2, "读取受控记忆", "memory", True, f"加载当前任务上下文和本地知识库状态；{observation_note}。"),
        PlanStep(3, "识别加工意图", "processing_intent_analyzer", True, "识别目标产品、规模、设备、质量目标并拆分工艺子问题。"),
        PlanStep(4, "检索知识依据", "literature_retriever", True, f"围绕 {product_filter} 场景执行关键词与语义混合检索。"),
        PlanStep(5, "提取加工参数", "processing_evidence_aggregator", True, "优先方法和结果片段，保留单位、条件、规模和来源并交叉验证。"),
        PlanStep(6, "评估加工路线", "rule_scoring_engine", True, "综合批次规则、直接相关文献和数据置信度进行分级排序。"),
        PlanStep(7, "检查质控风险", "quality_gate", True, "强制检查检测缺失、霉变、仓储和食品安全边界。"),
        PlanStep(8, "生成报告", "report_writer", True, "生成参数化可复核报告并执行合规词扫描。"),
        PlanStep(9, "执行固定护栏", "guardrails", True, "确认必需工具均已执行，且输出不越过人工复核边界。"),
    ]


def serialize_plan(plan: list[PlanStep]) -> list[dict[str, Any]]:
    return [asdict(step) for step in plan]
