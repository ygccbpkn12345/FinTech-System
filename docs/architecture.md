# 架构与迁移说明

## 两套独立应用

AnalystVerse 前端请求 `/api`，由 Vite 转发到 `8000`。
其后端处理聊天、数据获取、股票分析及报告管理。
买入方式验证由 `Analyst/services/strategy_validation.py` 调用 `8001` 的 FinPortfolio API；
报告中的结果链接打开 `5174` 的 FinPortfolio 回测页面。

FinPortfolio 后端只解析插件 manifest，实验由任务管理器提交到子进程。
前端根据插件声明生成算法选项及参数表单，结果通过统一协议输出。

| 目录 | 主要职责 |
|---|---|
| `analyst/Analyst/agent`、`graph` | 多分析师、综合决策、风险管理和反思 |
| `analyst/Analyst/services` | 聊天编排、数据服务、算法注册、任务事件、报告及联动 |
| `System/FinPortfolio_MVP/backend/app/core` | 路径、插件、结果协议、评价指标 |
| `System/FinPortfolio_MVP/backend/app/workers` | 子进程任务调度与执行 |
| `System/FinPortfolio_MVP/backend/app/services` | 数据集、实验、结果导入 |
| `System/FinPortfolio_MVP/plugins` | ASACPL、HMMP、等权与单股买入方式适配器 |

## 配置与数据隔离

AnalystVerse 使用 `analyst/Analyst/.env`，在导入运行配置服务前加载。
个人运行配置、加密凭据、算法注册状态、聊天及分析产物不上传。
FinPortfolio 默认运行目录为 `System/FinPortfolio_MVP`，支持 `FINPORTFOLIO_*` 环境变量覆盖。
数据索引在新机器上重新登记，避免携带原机器绝对路径。

## 当前边界

- 两套独立前后端，没有统一账号系统。开发服务仅监听本机地址。
- AnalystVerse 分析任务在内存中，后端重启后需重新分析；FinPortfolio 实验单独持久化。
- 默认演示分析不调用真实分析流水线；真实分析需模型密钥、PyTorch、新闻及财报等资料。
- 单股买入方式比较分析日前 20 个有效交易日，第 20 日退出，分批在第 1 与第 6 日各投入一半；
  这是历史规则对照，不是未来收益预测。
- ASACPL/HMMP 的完整训练不属于快速启动验收。TensorFlow 与 PyTorch 应在独立环境运行，
  在插件 manifest 的 `python_executable` 中配置相应解释器。
- **ASACPL 的原始脚本仍有作者机器的绝对数据/日志路径**，原适配器也会为这些路径创建目录。
  本次只整理发布，不改动论文算法。跨机器训练前需检查 `System/ASACPL` 与 asacpl 适配器路径，
  并准备对应数据；不要将“插件已发现”视为“论文训练可直接复现”。
- HMMP 新闻预处理原文件包含重复研究代码段，已移除各段的硬编码密钥，保留原算法结构。
- ASACPL notebook 仅移除了运行输出与执行序号，未重新执行研究单元。

子项目中的历史报告和设计文档用于说明已有实现；启动与端口以仓库首页为准。
