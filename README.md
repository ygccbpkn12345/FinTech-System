# 智慧金融系统 · FinTech-System

将 **AnalystVerse 智能股票分析** 与 **FinPortfolio 投资组合实验平台** 整理到同一仓库，
覆盖 AI 聊天、多分析师决策、算法管理、模型训练、数据集管理及策略回测。
两套应用分别启动，通过 HTTP API 联动；当前未合并为单个后端或统一登录系统。

## 功能与技术栈

| 模块 | 功能 | 技术 |
|---|---|---|
| AnalystVerse | 聊天、股票分析、分析历史、反思、算法管理、系统配置 | React 19、Ant Design、ECharts、FastAPI、LangChain、LangGraph |
| FinPortfolio | 概览、算法中心、训练中心、股票筛选、组合配置、回测、对比、数据集、实验 | React 18、TypeScript、Recharts、FastAPI |
| 算法插件 | ASACPL、HMMP、Equal Weight、单股买入方式 | 独立插件声明、适配器、子进程执行 |

智能分析包含市场、新闻、基本面、行业、动量五类分析，再经过综合决策、风控和最终决策。
买入类报告可联动 FinPortfolio，对比“一次买入”和“分两批买入”的历史表现。

## 目录

| 路径 | 内容 |
|---|---|
| `analyst/Analyst/` | 智能分析 FastAPI 后端、分析师工作流、工具和测试 |
| `analyst/frontend/` | 智能分析 React 前端 |
| `analyst/docker/`、`analyst/Dockerfile` | 原有 AnalystVerse 容器部署文件 |
| `System/FinPortfolio_MVP/` | 组合实验平台前后端、插件和数据登记脚本 |
| `System/ASACPL/`、`System/HMMP/` | 研究算法源码；ASACPL notebook 已清除执行输出 |
| `examples/` | 000063 的小型历史行情与分析示例资料 |
| `scripts/` | Windows 安装、服务启动及示例数据准备 |
| `docs/` | 架构、数据和开发说明 |

## 固定开发端口

| 服务 | 地址 |
|---|---|
| AnalystVerse 前端 | http://127.0.0.1:5173 |
| AnalystVerse 后端 / API 文档 | http://127.0.0.1:8000/docs |
| FinPortfolio 前端 | http://127.0.0.1:5174 |
| FinPortfolio 后端 / API 文档 | http://127.0.0.1:8001/docs |

前端均启用严格端口检查，端口被占用时会报错，避免自动切换后造成联动地址不一致。

## Windows 快速开始

准备 **Python 3.12**、**Node.js 22 / npm** 和 Git。以下命令从仓库根目录执行：

```powershell
git clone https://github.com/ygccbpkn12345/FinTech-System.git
Set-Location FinTech-System
.\scripts\setup.ps1
```

安装脚本使用 `py -3.12` 创建两个独立 Python 虚拟环境，安装后端依赖与两个前端的锁定依赖，
复制配置模板，并准备示例数据。也可指定解释器：

```powershell
.\scripts\setup.ps1 -Python 'C:\Python312\python.exe'
```

在四个 PowerShell 终端中，从仓库根目录分别执行一条：

```powershell
.\scripts\start.ps1 -Service portfolio-backend
.\scripts\start.ps1 -Service portfolio-frontend
.\scripts\start.ps1 -Service analyst-backend
.\scripts\start.ps1 -Service analyst-frontend
```

每个服务在当前终端前台运行，按 `Ctrl+C` 停止。打开 http://127.0.0.1:5173 进入智能分析。
也可以按组件目录手动运行；入口见 [开发说明](docs/development.md)。

### 演示模式与真实模型

默认 `BACKEND_USE_REAL_MODEL=false`：分析流水线使用演示输出，回测仍读取已登记的历史行情。
演示信号、真实行情回测与论文结果应分别理解，不能将演示报告当作实时投资信号。
普通聊天需要可用的模型配置，或遵循现有聊天路由的降级处理。

真实分析需在 `analyst/Analyst/.env` 设置：

```dotenv
BACKEND_USE_REAL_MODEL=true
DEEPSEEK_API_KEY=填写你自己的密钥
CONFIG_ENCRYPTION_KEY=填写你自己的随机私有值
```

然后安装真实工作流所需的 PyTorch：

```powershell
.\analyst\Analyst\.venv\Scripts\python.exe -m pip install -r .\analyst\Analyst\requirements-model.txt
```

真实分析还依赖所选股票的行情、新闻、财报等资料；首次运行会初始化记忆库。
不要把模型密钥写进前端 `VITE_*` 变量，也不要提交 `.env` 或运行时配置文件。
`CONFIG_ENCRYPTION_KEY` 用于设置页面保存敏感配置；自行生成并私下保管。

## 示例数据与回测

安装脚本已准备 `000063` 的历史示例；也可手动执行：

```powershell
.\System\FinPortfolio_MVP\backend\.venv\Scripts\python.exe .\scripts\prepare_example.py
```

该脚本不会覆盖已存在的分析示例文件；行情登记按文件哈希复用已有版本。
请在界面显示的可用日期中选择分析日。出现“买入”或“谨慎买入”报告后，
点击“验证买入策略”，完成后可打开两种买入方式对应的回测详情。
该对比使用分析日之前的历史窗口，规则见 [联调说明](analyst/docs/entry-validation-local.md)。

完整论文数据、模型权重和历史实验未随仓库上传。
ASACPL/HMMP 训练需要独立安装对应 TensorFlow/PyTorch 环境并准备论文预处理数据。
[数据说明](docs/data.md) 与 [架构说明](docs/architecture.md) 列出了格式和迁移限制。

## 检查与测试

```powershell
# FinPortfolio 后端
Push-Location System/FinPortfolio_MVP/backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location

# AnalystVerse 后端；完整测试会导入真实模型依赖
Push-Location analyst/Analyst
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location

# 前端分别构建
Push-Location analyst/frontend
npm.cmd run build
Pop-Location
Push-Location System/FinPortfolio_MVP/frontend
npm.cmd run build
Pop-Location
```

更多检查命令见 [开发说明](docs/development.md)。研究代码的依赖、路径与长时间训练限制见架构文档。

## 源码整理范围

保留应用源码、测试、前端依赖锁文件、算法插件、研究脚本及小型示例。
未包含虚拟环境、`node_modules`、构建目录、新闻大文件、向量缓存、运行日志、历史实验、模型权重、
旧压缩包、安装程序、个人运行时配置及 Git 历史。旧版 `uv.lock` 与不完整的依赖清单不再混用，
AnalystVerse 依赖由更新后的 `requirements.txt` / `pyproject.toml` 声明。

本项目用于研究与回测，不连接实盘交易。原有子项目文档中的历史测试结果不代表本次重新运行的结果。
来源与授权说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
