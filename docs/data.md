# 数据说明

## 附带示例

- `examples/data/000063_prices.csv`：从现有 FinPortfolio 登记快照提取的真实日线，
  字段为 `date,tic,open,close,volume`。价格口径沿用原文件。
- `examples/analyst/`：现有项目中 `000063` 对应的技术指标、新闻、行业资料、三张财报与历史结果 CSV，
  原样保留为小型演示资料，不代表当前行情或新生成的预测结果。

运行 `scripts/prepare_example.py` 将分析资料复制到本地运行目录，并通过现有登记脚本登记行情快照。
默认跳过已存在的分析文件；相同快照版本重复登记会复用。
不要用少量示例评价模型效果，也不要把历史结果当作实时收益。

## 导入自己的行情

在仓库根目录运行：

```powershell
.\System\FinPortfolio_MVP\backend\.venv\Scripts\python.exe `
  .\System\FinPortfolio_MVP\scripts\register_analystverse_prices.py `
  000063 'C:\your-data\prices.csv'
```

CSV 至少包含 `date,open,close,volume`，日期为 `YYYY-MM-DD`，同一日期不可重复，
可选 `tic` / `symbol` 必须与六位股票代码一致；价格和成交量须为正数。
买入方式回测需要分析日前至少 20 条有效行情。

## 论文数据

完整论文数据未随本仓库分发。ASACPL 需要预处理后的 `02_train_CNN.csv` 和 `02_test_CNN.csv`，
包括协方差与 f1-f4 特征；HMMP 需要行业价格、行业新闻及股票特征等预处理产物。
获取有权使用的数据后，显式指定路径登记：

```powershell
.\System\FinPortfolio_MVP\backend\.venv\Scripts\python.exe `
  .\System\FinPortfolio_MVP\scripts\register_datasets.py `
  --asacpl-data 'C:\your-data\asacpl' --hmmp-data 'C:\your-data\hmmp'
```

脚本的默认探测路径沿用研究阶段布局，跨机器应使用上述参数。
论文数据以 reference 模式登记，移动文件后需要重新登记。

运行时数据目录、数据索引、向量缓存、模型权重、实验输出均由 `.gitignore` 排除。
