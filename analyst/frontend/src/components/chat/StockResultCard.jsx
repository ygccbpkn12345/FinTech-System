import ReactECharts from 'echarts-for-react'
import { Button, Tag } from 'antd'
import { toStockChartOption } from '@/utils/chatResult'

function StockResultCard({ result, onAction }) {
  const data = result?.data || {}
  const actions = Array.isArray(result?.actions) ? result.actions : []
  const chartOption = toStockChartOption(result)

  return (
    <div className="chat-result-card">
      <div className="chat-result-head">
        <div>
          <div className="chat-result-stock">
            {data.stockName || '分析结果'}
            {data.stockCode && <span className="chat-result-code">{data.stockCode}</span>}
          </div>
          {data.analysisDate && (
            <div className="chat-result-date">交易日 {data.analysisDate}</div>
          )}
        </div>
        {data.action && <Tag className="chat-result-action">{data.action}</Tag>}
      </div>

      {result?.summary && <p className="chat-result-summary">{result.summary}</p>}

      <div className="chat-result-meta">
        {data.confidenceText && (
          <span>
            置信度 <b>{data.confidenceText}</b>
          </span>
        )}
        {data.riskSummary && (
          <span className="chat-result-risk">
            风险 <b>{data.riskSummary}</b>
          </span>
        )}
      </div>

      {chartOption && (
        <div className="chat-result-chart">
          <ReactECharts
            option={chartOption}
            style={{ height: 220 }}
            opts={{ renderer: 'canvas' }}
            notMerge
          />
        </div>
      )}

      {actions.length > 0 && (
        <div className="chat-result-actions">
          {actions.map((action) => (
            <Button
              key={`${action.type}-${action.target || action.label}`}
              type="primary"
              size="small"
              onClick={() => onAction?.(result, action)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}

export default StockResultCard
