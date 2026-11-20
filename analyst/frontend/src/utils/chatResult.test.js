import test from 'node:test'
import assert from 'node:assert/strict'
import { buildStockResultPayload, toStockChartOption } from './chatResult.js'

test('stock result becomes line chart option', () => {
  const option = toStockChartOption({
    visualizations: [
      {
        type: 'line',
        title: '价格走势',
        x: ['2024-01-02', '2024-01-03'],
        series: [{ name: '收盘价', data: [10, 11] }],
      },
    ],
  })
  assert.deepEqual(option.xAxis.data, ['2024-01-02', '2024-01-03'])
  assert.deepEqual(option.series[0].data, [10, 11])
})

test('chart option is null without a line visualization', () => {
  assert.equal(toStockChartOption({ visualizations: [] }), null)
  assert.equal(toStockChartOption(null), null)
})

test('chart option keeps series names', () => {
  const option = toStockChartOption({
    visualizations: [
      { type: 'line', title: '走势', x: ['d1'], series: [{ name: '收盘价', data: [1] }] },
    ],
  })
  assert.equal(option.series[0].name, '收盘价')
  assert.equal(option.series[0].type, 'line')
})

test('analysis result becomes a completed chat tool result', () => {
  const payload = buildStockResultPayload({
    taskId: 'task-1',
    stock: { code: '000063', name: '中兴通讯', analysisDate: '2024-01-03' },
    finalDecision: {
      action: '谨慎买入',
      confidence: 0.68,
      coreReason: '分析师整体偏多，但风险项仍存。',
      keyRisks: ['估值偏高'],
    },
    riskAssessment: {
      items: [
        {
          riskType: '估值风险',
          levelLabel: '中等',
          explanation: '当前估值高于行业中位。',
        },
      ],
    },
    chartData: { dates: ['2024-01-02', '2024-01-03'], prices: [10, 11] },
  })

  assert.equal(payload.status, 'completed')
  assert.equal(payload.tool, 'stock_prediction')
  assert.match(payload.summary, /中兴通讯/)
  assert.match(payload.summary, /谨慎买入/)
  assert.equal(payload.data.confidence, 0.68)
  assert.equal(payload.data.riskSummary, '中等 · 当前估值高于行业中位。')
  assert.equal(payload.visualizations[0].x.length, 2)
  assert.equal(payload.actions[0].type, 'navigate')
  assert.equal(payload.actions[0].target, '/dashboard')
  assert.equal(payload.actions[0].value, 'task-1')
})

test('missing analysis fields still produce a usable result', () => {
  const payload = buildStockResultPayload({ taskId: 'task-2' })

  assert.equal(payload.status, 'completed')
  assert.equal(payload.data.confidence, 0)
  assert.deepEqual(payload.visualizations, [])
  assert.equal(payload.actions[0].value, 'task-2')
})
