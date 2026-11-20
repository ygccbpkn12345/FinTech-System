# 单股买入方式联调

安装和启动统一按 [仓库首页](../../README.md) 执行。

| 服务 | 地址 |
|---|---|
| AnalystVerse API | http://127.0.0.1:8000 |
| AnalystVerse UI | http://127.0.0.1:5173 |
| FinPortfolio API | http://127.0.0.1:8001 |
| FinPortfolio UI | http://127.0.0.1:5174 |

运行 `scripts/prepare_example.py` 后，FinPortfolio 会登记仓库附带的 `000063` 行情快照，
AnalystVerse 会获得一只股票的示例分析资料。演示模式为 `BACKEND_USE_REAL_MODEL=false`。
分析日期应位于本地数据覆盖范围内；只有“买入”或“谨慎买入”报告开放买入方式验证。

点击“验证买入策略”后，会提交一次买入和分两批买入两个实验。
两者使用分析日之前最近 20 条有效日线、第 20 日收盘退出；分批买入在第 1、6 日各投入一半，
每笔成交费率为 0.1%。结果中的链接打开 FinPortfolio 回测详情。

该功能比较已经发生的历史窗口，不是分析日之后的预测收益；
日线开收盘成交模型未纳入涨跌停、滑点和最小交易单位。
AnalystVerse 的任务存于进程内，后端重启后需要重新分析；FinPortfolio 实验结果独立持久化。
