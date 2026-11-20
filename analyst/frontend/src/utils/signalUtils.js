export function getSignalTag(signal) {
  const map = {
    bullish: { label: '偏多', className: 'tag-up', key: 'bullish' },
    bearish: { label: '偏空', className: 'tag-down', key: 'bearish' },
    neutral: { label: '中性', className: 'tag-neutral', key: 'neutral' },
  }
  return map[signal] ?? map.neutral
}

export function getSignalCardClass(signal) {
  const map = {
    bullish: 'analyst-card--bullish',
    bearish: 'analyst-card--bearish',
    neutral: 'analyst-card--neutral',
  }
  return map[signal] ?? map.neutral
}

export function getStatusTag(status) {
  const map = {
    completed: { label: '已完成', className: 'tag-status-completed' },
    running: { label: '分析中', className: 'tag-status-running' },
    pending: { label: '等待中', className: 'tag-status-pending' },
    failed: { label: '失败', className: 'tag-status-failed' },
  }
  return map[status] ?? map.pending
}

export function getRiskLevelColor(level) {
  const map = {
    high: '#ff4d4f',
    medium: '#faad14',
    low: '#00b578',
  }
  return map[level] ?? '#a8a8a8'
}

export function getRiskLevelTag(level, label) {
  const map = {
    high: { className: 'tag-risk-high', label: label ?? '高' },
    medium: { className: 'tag-risk-medium', label: label ?? '中' },
    low: { className: 'tag-risk-low', label: label ?? '低' },
  }
  return map[level] ?? map.medium
}

export function formatPercent(value, digits = 2) {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}${value.toFixed(digits)}%`
}

export function formatWeight(value) {
  return `${(value * 100).toFixed(0)}%`
}

export function getActionTheme(action = '') {
  if (action.includes('买入')) {
    return {
      type: 'buy',
      className: 'final-decision-card--buy',
      heroClass: 'final-hero--buy',
      tagClass: 'tag-up',
      accentColor: '#ff4d4f',
      progressColor: { from: '#e93030', to: '#ff7875' },
      label: '买入建议',
    }
  }
  if (action.includes('卖出')) {
    return {
      type: 'sell',
      className: 'final-decision-card--sell',
      heroClass: 'final-hero--sell',
      tagClass: 'tag-down',
      accentColor: '#00b578',
      progressColor: { from: '#00b578', to: '#52c41a' },
      label: '卖出建议',
    }
  }
  return {
    type: 'hold',
    className: 'final-decision-card--hold',
    heroClass: 'final-hero--hold',
    tagClass: 'tag-hold',
    accentColor: '#e6b84d',
    progressColor: { from: '#737373', to: '#faad14' },
    label: '持有建议',
  }
}
