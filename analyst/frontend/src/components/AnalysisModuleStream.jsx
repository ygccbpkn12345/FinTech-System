import { Card, Empty, Tag, Typography } from 'antd'
import { ANALYSIS_MODULES } from '@/utils/analysisModuleDefinitions'

const { Paragraph, Text } = Typography

const STATUS_META = {
  pending: ['default', '等待'],
  running: ['processing', '运行中'],
  completed: ['success', '已完成'],
  failed: ['error', '失败'],
}

function renderPayload(result) {
  if (result == null) return ''
  if (typeof result === 'string') return result
  return Object.entries(result)
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('\n')
}

function AnalysisModuleStream({ modules = {}, currentNode = '', taskStatus = 'running', streamState }) {
  return (
    <div>
      {streamState === 'reconnecting' && (
        <Paragraph type="warning">实时连接中断，正在重连；已完成的模块结果会保留。</Paragraph>
      )}
      <div className="analyst-grid analyst-grid--enhanced">
        {ANALYSIS_MODULES.map(([name, label]) => {
          const event = modules[name]
          const status = event?.status === 'completed'
            ? 'completed'
            : taskStatus === 'failed' && currentNode === name
              ? 'failed'
              : currentNode === name
                ? 'running'
                : 'pending'
          const [color, statusLabel] = STATUS_META[status]
          const payload = renderPayload(event?.result)
          return (
            <Card
              key={name}
              size="small"
              title={label}
              extra={<Tag color={color}>{statusLabel}</Tag>}
              className="analyst-card"
            >
              {payload ? (
                <Paragraph ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}>
                  <Text style={{ whiteSpace: 'pre-wrap' }}>{payload}</Text>
                </Paragraph>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="等待模块输出" />
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}

export default AnalysisModuleStream
