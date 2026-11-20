# FinPortfolio — 可扩展金融智能投资组合算法管理与可视化平台

前后端分离、插件化架构的金融算法实验平台。两篇论文算法（ASACPL、HMMP）以**独立插件**形式接入，
各自运行在自己的 Python 环境与**独立子进程**中，互不依赖、互不污染；另含 Equal Weight 基线插件
作为插件化架构的验收示例（接入时未改动任何核心代码与前端）。

> 平台是研究回测工具，**不是实盘交易系统**。所有指标口径显式声明，不伪造、不混合论文原始结果与平台复算结果。

---

## 1. 架构总览

```
┌────────────────────────────── 前端 React + TS (Vite) ──────────────────────────────┐
│  9 页面：概览 / 算法中心 / 训练中心 / 股票筛选 / 组合配置 / 回测分析 / 对比 / 数据集 / 实验 │
│  算法下拉、参数表单全部由 /api/algorithms 与 manifest 动态生成（前端零算法硬编码）      │
└───────────────────────────────┬────────────────────────────────────────────────────┘
                                │ HTTP /api/*
┌───────────────────────────────┴────────────────────────────────────────────────────┐
│  FastAPI 后端（不 import 任何插件代码，只解析 manifest.yaml）                        │
│  ├─ PluginRegistry    插件发现 / Pydantic 严格校验 / 错误隔离                        │
│  ├─ DatasetService    数据集元信息 / 完整性校验 / 算法兼容性检查                      │
│  ├─ ExperimentService 实验编排 → TaskManager 提交子进程任务                          │
│  ├─ TaskManager       daemon 工作线程池 / 超时 / 取消 / taskkill 兜底 / 原子持久化   │
│  ├─ ImportService     论文 CSV → StandardPortfolioResult 统一导入                    │
│  └─ Metrics           252 交易日年化、rf=0、几何复利、单边换手（口径显式）             │
└───────┬──────────────────────┬──────────────────────┬──────────────────────────────┘
        │ argv 列表子进程        │                      │
┌───────┴────────┐    ┌────────┴────────┐    ┌─────────┴────────┐
│ plugins/       │    │ plugins/        │    │ plugins/         │
│ equal_weight/  │    │ asacpl/         │    │ hmmp/            │
│ (NumPy, 基线)  │    │ TF 2.x 独立环境  │    │ PyTorch 独立环境  │
│ adapter.py     │    │ adapter.py      │    │ adapter.py       │
│ manifest.yaml  │    │ → System/ASACPL │    │ → System/HMMP    │
│                │    │  (原始代码零修改)│    │  (原始代码零修改) │
└────────────────┘    └─────────────────┘    └──────────────────┘
        每个插件 = manifest.yaml（声明） + adapter.py（实现 BasePortfolioPlugin）
        plugin_runner.py（纯 stdlib）在插件自己的解释器里加载并调用，产出 result.json
```

### 关键设计决策

| 决策 | 说明 |
|---|---|
| 注册与执行分离 | FastAPI 进程只读 manifest.yaml，绝不 import 插件代码 → TF/torch 不进后端进程 |
| 独立 Python 环境 | 每个插件可在 manifest 声明 `python_executable`；缺失时回退后端解释器并警告 |
| 安全子进程 | 命令强制 `[python, runner, payload.json]` 参数列表，禁止 shell 拼接；Windows `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F` 兜底终止 |
| 论文代码零修改 | ASACPL 通过 importlib 复刻 `__main__` 流程（含 state_space 注入、硬编码日志目录预创建）；HMMP 通过 CWD 注入 `Data/`（junction 优先）后以白名单 argv 调 `B_Train.py` |
| 统一结果契约 | StandardPortfolioResult：毛/净收益分离、权重关联真实代码、非负与预算约束强校验（容差 5e-3）、口径假设显式 |
| 两种回测模式 | `paper_original`（论文原始口径，费前）与 `unified_rebalance`（平台统一再平衡口径）绝不混用 |

---

## 2. 目录结构

```
FinPortfolio_MVP/
├─ backend/
│  ├─ app/
│  │  ├─ core/        paths / manifest_schema / plugin_interface(纯stdlib) /
│  │  │               plugin_registry / result_schema / metrics
│  │  ├─ workers/     task_manager / plugin_runner(纯stdlib 子进程入口)
│  │  ├─ services/    dataset_service / experiment_service / import_service
│  │  ├─ api/         routes_{algorithms,datasets,experiments,tasks,results,system}
│  │  ├─ schemas/     api_models
│  │  └─ main.py      组合根
│  ├─ tests/          66 个测试（manifest/registry/task/result/metrics/dataset/api/EW端到端）
│  └─ requirements.txt
├─ plugins/
│  ├─ equal_weight/   基线插件（NumPy，真实回测）
│  ├─ asacpl/         论文A：HLB-AS 筛选 + CNN 协方差 + 异步 A3C（TensorFlow）
│  └─ hmmp/           论文B：多模态 MoE + 分层配置 + CTDE-MAPPO（PyTorch）
├─ frontend/
│  ├─ src/
│  │  ├─ pages/       9 个页面（懒加载）
│  │  ├─ components/  ui / ParamForm(manifest动态表单) / charts
│  │  ├─ api/ client.ts  hooks/ useApi.ts  router.tsx(自写hash路由)
│  │  └─ layouts/ MainLayout.tsx
│  └─ package.json    （未新增任何 npm 依赖）
├─ scripts/
│  ├─ register_datasets.py   登记论文真实数据集
│  └─ check_plugins.py       插件发现自检
├─ datasets/ experiments/ logs/ checkpoints/   （运行时存储，自动创建）
└─ README.md
```

原始论文代码随整合仓库提供，位于 `System/ASACPL` 和 `System/HMMP`；对本子项目而言，位于 `FINPORTFOLIO_ORIGINAL_CODE_ROOT`（默认 `../`，即 `System/ASACPL` 与 `System/HMMP`），保持零修改。

---

## 3. 启动（PowerShell）

以下每段命令都**从项目根目录出发**，可独立复制执行。

```powershell
$ROOT = (Get-Location).Path  # 从 System/FinPortfolio_MVP 目录执行

# ---------- 后端（保持运行的终端 1） ----------
cd "$ROOT\backend"
python -m pip install -r requirements.txt
python -m app
# API 文档: http://127.0.0.1:8001/docs

# ---------- 前端（新开终端 2） ----------
cd "$ROOT\frontend"
npm install        # 首次运行需要
npm run dev        # 开发: http://localhost:5174（已代理 /api → 8001）
npm run build      # 生产构建（tsc -b && vite build）

# ---------- 数据集登记（一次性，另开终端） ----------
cd "$ROOT\backend"
python ..\scripts\register_datasets.py          # 登记两个论文真实数据集
python ..\scripts\check_plugins.py              # 插件发现自检（应输出 3 个 READY）

# ---------- 测试 ----------
cd "$ROOT\backend"
python -m pytest tests -q                        # 66 个测试
```

### 运行论文算法（需先训练好模型或使用论文原产物）

- **ASACPL**：训练中心 → 算法 `asacpl` → 能力 `train` → 数据集 `asacpl_sp500_test2023`。
  注意 `max_episodes=100` 为演示默认值（论文完整训练请按论文设置调大），需要 TensorFlow 环境。
- **HMMP**：训练中心 → `hmmp` → `train` → `hmmp_csi500_features`。需要 PyTorch 环境，
  适配器自动把数据集以 junction 挂到其工作目录 `Data/`。
- **论文 CSV 直接导入**（不跑模型）：实验管理页 →「导入论文结果 CSV」，
  ASACPL 上传 returns+weights，HMMP 上传 returns+industry+intra；导入结果标记 `paper_original` 费前口径。

### 环境变量（可选）

| 变量 | 作用 |
|---|---|
| `FINPORTFOLIO_ROOT` | 运行时存储根目录（默认项目根） |
| `FINPORTFOLIO_PLUGINS_DIR` / `FINPORTFOLIO_DATASETS_DIR` / ... | 各存储子目录覆盖 |
| `FINPORTFOLIO_ORIGINAL_CODE_ROOT` | 论文原始代码根（默认项目根的上级） |
| `FINPORTFOLIO_MAX_CONCURRENT_TASKS` | 并发子进程上限 |
| `FINPORTFOLIO_ALLOW_PATH_IMPORT=1` | 允许服务器本地路径导入（仅受信管理员） |

---

## 4. 新算法接入指南（无需改任何核心代码 / 前端）

1. 新建 `plugins/<your_algo>/`，写 `manifest.yaml`（id/name/capabilities/parameters/execution…，
   严格校验，未知字段拒绝）与 `adapter.py`（继承 runner 注入的 `finportfolio_plugin_interface.BasePortfolioPlugin`，
   按能力实现 `train/predict/backtest/stock_selection` 等方法，返回 dict）。
2. 如需独立环境：manifest 里写 `execution.python_executable: "<venv>/python.exe"`。
3. 后端启动时自动发现（或调 `GET /api/algorithms/registry/reload`）。坏 manifest 只隔离自身。
4. 前端算法中心 / 训练中心自动出现新算法，参数表单由 manifest 动态生成。

参考实现：`plugins/equal_weight/`（约 200 行，最简完整示例）。

---

## 5. 完成状态矩阵（诚实版）

| 功能 | 状态 | 验证方式 |
|---|---|---|
| 插件系统（manifest 校验/注册/隔离/参数校验） | ✅ 已实现且测试通过 | test_manifest_schema / test_plugin_registry |
| 子进程任务管理（状态机/超时/取消/日志/并发） | ✅ 已实现且测试通过 | test_task_manager |
| 数据集管理（元信息/校验/兼容性） | ✅ 已实现且测试通过 | test_datasets + 真实数据集实测 |
| StandardPortfolioResult（约束/口径） | ✅ 已实现且测试通过 | test_result_schema / test_api |
| 指标计算（年化/Sharpe/MDD/换手） | ✅ 已实现且测试通过 | test_metrics |
| Equal Weight 插件端到端 | ✅ 已实现且真实验证 | 真实 S&P500 2023 数据回测（见下） |
| 前端 9 页面 + 动态算法 + 动态表单 | ✅ 已实现，构建通过 | `npm run build` + 全部 API 契约实测 |
| 论文 CSV 导入（ASACPL/HMMP 两口径） | ✅ 已实现且测试通过 | test_api（HMMP 行业×条件 0.6×0.7=0.42 断言） |
| **ASACPL 训练执行** | ⚠️ 适配层已接通、机制可用；**完整论文级训练未在本次会话完整跑完**（耗时长 + 需 TF 环境）。论文 CSV 导入路径已验证 | 通过 importlib 加载原代码实测 |
| **HMMP 训练执行** | ⚠️ 同上：适配层已接通（junction + 白名单 argv），完整论文级训练未跑完 | 数据集已登记、兼容性检查通过 |
| Redis + Celery 分布式调度 | ❌ 未实现（按任务书初期不要求，TaskManager 可扩展替换） | — |

### 真实验证结果摘要（S&P500 2023 · Equal Weight · 每日再平衡 · cost_pct=0.001）

250 个交易日、20 只股票（真实论文数据集 `asacpl_sp500_test2023`）：
累计收益 **+26.24%**，几何年化 **+26.48%**，Sharpe **2.13**（rf=0），
最大回撤 **-7.59%**，平均单边换手 **0.86%/日**。
毛收益与扣费序列分离输出，权重非负、预算偏差 < 5e-3，全部约束校验通过。
（此为平台 `unified_rebalance` 口径的基线验证，**不是论文实验结果**。）

论文原始结果的费前口径（两篇论文环境均未实现交易扣费）在导入与适配输出中以
`cost_included=false` + notes 如实标注。

---

## 6. 已知限制

- ASACPL/HMMP 完整论文级训练（数千 episode / epoch）在 CPU 上耗时极长，本次未完整执行；
  适配层与任务通道均已打通并用真实数据/代码验证过加载路径。
- 结果对比页对跨论文比较（ASACPL vs HMMP）始终提示「非受控公平基准」（市场/切分/协议不同）。
- 前端 hash 路由为自写实现（避免新增依赖），刷新后保持当前页面。
