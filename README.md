# 柑橘产业链智能决策 Agent Demo

这是一个面向柑橘批次加工决策的 Streamlit Agent Demo。当前版本已经从“表单分析 + 大模型问答”重构为统一的对话式 Agent 工作台，并进一步整理为受控 Agent 架构：Planning、Tools、Memory 和固定质控护栏都在后端显式执行。用户在聊天框输入批次信息后，Agent 自动抽取字段、调用本地文献库、运行规则评分、检查质控风险，并在同一轮对话里输出结论、工具过程、文献证据和 Markdown 报告。

当前 Demo 不替代实验室检测、食品安全放行、标签审核、报价审批和人工复核。它的定位是帮助业务和质控人员形成可追溯、可复核的加工决策草稿。

## 当前 Agent 流程

```text
用户聊天输入 / 上传图片 / 补充外观描述
  -> Agent 判断是否需要调用工具
  -> 从文本中抽取批次字段
  -> 如有图片，调用 Qwen 视觉模型生成结构化外观描述
  -> 受控 Planning 生成必需执行步骤
  -> Memory 读取当前任务上下文和本地长期知识状态
  -> 调用本地文献混合 RAG 检索
  -> 调用规则引擎进行加工路线评分
  -> 调用质控规则检查风险边界
  -> 生成 Markdown 决策报告
  -> 固定质控护栏检查必需工具、检测缺失和合规边界
  -> 可选调用 DeepSeek 生成对话式总结
  -> 在同一对话中展示结论、证据、工具轨迹和报告
```

示例输入：

```text
我有一批新会茶枝柑，糖度10.5，水分18%，客户是茶饮品牌，帮我按整果、果肉、果皮、种子和副产物拆开判断加工方向并出报告。
```

## 快速启动

```powershell
.\启动Demo.ps1
```

启动后打开：

```text
http://localhost:8501
```

也可以在已安装依赖的环境中手动启动：

```powershell
.\.venv\Scripts\streamlit.exe run app\main.py
```

## 模型配置

DeepSeek 用于普通对话和工具调用后的自然语言总结；Qwen 视觉模型用于上传图片后的外观识别。API Key 不在网页上输入，而是从本地配置文件读取：

```python
# agent/llm_config.py
DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
VISION_API_KEY = "你的 Qwen 视觉模型 API Key"
VISION_MODEL = "qwen-vl-max"
VISION_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
```

`VISION_MODEL` 必须填写支持 `image_url` 输入的视觉语言模型。如果你已经部署了自己的 OpenAI-compatible 视觉接口，请把 `VISION_API_URL` 和 `VISION_MODEL` 改成部署接口对应的值；同名环境变量会优先于 `agent/llm_config.py`。

当前文本模型固定为：

```text
deepseek-v4-pro
```

如果没有填写 DeepSeek API Key，本地文献检索、规则评分、风险检查和报告生成仍可运行，但不能生成 DeepSeek 总结或普通大模型问答。如果没有填写视觉模型 API Key，上传图片将无法自动识别，只能使用人工外观描述。

注意：如果项目会上传到 GitHub 或发给别人，不要提交真实 API Key。

## 页面使用方式

- 底部聊天框是主入口，直接输入批次信息或追问。
- 侧边栏支持 JPG、PNG、WebP、BMP、GIF、TIFF、HEIC/HEIF、AVIF、JPEG 2000、ICO 等常见图片格式；服务端会校验并转换为模型兼容的 JPEG，再调用 Qwen 视觉模型生成结构化外观描述。“外观描述”仍可作为人工补充。
- 当输入包含“分析、加工、报告、批次、陈皮、柑橘、果肉、果皮、果胶、精油、糖度、水分、农残”等意图词时，Agent 会自动调用工具链。
- 工具调用结果会在同一轮对话里展示，可展开查看：
  - 工具调用过程
  - 加工评分与质控风险
  - 文献证据
  - 报告草稿
- 生成的报告会保存到 `outputs/reports/`，审计摘要会写入 `logs/audit.jsonl`。

## 目录结构

```text
柑橘Agent/
  app/
    main.py                         # Streamlit 统一 Agent 工作台入口

  agent/
    orchestrator.py                 # 对话入口与工具调用编排
    workflow.py                     # 受控 Agent 主工作流
    planner.py                      # Planning：生成固定必需执行计划
    tools.py                        # Tools：统一包装检索、评分、质控和报告工具
    memory.py                       # Memory：短期任务上下文和本地长期知识状态
    guardrails.py                   # 固定质控护栏和必需工具校验
    llm_client.py                   # DeepSeek 调用、提示词和上下文拼接
    llm_config.py                   # 本地 DeepSeek API Key 配置
    rag.py                          # 本地文献混合 RAG 检索
    rules.py                        # 加工评分与质控风险规则
    report.py                       # 报告生成与合规词检查
    langchain_agent.py              # 预留/实验性入口

  scripts/
    build_literature_chunks.py      # 文献库构建脚本

  文献库/                            # 原始 JSON/PDF 文献

  data/
    cases/                          # 历史演示案例，可作为后续结构化样例
    clean_chunks/                   # 兜底示例知识片段
    literature/
      chunks.jsonl                  # Agent 实际检索的文献切片
      converted_json/               # PDF 抽取后的 JSON 文本
      manifest.json                 # 文献库构建清单

  logs/                             # 审计日志
  outputs/                          # 生成报告
  requirements.txt
  启动Demo.ps1
```

## 文献库构建

把陈皮/柑橘加工相关 `.json` 和 `.pdf` 放入 `文献库/` 后运行：

```powershell
.\.venv\Scripts\python.exe scripts\build_literature_chunks.py
```

构建脚本会：

- 读取 `文献库/*.json`，抽取标题、摘要、DOI、年份、期刊和全文字段。
- 读取 `文献库/*.pdf`，用 `pypdf` 抽取每页文本。
- 过滤明显的参考文献列表等噪声段落。
- 生成统一文献切片到 `data/literature/chunks.jsonl`。
- 将 PDF 抽取结果保存到 `data/literature/converted_json/`。
- 将构建统计和错误信息写入 `data/literature/manifest.json`。

当前检索已经升级为本地混合 RAG，不需要额外下载 embedding 模型或启动向量数据库。`agent/rag.py` 会在同一份 `chunks.jsonl` 上同时计算三类信号：

- 关键词匹配：保留标题、主题、关键词、正文、DOI 和来源字段的词面命中，适合 DOI、品种名、工艺名和专有术语。
- 语义相关性：用中英文术语桥接、英文词/短语、中文字符 n-gram 和 TF-IDF 余弦相似度做轻量向量检索。例如“陈皮、茶枝柑、果皮、果胶、黄酮、精油、质控”会关联到 `chenpi`、`chachi`、`citrus peel`、`pectin`、`flavonoid`、`essential oil`、`quality` 等英文文献表达。
- 元数据加权：结合 `product`、标题、DOI、人工抽取来源等字段，优先返回与当前批次部位和产品方向更匹配的证据。

默认入口是 `hybrid_search_knowledge()`，返回字段会附带 `keyword_score`、`vector_score`、`metadata_score`、`match_score` 和 `retrieval_method`，上层报告仍使用原来的文献证据结构。后续如果需要更强语义能力，可以在同一份 `chunks.jsonl` 基础上替换为 FAISS、Chroma、Qdrant 或 embedding API，并保留现有返回字段。

## 主要开发入口

- `app/main.py`：调整统一对话式工作台、消息展示、图片上传和结果展开区。
- `agent/orchestrator.py`：调整用户意图判断、批次字段抽取、工具调用顺序和同一轮对话输出。
- `agent/workflow.py`：调整受控 Agent 主流程、工具轨迹和下一步动作。
- `agent/planner.py`：调整 Planning 步骤、必需工具顺序和任务拆解。
- `agent/tools.py`：维护工具注册和工具包装函数。
- `agent/memory.py`：维护短期任务上下文和本地长期知识状态。
- `agent/guardrails.py`：维护固定质控护栏、必需工具校验和风险边界。
- `agent/llm_client.py`：调整 DeepSeek 调用、系统提示词、上下文拼接和模型参数。
- `agent/llm_config.py`：配置本地 DeepSeek API Key。
- `agent/rag.py`：调整文献混合检索逻辑、关键词扩展、语义相关性和排序规则。
- `agent/rules.py`：把加工经验写成加分、扣分和风险提示。
- `agent/report.py`：调整报告章节、文献引用、销售话术和合规提示。
- `scripts/build_literature_chunks.py`：维护 JSON/PDF 文献转切片流程。

## 当前边界

- 已接入 Qwen 视觉模型做外观初筛，但图片识别只用于可见外观描述，不能替代检测报告和人工质控复核。
- DeepSeek 负责自然语言理解和总结，不替代规则评分、检测报告或人工审批。
- 文献依据来自本地文献切片，正式使用前应人工复核原文、页码、实验条件和适用边界。
- 农残、重金属、微生物、黄曲霉毒素等食品安全结论必须来自真实检测报告。
- 食品安全放行、标签标识、对外宣传、报价和客户承诺仍需企业质控、法规、法务或业务负责人确认。
- 暂不接 ERP、MES、WMS、CRM 等企业系统。

## 后续可扩展方向

- 优化视觉模型提示词和结构化字段，增加多角度图片与缺陷区域标注。
- 用 DeepSeek 或其他模型做更强的批次字段抽取和缺失字段追问。
- 将当前轻量语义检索替换或增强为 embedding + FAISS/Chroma/Qdrant，并增加 rerank。
- 增加企业 SOP、检测报告和客户规格书作为工具输入。
- 增加正式的工具调用审计页面和报告版本管理。



