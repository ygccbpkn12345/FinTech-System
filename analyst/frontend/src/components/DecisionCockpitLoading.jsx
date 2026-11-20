import { Alert, Skeleton, Spin } from 'antd'
import { CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'

function DecisionCockpitLoading({ loading, failed = false, error = '' }) {
  return (
    <div
      className={`decision-cockpit decision-cockpit--loading${failed ? ' decision-cockpit--failed' : ''}`}
    >
      <div className="cockpit-header">
        <div>
          <div className="cockpit-title">终局输出：决策驾驶舱</div>
          <div className="cockpit-subtitle">Final Decision Cockpit</div>
        </div>
        <span className={`cockpit-status-badge${failed ? ' cockpit-status-badge--failed' : ''}`}>
          {loading ? 'Running' : failed ? 'Failed' : 'Waiting'}
        </span>
      </div>

      {failed ? (
        <div className="cockpit-loading-center">
          <CloseCircleOutlined className="cockpit-failed-icon" />
          <div className="cockpit-loading-text">分析未完成，未生成最终决策</div>
          {error ? (
            <Alert
              type="error"
              showIcon
              message={error}
              className="cockpit-failed-alert"
            />
          ) : null}
        </div>
      ) : (
        <>
          <div className="cockpit-loading-center">
            <Spin indicator={<LoadingOutlined style={{ fontSize: 28 }} spin />} />
            <div className="cockpit-loading-text">等待最终决策生成中</div>
          </div>
          <Skeleton active paragraph={{ rows: 5 }} title={{ width: '60%' }} />
        </>
      )}

      <div className="cockpit-footer">AI 决策建议 · 非真实交易指令</div>
    </div>
  )
}

export default DecisionCockpitLoading
