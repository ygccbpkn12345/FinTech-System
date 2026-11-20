export const FLOW_STEPS = [
  {
    key: 'data',
    title: '数据获取',
    nodes: ['data_loading', 'start', 'initialized', 'data_fetch'],
  },
  {
    key: 'analysts',
    title: '五位分析师',
    nodes: [
      'market_analyst',
      'news_analyst',
      'fundamentals_analyst',
      'industry_analyst',
      'momentum_analyst',
      'analysts',
    ],
  },
  {
    key: 'router',
    title: '动态路由',
    nodes: ['router', 'routing'],
  },
  {
    key: 'manager',
    title: '经理决策',
    nodes: ['manager'],
  },
  {
    key: 'risk',
    title: '风险评估',
    nodes: ['risk_manager', 'risk'],
  },
  {
    key: 'decision',
    title: '最终决策',
    nodes: ['final_decision', 'decision', 'completed'],
  },
]

const NODE_LABELS = {
  data_loading: '数据获取',
  start: '任务初始化',
  initialized: '初始化完成',
  data_fetch: '数据获取',
  market_analyst: '市场分析师',
  news_analyst: '新闻分析师',
  fundamentals_analyst: '基本面分析师',
  industry_analyst: '行业分析师',
  momentum_analyst: '动量分析师',
  analysts: '五位分析师',
  router: '动态路由',
  routing: '动态路由',
  manager: '经理决策',
  risk_manager: '风险评估',
  risk: '风险评估',
  final_decision: '最终决策',
  decision: '最终决策',
  completed: '流程完成',
}

function normalizeNode(node) {
  if (!node) return ''
  return String(node).trim().toLowerCase().replace(/-/g, '_')
}

function matchStepIndex(node) {
  if (!node) return -1

  for (let i = 0; i < FLOW_STEPS.length; i += 1) {
    const step = FLOW_STEPS[i]
    if (step.nodes.some((n) => node === n || node.includes(n))) {
      return i
    }
  }

  if (node.includes('analyst')) return 1
  if (node.includes('router') || node.includes('routing')) return 2
  if (node.includes('manager') && !node.includes('risk')) return 3
  if (node.includes('risk')) return 4
  if (node.includes('decision')) return 5

  return -1
}

/**
 * 根据后端 status / currentNode / progress 解析当前活跃步骤索引
 */
export function resolveActiveStepIndex({
  currentNode,
  progress = 0,
  status = 'running',
  currentStep,
} = {}) {
  if (status === 'completed') {
    return FLOW_STEPS.length
  }

  const node = normalizeNode(currentNode)
  const fromNode = matchStepIndex(node)
  if (fromNode >= 0) {
    return fromNode
  }

  if (typeof currentStep === 'number' && currentStep >= 0) {
    const capped = Math.min(currentStep, FLOW_STEPS.length - 1)
    if (status === 'running') {
      return capped
    }
    return capped
  }

  if (typeof progress === 'number' && progress > 0) {
    if (progress >= 100 && status !== 'completed') {
      return FLOW_STEPS.length - 1
    }
    const idx = Math.floor((progress / 100) * FLOW_STEPS.length)
    return Math.min(Math.max(idx, 0), FLOW_STEPS.length - 1)
  }

  return 0
}

/**
 * 为 Ant Design Steps 构建逐步状态（wait / process / finish / error）
 */
export function buildStepStatuses(activeIndex, overallStatus = 'process') {
  return FLOW_STEPS.map((step, index) => {
    let stepStatus = 'wait'

    if (overallStatus === 'finish') {
      stepStatus = 'finish'
    } else if (overallStatus === 'error') {
      if (index < activeIndex) stepStatus = 'finish'
      else if (index === activeIndex) stepStatus = 'error'
      else stepStatus = 'wait'
    } else if (index < activeIndex) {
      stepStatus = 'finish'
    } else if (index === activeIndex) {
      stepStatus = 'process'
    } else {
      stepStatus = 'wait'
    }

    return { ...step, status: stepStatus }
  })
}

export function getNodeLabel(currentNode) {
  const node = normalizeNode(currentNode)
  if (!node) return '初始化'
  return NODE_LABELS[node] || currentNode
}

/**
 * 运行中 capped 进度：status=running 时最高 95%，仅 completed 时为 100%
 */
export function normalizeDisplayProgress({ progress = 0, status = 'running' } = {}) {
  if (status === 'completed') return 100
  const raw = Math.round(Number(progress) || 0)
  if (status === 'running') {
    return Math.min(raw >= 100 ? 95 : raw, 95)
  }
  return raw
}

/**
 * 顶部 Alert 第二行专用：简短阶段提示（不含英文节点名）
 */
export function formatAlertPhaseHint(currentNode, progress = 0, status = 'running') {
  const displayProgress = normalizeDisplayProgress({ progress, status })

  if (status === 'completed') {
    return '分析完成，进度 100%'
  }

  if (!currentNode && displayProgress <= 0) {
    return null
  }

  const label = getNodeLabel(currentNode)
  return `当前阶段：${label}，进度：${displayProgress}%`
}
