import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

function RouterWeightChart({ routingWeights = [], horizontal = true }) {
  const maxWeight = Math.max(...routingWeights.map((w) => w.finalWeight), 0)
  const maxId = routingWeights.find((w) => w.finalWeight === maxWeight)?.analystId

  const option = useMemo(() => {
    const names = routingWeights.map((w) => w.analystName.replace('分析师', ''))
    const values = routingWeights.map((w) => +(w.finalWeight * 100).toFixed(1))

    const barData = values.map((val, i) => {
      const row = routingWeights[i]
      const isTop = row.analystId === maxId
      return {
        value: val,
        itemStyle: {
          borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
          color: isTop
            ? {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 1,
                y2: 0,
                colorStops: [
                  { offset: 0, color: '#c8161d' },
                  { offset: 1, color: '#e93030' },
                ],
              }
            : 'rgba(233, 48, 48, 0.35)',
          shadowBlur: isTop ? 10 : 0,
          shadowColor: isTop ? 'rgba(233, 48, 48, 0.35)' : 'transparent',
        },
      }
    })

    const tooltip = {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255, 255, 255, 0.98)',
      borderColor: '#e4e7ed',
      textStyle: { color: '#333333', fontSize: 12 },
      formatter: (params) => {
        const item = params[0]
        const row = routingWeights[item.dataIndex]
        if (!row) return ''
        return [
          `<strong>${row.analystName}</strong>`,
          `最终权重：${(row.finalWeight * 100).toFixed(0)}%`,
          `置信度：${(row.confidenceWeight * 100).toFixed(0)}%`,
          `历史 RAG：${(row.historicalWeight * 100).toFixed(0)}%`,
        ].join('<br/>')
      },
    }

    if (horizontal) {
      return {
        backgroundColor: 'transparent',
        tooltip,
        grid: { left: 72, right: 48, top: 8, bottom: 8 },
        xAxis: {
          type: 'value',
          max: 35,
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.06)', type: 'dashed' } },
          axisLabel: { color: '#999999', fontSize: 10, formatter: '{value}%' },
        },
        yAxis: {
          type: 'category',
          data: names,
          inverse: true,
          axisLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.12)' } },
          axisTick: { show: false },
          axisLabel: { color: '#333333', fontSize: 12, fontWeight: 500 },
        },
        series: [
          {
            name: '最终权重',
            type: 'bar',
            barWidth: 14,
            data: barData,
            label: {
              show: true,
              position: 'right',
              formatter: '{c}%',
              color: '#666666',
              fontSize: 11,
              fontFamily: 'Consolas, monospace',
            },
          },
        ],
      }
    }

    return {
      backgroundColor: 'transparent',
      tooltip,
      grid: { left: 48, right: 16, top: 24, bottom: 36 },
      xAxis: {
        type: 'category',
        data: names,
        axisLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.12)' } },
        axisLabel: { color: '#999999', fontSize: 11, interval: 0 },
      },
      yAxis: {
        type: 'value',
        max: 35,
        splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.06)', type: 'dashed' } },
        axisLabel: { color: '#999999', fontSize: 10 },
      },
      series: [{ name: '最终权重', type: 'bar', barWidth: '48%', data: barData }],
    }
  }, [routingWeights, maxId, horizontal])

  return (
    <ReactECharts
      option={option}
      style={{ height: horizontal ? 220 : 280, width: '100%' }}
      opts={{ renderer: 'canvas' }}
    />
  )
}

export default RouterWeightChart
