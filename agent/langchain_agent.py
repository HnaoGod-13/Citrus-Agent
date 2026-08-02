from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.agents import AgentType, Tool, initialize_agent
from langchain.docstore.document import Document
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
from langchain.vectorstores import Chroma

from .rag import load_chunks
from .report import check_compliance, generate_report
from .rules import check_quality_risks, score_processing_options

ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = ROOT / "data" / "chroma_store"


def build_vector_store(chunk_path: Path | None = None, persist_directory: Path | None = None) -> Chroma:
    """Create or load a Chroma vector store from local literature chunks."""
    chunk_path = chunk_path or ROOT / "data" / "literature" / "chunks.jsonl"
    persist_directory = persist_directory or CHROMA_DIR
    persist_directory.mkdir(parents=True, exist_ok=True)

    embeddings = OpenAIEmbeddings()
    docs: list[Document] = []

    if not chunk_path.exists():
        raise FileNotFoundError(f"Chunk file not found: {chunk_path}")

    with chunk_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            docs.append(
                Document(
                    page_content=str(chunk.get("chunk_text", "")),
                    metadata={
                        "title": chunk.get("title"),
                        "topic": chunk.get("topic"),
                        "source": chunk.get("source"),
                        "doi": chunk.get("doi"),
                        "year": chunk.get("year"),
                        "product": chunk.get("product"),
                    },
                )
            )

    return Chroma.from_documents(documents=docs, embedding=embeddings, persist_directory=str(persist_directory))


def load_vector_store(persist_directory: Path | None = None) -> Chroma:
    persist_directory = persist_directory or CHROMA_DIR
    embeddings = OpenAIEmbeddings()
    return Chroma(persist_directory=str(persist_directory), embedding_function=embeddings)


def search_knowledge_rag(query: str, product_filter: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    """Search local literature chunks using embedding similarity."""
    retriever = load_vector_store().as_retriever(search_kwargs={"k": top_k})
    docs = retriever.get_relevant_documents(query)
    results: list[dict[str, Any]] = []
    for doc in docs:
        metadata = {**(doc.metadata or {})}
        results.append(
            {
                "chunk_text": doc.page_content,
                "title": metadata.get("title"),
                "topic": metadata.get("topic"),
                "source": metadata.get("source"),
                "doi": metadata.get("doi"),
                "year": metadata.get("year"),
                "product": metadata.get("product"),
            }
        )
    return results


def tool_search_knowledge(query: str, product_filter: str = "不限") -> str:
    evidence = search_knowledge_rag(query=query, product_filter=product_filter, top_k=5)
    if not evidence:
        return "未检索到相关文献片段。"
    lines = []
    for idx, item in enumerate(evidence, 1):
        lines.append(
            f"{idx}. {item.get('title')} ({item.get('year')}，{item.get('source')})：{item.get('chunk_text')[:200]}"
        )
    return "\n".join(lines)


def tool_score_processing_options(batch_json: str, image_observation: str) -> str:
    batch = json.loads(batch_json)
    scores = score_processing_options(batch, image_observation)
    lines = [
        f"{item.direction}：{item.match_level}；文献支持：{item.evidence_support}；"
        f"数据置信度：{item.data_confidence}；原因：{'；'.join(item.reasons)}。"
        f"风险：{'；'.join(item.risk_notes) or '无'}"
        for item in scores
    ]
    return "\n".join(lines)


def tool_check_quality_risks(batch_json: str, image_observation: str) -> str:
    batch = json.loads(batch_json)
    risks = check_quality_risks(batch, image_observation)
    if not risks:
        return "未发现高风险项。"
    return "\n".join([f"[{risk.level}] {risk.item}：{risk.suggestion}" for risk in risks])


def tool_generate_report(batch_json: str, image_observation: str, evidence_json: str, scores_json: str, risks_json: str) -> str:
    batch = json.loads(batch_json)
    evidence = json.loads(evidence_json)
    scores = [type("ScoreResult", (), item) for item in json.loads(scores_json)]
    risks = [type("QualityRisk", (), item) for item in json.loads(risks_json)]
    return generate_report(batch, image_observation, evidence, scores, risks)


def tool_check_compliance(text: str) -> str:
    issues = check_compliance(text)
    if not issues:
        return "未发现合规问题。"
    return "\n".join(issues)


AGENT_PROMPT = PromptTemplate(
    input_variables=["batch_info", "observation", "tool_descriptions"],
    template=(
        "你是一个柑橘加工决策 Agent。\n"
        "批次信息：{batch_info}\n"
        "外观描述：{observation}\n"
        "请使用可用工具检索文献、评估加工方向、检查质控风险，并给出最合适的推荐。\n"
        "如果需要，调用工具。\n"
        "工具说明：{tool_descriptions}\n"
        "最终输出要包含：推荐方向、关键理由、质控风险和下一步建议。"
    ),
)


def run_langchain_agent(batch: dict[str, Any], image_observation: str) -> str:
    """Run a LangChain Agent with tool-enabled retrieval and decision support."""
    tools = [
        Tool(
            name="search_knowledge",
            func=tool_search_knowledge,
            description="检索本地文献知识库，返回相关文献片段和匹配出处。输入格式：query|product_filter。",
        ),
        Tool(
            name="score_processing_options",
            func=tool_score_processing_options,
            description="基于批次数据、文献适用性和数据置信度，按整果、果肉、果皮、种子和副产物分级多个加工方向。输入格式：batch_json|image_observation。",
        ),
        Tool(
            name="check_quality_risks",
            func=tool_check_quality_risks,
            description="检查关键检测和外观风险。输入格式：batch_json|image_observation。",
        ),
        Tool(
            name="generate_report",
            func=tool_generate_report,
            description="生成完整 Markdown 报告。输入格式：batch_json|image_observation|evidence_json|scores_json|risks_json。",
        ),
    ]

    llm = OpenAI(temperature=0)
    batch_info = json.dumps(batch, ensure_ascii=False, indent=2)
    tool_descriptions = "\n".join([f"{tool.name}: {tool.description}" for tool in tools])
    prompt = AGENT_PROMPT.format(
        batch_info=batch_info,
        observation=image_observation or "无",
        tool_descriptions=tool_descriptions,
    )

    agent = initialize_agent(tools, llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, verbose=False)
    return agent.run(prompt)
