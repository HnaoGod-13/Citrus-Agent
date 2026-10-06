# 报告服务接入

当前项目已经把报告撰写核心封装成独立 HTTP 服务。其他项目只需要把数据库、知识图谱或表单数据整理成统一 JSON，就可以生成同样的正式项目报告、引用清单和可编辑 Word。

迁移时不要只复制本说明文件。真正运行服务需要复制 `app/reporting/` 目录中的 `http_service.py`、`service.py`、`model_client.py`、`web_search.py`、`docx_export.py` 和 `__init__.py`。这些文件已经包含报告生成、联网检索、模型调用和 Word 导出能力；不需要复制当前网站的整个 `agent` 目录。

## 启动服务

在 `streamlit-deploy` 目录执行：

```powershell
$env:DEEPSEEK_API_KEY="你的模型密钥"
$env:REPORT_SERVICE_PORT="8787"
$env:REPORT_SERVICE_API_KEY="给调用方使用的服务密钥"
python -m app.reporting.http_service
```

没有设置 `REPORT_SERVICE_API_KEY` 时服务不校验调用密钥；正式部署时应设置它。`REPORT_SERVICE_OUTPUT_DIR` 可以指定报告文件保存目录，`REPORT_SERVICE_CORS` 可以限制浏览器来源。

## 调用接口

健康检查：

```http
GET /health
```

生成报告：

```http
POST /report/generate
Content-Type: application/json
X-Report-Service-Key: 给调用方使用的服务密钥
```

请求正文示例：

```json
{
  "request_id": "project-2026-001",
  "project": {
    "title": "广西南宁沃柑加工项目",
    "industry": "农产品加工",
    "region": "广西南宁",
    "purpose": "项目申报",
    "agency": "项目申报单位"
  },
  "facts": {
    "origin": "广西南宁武鸣",
    "variety": "沃柑",
    "batch": "B-0903-001",
    "quantity": "20吨",
    "target_product": "NFC果汁"
  },
  "route": {
    "label": "鲜果榨汁路线",
    "alternatives": []
  },
  "process": {
    "stages": ["验收", "分选", "榨汁", "过滤", "灌装", "冷藏"],
    "equipment": ["分选设备", "榨汁设备", "灌装设备"],
    "quality_controls": ["原料验收", "过程卫生控制", "成品检测"]
  },
  "sources": [],
  "report_profile": {
    "template": "项目报告",
    "language": "zh-CN",
    "output_formats": ["markdown", "docx"]
  }
}
```

响应包含 `status`、`report_id`、`markdown`、`sources`、`docx_path` 和 `docx_base64`。其他项目可以把 `markdown` 用于网页报告页，把 `docx_base64` 转成下载文件，并按自己的项目 ID 保存报告和来源。

页面提交按钮只需要调用这个接口，然后把 `markdown` 放入预览区域，把 `docx_base64` 转成下载文件：

```javascript
const response = await fetch(`${REPORT_SERVICE_URL}/report/generate`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Report-Service-Key": REPORT_SERVICE_KEY,
  },
  body: JSON.stringify(formToReportPayload()),
});
const result = await response.json();
if (result.status !== "completed") throw new Error(result.message || "报告生成失败");
reportPreview.innerHTML = renderMarkdown(result.markdown);
const wordBytes = Uint8Array.from(atob(result.docx_base64), ch => ch.charCodeAt(0));
downloadWord(new Blob([wordBytes], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
```

## 接入其他项目的方式

其他系统只负责四件事：把自己的字段映射到 `project`、`facts`、`route`、`process` 和 `sources`；在正式提交后调用接口；保存返回的报告和来源；在页面上提供报告预览与 Word 下载。联网检索、模型生成、引用编号、内部表达检查和 Word 格式都由报告服务完成。

知识图谱可以把实体属性和关系结果放进 `facts`、`route`、`process`；数据库系统可以直接用查询结果组装同一个请求；新的网页项目也可以在提交表单后调用同一个接口。这样每个项目保留自己的数据来源和页面，但共用同一套正式报告能力。

Skill 本身是写作和质量规则，供 Codex 或报告服务使用；运行中的其他项目通过报告服务接口接入。这样既能复用同一套报告能力，也不会要求其他项目复制当前网站的页面代码。
