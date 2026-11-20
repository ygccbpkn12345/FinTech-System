import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { analysisMock } from '@/mock/analysisMock'
import TerminalCard from './TerminalCard'
import { calcMA } from '@/utils/chartUtils'

const FALLBACK_CHART = {
  dates: analysisMock.marketChart?.dates ?? [],
  prices: analysisMock.marketChart?.prices ?? [],
  volumes: analysisMock.marketChart?.volumes ?? [],
}

function MarketChartPanel({ chartData, isUp = true }) {
  const source = chartData ?? {}
  const hasData =
    (Array.isArray(source.dates) && source.dates.length > 0) ||
    (Array.isArray(source.prices) && source.prices.length > 0)

  const safeChart = hasData
    ? {
        dates: Array.isArray(source.dates) ? source.dates : [],
        prices: Array.isArray(source.prices) ? source.prices : [],
        volumes: Array.isArray(source.volumes) ? source.volumes : [],
      }
    : FALLBACK_CHART

  const option = useMemo(() => {
    const lineColor = isUp ? '#f5222d' : '#52c41a'
    const ma5 = calcMA(safeChart.prices, 5)
    const ma10 = calcMA(safeChart.prices, 10)

    return {
      backgroundColor: 'transparent',
      animation: true,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', crossStyle: { color: '#999999' } },
        backgroundColor: 'rgba(255, 255, 255, 0.98)',
        borderColor: '#e4e7ed',
        textStyle: { color: '#333333', fontSize: 12 },
        formatter: (params) => {
          const date = params[0]?.axisValue ?? ''
          const price = params.find((p) => p.seriesName === '收盘价')
          const ma5p = params.find((p) => p.seriesName === 'MA5')
          const ma10p = params.find((p) => p.seriesName === 'MA10')
          const vol = params.find((p) => p.seriesName === '成交量')
          const lines = [`<strong>${date}</strong>`]
          if (price) lines.push(`收盘价：${price.data}`)
          if (ma5p?.data != null) lines.push(`MA5：${ma5p.data}`)
          if (ma10p?.data != null) lines.push(`MA10：${ma10p.data}`)
          if (vol) lines.push(`成交量：${vol.data} 万手`)
          return lines.join('<br/>')
        },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      legend: {
        data: ['收盘价', 'MA5', 'MA10'],
        top: 4,
        right: 120,
        textStyle: { color: '#666666', fontSize: 10 },
        itemWidth: 14,
        itemHeight: 8,
      },
      graphic: [
        {
          type: 'text',
          right: 12,
          top: 8,
          style: {
            text: '30 Trading Days',
            fill: '#999999',
            font: '11px Consolas, monospace',
          },
        },
      ],
      grid: [
        { left: 52, right: 16, top: 32, height: '54%' },
        { left: 52, right: 16, top: '76%', height: '16%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: safeChart.dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.12)' } },
          axisLabel: { color: '#999999', fontSize: 10, interval: 5 },
          axisTick: { show: false },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: safeChart.dates,
          boundaryGap: true,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.06)', type: 'dashed' } },
          axisLabel: { color: '#999999', fontSize: 10 },
          axisLine: { show: false },
        },
        {
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { color: '#999999', fontSize: 9 },
          axisLine: { show: false },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '收盘价',
          type: 'line',
          data: safeChart.prices,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 2, color: lineColor },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: isUp ? 'rgba(245,34,45,0.2)' : 'rgba(82,196,26,0.15)' },
                { offset: 1, color: 'rgba(0,0,0,0)' },
              ],
            },
          },
        },
        {
          name: 'MA5',
          type: 'line',
          data: ma5,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.5, color: '#faad14' },
        },
        {
          name: 'MA10',
          type: 'line',
          data: ma10,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.5, color: '#666666' },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: safeChart.volumes,
          barWidth: '55%',
          itemStyle: {
            color: (params) => {
              const idx = params.dataIndex
              const prev = safeChart.prices[idx - 1] ?? safeChart.prices[idx]
              const curr = safeChart.prices[idx]
              return curr >= prev ? 'rgba(245, 34, 45, 0.55)' : 'rgba(82, 196, 26, 0.55)'
            },
          },
        },
      ],
    }
  }, [safeChart.dates, safeChart.prices, safeChart.volumes, isUp])

  return (
    <TerminalCard
      title="行情层：价格与成交量"
      subtitle="Market Chart Layer"
      extra="K-Line Style"
      bodyClassName="chart-panel-body"
    >
      <ReactECharts option={option} style={{ height: 220, width: '100%' }} opts={{ renderer: 'canvas' }} />
    </TerminalCard>
  )
}

export default MarketChartPanel
