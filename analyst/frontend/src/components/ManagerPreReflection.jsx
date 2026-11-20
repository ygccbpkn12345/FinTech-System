import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { Tag } from 'antd'
import { DisplayParagraphs } from '@/components/DisplayText'

const STATUS_ICON = {
  passed: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  warning: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
  failed: <CloseCircleOutlined style={{ color: '#f5222d' }} />,
}

const STATUS_LABEL = {
  passed: { text: '通过', className: 'tag-risk-low' },
  warning: { text: '待改进', className: 'tag-risk-medium' },
  failed: { text: '漏洞', className: 'tag-risk-high' },
}

function ManagerPreReflection({ preReflection = {} }) {
  const checks = Array.isArray(preReflection?.checks) ? preReflection.checks : []
  const summary = preReflection?.summary ?? ''

  if (!summary && !checks.length) {
    return (
      <div className="cockpit-placeholder-body" style={{ minHeight: 80 }}>
        暂无经理事前反思数据
      </div>
    )
  }

  return (
    <div className="manager-prereflect">
      {summary ? (
        <DisplayParagraphs className="manager-prereflect-summary" children={summary} />
      ) : null}
      <div className="manager-prereflect-list">
        {checks.map((check, index) => {
          const statusTag = STATUS_LABEL[check?.status] ?? STATUS_LABEL.warning
          return (
            <div
              key={check?.id ?? `check-${index}`}
              className={`manager-prereflect-item manager-prereflect-item--${check?.status ?? 'warning'}`}
            >
              <div className="manager-prereflect-item-head">
                {STATUS_ICON[check?.status] ?? STATUS_ICON.warning}
                <span className="manager-prereflect-area">{check?.area ?? '--'}</span>
                <Tag className={statusTag.className}>{statusTag.text}</Tag>
              </div>
              <div className="manager-prereflect-question">{check?.question ?? '--'}</div>
              <DisplayParagraphs
                className="manager-prereflect-finding"
                children={check?.finding ?? '--'}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default ManagerPreReflection
