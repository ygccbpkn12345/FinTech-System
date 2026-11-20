# AnalystVerse 更新版单容器部署设计

## 目标

以根目录 `Analyst/` 为唯一后端源码，重新生成一个可同时运行 React 前端、Nginx 和 FastAPI 后端的镜像，并支持新版项目内置的 Baostock/Tushare 数据获取能力。

## 架构

- Node.js 构建阶段生成 Vite 生产静态文件。
- Python 3.12.4 运行阶段安装 Nginx、后端完整依赖、Baostock 和 Tushare。
- Nginx 监听 80 端口并将 `/api/` 代理到单 worker Uvicorn。
- 容器启动不额外生成 result 数据；本地结果生成和在线取数均由新版项目自身实现。
- `docker/Analyst` 是备份目录，通过 `.dockerignore` 排除。

## 数据与配置

- 镜像包含 `Analyst/data`、`Analyst/data_cache` 和 `Analyst/result` 的现有内容。
- 在线取数产生的数据写入项目自己的数据目录，可通过卷持久化。
- Baostock 无需 Token；Tushare Token 通过 `TUSHARE_TOKEN` 环境变量或前端请求配置。
- DeepSeek Key 只通过运行时环境变量传入。

## 验收

- 前端能够以同源 `/api` 完成生产构建。
- 镜像内能够导入 `baostock` 和 `tushare`。
- `GET /api/health` 返回 `status=ok`。
- 页面可通过 `http://localhost` 或 `http://服务器IP` 访问。

