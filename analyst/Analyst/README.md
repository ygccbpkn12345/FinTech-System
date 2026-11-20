# AnalystVerse backend

Python 3.12 + FastAPI。启动入口为 `api_server:app`，固定开发端口 `8000`。

完整安装、示例数据和启动步骤见 [仓库首页](../../README.md)。
`requirements.txt` 包含 API、演示分析、数据获取和聊天所需依赖；
真实分析另装 `requirements-model.txt` 并设置 `BACKEND_USE_REAL_MODEL=true` 和模型密钥。
配置模板为本目录 `.env.example`。密钥和运行时配置不纳入版本控制。
