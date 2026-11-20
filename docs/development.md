# 开发说明

推荐 Python 3.12、Node.js 22。两个后端分别安装依赖，避免 AnalystVerse 的 pandas 3 与
FinPortfolio 的 pandas 2 要求在同一环境中冲突。

## 手动启动

每段在独立终端中从仓库根目录执行：

```powershell
Set-Location analyst/Analyst
.\.venv\Scripts\python.exe -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location analyst/frontend
npm.cmd run dev -- --host 127.0.0.1
```

```powershell
Set-Location System/FinPortfolio_MVP/backend
.\.venv\Scripts\python.exe -m app
```

```powershell
Set-Location System/FinPortfolio_MVP/frontend
npm.cmd run dev -- --host 127.0.0.1
```

## 验证

后端测试见首页。AnalystVerse 前端有额外的 Node.js 测试：

```powershell
Set-Location analyst/frontend
npm.cmd run test:events
npm.cmd run test:config
npm.cmd run test:reflection
npm.cmd run test:crawl
npm.cmd run test:analysis-date
npm.cmd run test:chat
npm.cmd run build
```

FinPortfolio 前端的 `npm.cmd run build` 同时执行 TypeScript 检查与 Vite 构建。
健康检查为两个后端各自的 `/api/health`。

## 配置与提交

`analyst/Analyst/.env.example` 是后端配置模板；
`analyst/frontend/.env.development.example` 是开发前端配置模板。
`.env`、`.env.development`、运行时配置和算法注册状态均不纳入 Git。
新增算法的示例见 `analyst/docs/algorithm-registry.md`，组合插件示例见 `System/FinPortfolio_MVP/plugins/equal_weight`。

保留了两个前端的 `package-lock.json`，使用 `npm ci` 安装。
AnalystVerse 的旧 `uv.lock` 已移除；若采用 uv 管理，需基于当前 `pyproject.toml` 重新锁定。

## Docker

`analyst/Dockerfile` 仅封装 AnalystVerse，不包含 FinPortfolio。
容器中需要将 `FINPORTFOLIO_API_BASE_URL` 指向容器可达的 FinPortfolio 后端，
构建前端时也需配置浏览器可达的 FinPortfolio UI 地址。
仓库首页的快速启动使用本地开发模式，本次未验证完整容器部署。
