from __future__ import annotations

# 云端部署时从环境变量 / Streamlit Secrets 读取真实密钥。
# 不在代码仓库中保存任何 API Key。
DEEPSEEK_API_KEY = ""

# Qwen 视觉模型配置。用于上传柑橘图片后的外观识别。
VISION_API_KEY = ""
VISION_MODEL = "qwen-vl-max"
VISION_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
