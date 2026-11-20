import ReactECharts from 'echarts-for-react'

const CHART = {
  text: '#666666',
  textMuted: '#999999',
  axis: 'rgba(0, 0, 0, 0.12)',
  split: 'rgba(0, 0, 0, 0.06)',
  tooltipBg: 'rgba(255, 255, 255, 0.98)',
  tooltipBorder: '#e4e7ed',
  brand: '#e93030',
}

function PriceChart({ dates = [], prices = [] }) {
  const option = {
    backgroundColor: 'transparent',
    textStyle: { color: CHART.text },
    tooltip: {
      trigger: 'axis',
      backgroundColor: CHART.tooltipBg,
      borderColor: CHART.tooltipBorder,
      textStyle: { color: '#333333', fontSize: 12 },
    },
    grid: {
      left: 48,
      right: 24,
      top: 24,
      bottom: 32,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: CHART.axis } },
      axisLabel: { color: CHART.textMuted, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: CHART.split, type: 'dashed' } },
      axisLabel: { color: CHART.textMuted, fontSize: 11 },
    },
    series: [
      {
        name: '收盘价',
        type: 'line',
        smooth: true,
        data: prices,
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(233, 48, 48, 0.18)' },
              { offset: 1, color: 'rgba(233, 48, 48, 0.02)' },
            ],
          },
        },
        lineStyle: {
          width: 2,
          color: CHART.brand,
        },
        itemStyle: { color: CHART.brand },
      },
    ],
  }

  return <ReactECharts option={option} style={{ height: 320 }} opts={{ renderer: 'canvas' }} />
}

export default PriceChart
