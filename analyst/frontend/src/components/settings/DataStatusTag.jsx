import { Tag } from 'antd'

const STATUS_MAP = {
  ready: { color: 'success', label: '已配置' },
  partial: { color: 'warning', label: '部分' },
  missing: { color: 'error', label: '缺失' },
  optional: { color: 'default', label: '未配置' },
}

function DataStatusTag({ status, optional = false }) {
  let normalized =
    status === true || status === 'ready' || status === 'configured'
      ? 'ready'
      : status === 'partial'
        ? 'partial'
        : status === 'optional'
          ? 'optional'
          : 'missing'

  if (normalized === 'missing' && optional) {
    normalized = 'optional'
  }

  const meta = STATUS_MAP[normalized] ?? STATUS_MAP.missing
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export default DataStatusTag
