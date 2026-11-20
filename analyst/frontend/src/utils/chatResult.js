/** 把股票分析结果转换成聊天消息可直接渲染的结构。 */

const DEFAULT_ACTION = '--'

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function pickText(...values) {
  for (const value of values) {
    if (value != null && String(value).trim() !== '') return String(value)
  }
  return ''
}

function findVisualization(result) {
  const visualizations = asArray(asObject(result).visualizations)
  return visualizations.find((item) => item?.type === 'line') || visualizations[0] || null
}

export function toStockChartOption(result) {
  const visualization = findVisualization(result)
  if (!visualization) return null

  const x = asArray(visualization.x)
  const series = asArray(visualization.series)
  if (!x.length && !series.length) return null

  return {
    grid: { left: 12, right: 16, top: 28, bottom: 28, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: x, boundaryGap: false },
    yAxis: { type: 'value', scale: true },
    series: series.map((item) => ({
      name: pickText(item?.name, visualization.title, '价格'),
      type: visualization.type === 'bar' ? 'bar' : 'line',
      smooth: visualization.type !== 'bar',
      showSymbol: false,
      data: asArray(item?.data),
      areaStyle: visualization.type === 'line' ? { opacity: 0.12 } : undefined,
    })),
  }
}

function formatConfidence(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return ''
  return `${Math.round(number * 100)}%`
}

function describeRisk(items) {
  if (!items.length) return ''
  const first = items[0]
  const level = pickText(first.levelLabel, first.level)
  const text = pickText(first.explanation, first.riskType)
  return [level, text].filter(Boolean).join(' · ')
}

export function buildStockResultPayload(analysisResult) {
  const result = asObject(analysisResult)
  const stock = asObject(result.stock ?? result.stockInfo)
  const decision = asObject(result.finalDecision)
  const chartData = asObject(result.chartData ?? result.marketChart)
  const riskItems = asArray(asObject(result.riskAssessment).items ?? result.riskList)

  const stockCode = pickText(stock.code, result.stockCode)
  const stockName = pickText(stock.name, result.stockName)
  const analysisDate = pickText(stock.analysisDate, result.analysisDate)
  const action = pickText(decision.action, DEFAULT_ACTION)

  const displayName = stockName ? `${stockName}（${stockCode || '--'}）` : stockCode || '该股票'
  const dateText = analysisDate && analysisDate !== '--' ? `在 ${analysisDate} ` : ''
  const confidence = Number(decision.confidence) || 0
  const confidenceText = formatConfidence(confidence)

  const summary = [
    `${displayName}${dateText}的综合判断为「${action}」`,
    confidenceText ? `，置信度 ${confidenceText}` : '',
    pickText(decision.coreReason) ? `。核心依据：${pickText(decision.coreReason)}` : '。',
  ].join('')

  const dates = asArray(chartData.dates)
  const prices = asArray(chartData.prices)
  const visualizations = dates.length
    ? [
        {
          type: 'line',
          title: '价格走势',
          x: dates,
          series: [{ name: '收盘价', data: prices }],
        },
      ]
    : []

  return {
    tool: 'stock_prediction',
    status: 'completed',
    summary,
    data: {
      taskId: pickText(result.taskId),
      stockCode,
      stockName,
      analysisDate,
      action,
      actionEn: pickText(decision.actionEn),
      confidence,
      confidenceText,
      coreReason: pickText(decision.coreReason),
      riskSummary: describeRisk(riskItems),
      keyRisks: asArray(decision.keyRisks),
    },
    visualizations,
    actions: [
      {
        type: 'navigate',
        label: '查看完整分析',
        target: '/dashboard',
        value: pickText(result.taskId),
      },
    ],
  }
}
