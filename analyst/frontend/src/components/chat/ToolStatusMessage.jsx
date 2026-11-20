import { Progress, Spin, Typography } from 'antd'

const { Text } = Typography

function ToolStatusMessage({ message }) {
  const progress = Number(message?.data?.progress ?? message?.result?.data?.progress ?? 0)
  const hasProgress = Number.isFinite(progress) && progress > 0

  return (
    <div className="chat-tool-status">
      <Spin size="small" />
      <div className="chat-tool-body">
        <Text className="chat-tool-text">{message?.content || '工具执行中…'}</Text>
        {hasProgress && (
          <Progress
            percent={Math.min(100, Math.round(progress))}
            size="small"
            showInfo={false}
            strokeColor="var(--brand-red)"
          />
        )}
      </div>
    </div>
  )
}

export default ToolStatusMessage
