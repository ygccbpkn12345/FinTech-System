import axios from 'axios'
import { analysisMock } from '@/mock/analysisMock'
import { enrichWorkbenchData, normalizeDecisionTree, normalizePreReflection, normalizeRiskListItems } from '@/utils/workbenchDataUtils'
import { normalizeReflectionPayload } from '@/utils/reflectionUtils'
import { cleanDisplayText, cleanStringList } from '@/utils/displayTextUtils'
import { buildAnalyzeStartBody, FALLBACK_STOCK_CODES } from '@/utils/systemConfig'
import { subscribeAnalysisEvents } from './analysisEvents'
import { API_BASE_URL } from './apiBaseUrl.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

const ANALYSIS_STEPS = [
  { key: 'data_fetch', label: '数据获取' },
  { key: 'analysts', label: '五位分析师' },
  { key: 'routing', label: '动态路由' },
  { key: 'manager', label: '经理决策' },
  { key: 'risk', label: '风险评估' },
  { key: 'decision', label: '最终决策' },
  { key: 'reflection', label: '反思更新' },
]

const MOCK_HISTORY = [
  {
    id: 'hist_001',
    taskId: 'task_mock_001',
    stockCode: '600519.SH',
    stockName: '贵州茅台',
    analysisDate: '2026-06-10',
    action: '谨慎买入',
    confidence: 0.71,
    status: 'completed',
    createdAt: '2026-06-10T14:32:00+08:00',
  },
  {
    id: 'hist_002',
    taskId: 'task_mock_002',
    stockCode: '300750.SZ',
    stockName: '宁德时代',
    analysisDate: '2026-06-08',
    action: '持有',
    confidence: 0.58,
    status: 'completed',
    createdAt: '2026-06-08T10:15:00+08:00',
  },
  {
    id: 'hist_003',
    taskId: 'task_mock_003',
    stockCode: '000858.SZ',
    stockName: '五粮液',
    analysisDate: '2026-06-05',
    action: '谨慎买入',
    confidence: 0.65,
    status: 'completed',
    createdAt: '2026-06-05T16:48:00+08:00',
  },
]

/** @type {Map<string, { taskId: string, params: object, createdAt: number }>} */
const mockTaskStore = new Map()

const STEP_DURATION_MS = 400
const DEFAULT_POLL_INTERVAL_MS = USE_MOCK ? 400 : 3000
/** mock 30s；真实后端单次请求超时 5 分钟（分析约 70–100 秒，留足余量） */
const REQUEST_TIMEOUT_MS = USE_MOCK ? 30000 : 5 * 60 * 1000

/** 后端不可用时的默认股票列表（6 位代码） */
export const SUPPORTED_STOCK_CODES = FALLBACK_STOCK_CODES

export const SUPPORTED_STOCK_HINT = '上传数据请前往系统配置。'

export const ANALYSIS_RUNNING_MSG =
  '真实多智能体分析中，正在调用市场、新闻、行业、公司、动量分析师，并进入路由、经理、风控、终局决策与反思阶段。真实分析约需 1–2 分钟，请耐心等待。'

export function normalizeStockCodeInput(code = '') {
  return code.trim().toUpperCase().replace(/\.(SH|SZ)$/, '')
}

/** @deprecated 请优先使用 configApi.checkStockAnalyzable */
export function isSupportedStock(code) {
  if (USE_MOCK) return Boolean(code?.trim())
  return FALLBACK_STOCK_CODES.includes(normalizeStockCodeInput(code))
}

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
})

const BACKEND_UNAVAILABLE_MSG =
  '后端服务不可用，请检查 FastAPI 是否启动或 SSH 隧道是否建立。'

function formatApiError(error) {
  if (!error.response) {
    if (error.code === 'ECONNABORTED') {
      return '请求超时，请检查网络或 SSH 隧道是否正常'
    }
    return BACKEND_UNAVAILABLE_MSG
  }

  const detail = error.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
  }

  return error.response?.data?.message || error.message || '请求失败'
}

client.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(new Error(formatApiError(error))),
)

const delay = (ms = 300) => new Promise((resolve) => setTimeout(resolve, ms))

function assertNoApiError(payload, fallbackMsg = '分析任务失败') {
  if (!payload || payload.error !== true) return
  throw new Error(extractTaskErrorMessage(payload, fallbackMsg))
}

/** 从任务状态/错误响应中提取可读错误信息 */
export function extractTaskErrorMessage(payload, fallback = '分析任务失败') {
  if (payload == null) return fallback
  if (payload instanceof Error) return payload.message?.trim() || fallback
  if (typeof payload === 'string') return payload.trim() || fallback

  const candidates = [
    payload.message,
    payload.errorMessage,
    payload.error_message,
    payload.detail,
    payload.reason,
    payload.failReason,
    payload.fail_reason,
    typeof payload.error === 'string' ? payload.error : null,
    payload.data?.message,
    payload.data?.detail,
    payload.result?.message,
  ]

  for (const item of candidates) {
    if (item == null || item === '') continue
    if (typeof item === 'string') return item.trim()
    if (Array.isArray(item)) {
      const text = item
        .map((entry) => (typeof entry === 'string' ? entry : entry?.msg || JSON.stringify(entry)))
        .filter(Boolean)
        .join('; ')
      if (text) return text
    }
    if (typeof item === 'object' && item.msg) return String(item.msg)
  }

  return fallback
}

function appendAnalysisFailureHint(message, status = {}) {
  const text = message || '分析任务失败'
  const node = String(status.currentNode ?? status.current_node ?? '').toLowerCase()

  if (/connection|connect|timeout|api.?key|unauthorized|401|403/i.test(text)) {
    return `${text}（${node.includes('reflect') || node.includes('反思') ? '反思阶段' : '分析过程'} LLM 连接失败，请检查系统配置中的 base_url 与 api_key）`
  }

  if (node.includes('reflect') && text === '分析任务失败') {
    return '反思阶段执行失败，请查看后端日志或检查 LLM 配置'
  }

  return text
}

async function resolveTaskFailureMessage(taskId, status = {}) {
  let message = extractTaskErrorMessage(status)

  if ((!message || message === '分析任务失败') && taskId && !USE_MOCK) {
    try {
      const res = await axios.get(`${API_BASE_URL}/api/analyze/result/${taskId}`, {
        timeout: REQUEST_TIMEOUT_MS,
        validateStatus: () => true,
      })
      message = extractTaskErrorMessage(res.data, message)
    } catch (err) {
      message = extractTaskErrorMessage(err, message)
    }
  }

  return appendAnalysisFailureHint(message, status)
}

function normalizeTaskStatus(raw = {}) {
  const normalizedStatus = String(raw.status ?? raw.state ?? 'running').toLowerCase()

  return {
    ...raw,
    status: normalizedStatus === 'failure' ? 'failed' : normalizedStatus,
  }
}

function isTaskFailed(status = {}) {
  const normalized = normalizeTaskStatus(status)
  return normalized.status === 'failed' || status.error === true
}

function generateTaskId() {
  return `task_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function buildMockStatus(task) {
  const elapsed = Date.now() - task.createdAt
  const currentStep = Math.min(
    Math.floor(elapsed / STEP_DURATION_MS),
    ANALYSIS_STEPS.length - 1,
  )
  const isCompleted =
    currentStep >= ANALYSIS_STEPS.length - 1 &&
    elapsed >= STEP_DURATION_MS * ANALYSIS_STEPS.length

  return {
    taskId: task.taskId,
    status: isCompleted ? 'completed' : 'running',
    currentStep,
    totalSteps: ANALYSIS_STEPS.length,
    steps: ANALYSIS_STEPS.map((step, index) => ({
      ...step,
      status:
        index < currentStep
          ? 'finish'
          : index === currentStep && !isCompleted
            ? 'process'
            : isCompleted
              ? 'finish'
              : 'wait',
    })),
    progress: isCompleted
      ? 100
      : Math.round(((currentStep + 1) / ANALYSIS_STEPS.length) * 100),
    params: task.params,
  }
}

async function mockStartAnalysis(params) {
  await delay(200)
  const taskId = generateTaskId()
  mockTaskStore.set(taskId, {
    taskId,
    params,
    createdAt: Date.now(),
  })
  return { taskId, status: 'running', message: '分析任务已创建' }
}

async function mockGetAnalysisStatus(taskId) {
  await delay(150)
  const task = mockTaskStore.get(taskId)
  if (!task) {
    throw new Error(`任务不存在: ${taskId}`)
  }
  return buildMockStatus(task)
}

async function mockGetAnalysisResult(taskId) {
  await delay(300)
  const task = mockTaskStore.get(taskId)
  if (!task) {
    throw new Error(`任务不存在: ${taskId}`)
  }
  return {
    taskId,
    ...analysisMock,
    params: task.params,
  }
}

async function mockGetHistoryList() {
  await delay(200)
  return { items: MOCK_HISTORY, total: MOCK_HISTORY.length }
}

function unwrapResult(raw) {
  if (!raw || typeof raw !== 'object') return {}
  if (raw.result && typeof raw.result === 'object' && !Array.isArray(raw.result)) {
    return raw.result
  }
  if (raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)) {
    return raw.data
  }
  return raw
}

function pickNum(...values) {
  for (const value of values) {
    if (typeof value === 'number' && !Number.isNaN(value)) return value
    if (typeof value === 'string' && value !== '' && !Number.isNaN(Number(value))) {
      return Number(value)
    }
  }
  return 0
}

function pickStr(...values) {
  for (const value of values) {
    if (value != null && value !== '') return String(value)
  }
  return '--'
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

const DEFAULT_CHART_DATA = {
  dates: asArray(analysisMock.marketChart?.dates),
  prices: asArray(analysisMock.marketChart?.prices),
  volumes: asArray(analysisMock.marketChart?.volumes),
}

function normalizeStock(raw, params = {}) {
  const src = asObject(
    raw?.stock ??
      raw?.stockInfo ??
      raw?.stock_info ??
      (raw?.code || raw?.stockCode || raw?.symbol ? raw : null),
  )

  const volumeRaw = src.volume ?? src.volumeLabel ?? src.volume_label
  const marketCapRaw =
    src.marketCapLabel ?? src.market_cap_label ?? src.marketCap ?? src.market_cap

  return {
    code: pickStr(src.code, src.stockCode, src.stock_code, src.symbol, params.stockCode, '--'),
    name: pickStr(src.name, src.stockName, src.stock_name, '--'),
    industry: pickStr(src.industry, '--'),
    currentPrice: pickNum(src.currentPrice, src.current_price, src.price, 0),
    change: pickNum(src.change, 0),
    changePercent: pickNum(
      src.changePercent,
      src.change_percent,
      src.changeRate,
      src.change_rate,
      0,
    ),
    high: pickNum(src.high, 0),
    low: pickNum(src.low, 0),
    volume: pickStr(volumeRaw, '--'),
    volatility: pickNum(src.volatility, 0),
    pe: pickNum(src.pe, 0),
    marketCap: pickStr(marketCapRaw, '--'),
    analysisDate: pickStr(
      src.analysisDate,
      src.analysis_date,
      params.analysisDate,
      '--',
    ),
    volumeLabel: pickStr(src.volumeLabel, src.volume_label, volumeRaw, '--'),
    marketCapLabel: pickStr(src.marketCapLabel, src.market_cap_label, marketCapRaw, '--'),
    amplitude: pickNum(src.amplitude, 0),
    open: pickNum(src.open, 0),
    prevClose: pickNum(src.prevClose, src.prev_close, 0),
    turnoverLabel: pickStr(src.turnoverLabel, src.turnover_label, '--'),
    exchange: pickStr(src.exchange, '--'),
  }
}

function normalizeChartData(raw) {
  const src = asObject(
    raw?.chartData ??
      raw?.chart_data ??
      raw?.marketChart ??
      raw?.market_chart ??
      raw?.chart ??
      raw?.stock?.chart ??
      raw?.stock?.marketChart,
  )

  const chart = {
    dates: asArray(src.dates),
    prices: asArray(src.prices),
    volumes: asArray(src.volumes),
  }

  if (!chart.dates.length && !chart.prices.length) {
    return { ...DEFAULT_CHART_DATA }
  }

  return chart
}

function normalizeAnalysts(raw) {
  return asArray(raw?.analysts).map((item, index) => ({
    id: pickStr(item?.id, item?.analystId, item?.analyst_id, `analyst_${index}`),
    name: pickStr(item?.name, item?.analystName, item?.analyst_name, '--'),
    role: pickStr(item?.role, '--'),
    status: pickStr(item?.status, 'completed'),
    signal: item?.signal ?? 'neutral',
    confidence: pickNum(item?.confidence, 0),
    summary: cleanDisplayText(item?.summary ?? ''),
    report: cleanDisplayText(item?.report ?? ''),
    dataUsed: asArray(item?.dataUsed ?? item?.data_used),
  }))
}

function normalizeRouterWeights(raw) {
  const list = asArray(
    raw?.routerWeights ??
      raw?.router_weights ??
      raw?.routingWeights ??
      raw?.routing_weights,
  )
  return list.map((item, index) => ({
    analystId: pickStr(item?.analystId, item?.analyst_id, `analyst_${index}`),
    analystName: pickStr(item?.analystName, item?.analyst_name, '--'),
    confidenceWeight: pickNum(item?.confidenceWeight, item?.confidence_weight, 0),
    historicalWeight: pickNum(item?.historicalWeight, item?.historical_weight, 0),
    finalWeight: pickNum(item?.finalWeight, item?.final_weight, 0),
    adjustmentReason: cleanDisplayText(item?.adjustmentReason ?? item?.adjustment_reason ?? ''),
  }))
}

function normalizeManagerDecision(raw) {
  const mgr = asObject(raw?.managerDecision ?? raw?.manager_decision)
  const rawTree = asArray(
    mgr.tree ??
      mgr.decisionTree ??
      mgr.decision_tree ??
      mgr.branches ??
      mgr.nodes ??
      raw?.managerDecisionTree ??
      raw?.manager_decision_tree,
  )
  const tree = normalizeDecisionTree(rawTree)
  const preReflection = normalizePreReflection(
    mgr.preReflection ??
      mgr.pre_reflection ??
      raw?.managerPreReflection ??
      raw?.manager_pre_reflection,
  )

  return {
    tree,
    preReflection,
    checks: preReflection.checks,
    summary: preReflection.summary ?? '',
    ...mgr,
  }
}

function normalizeRiskList(raw) {
  return normalizeRiskListItems(raw)
}

function normalizeFinalDecision(raw) {
  const src = asObject(raw?.finalDecision ?? raw?.final_decision)
  const target = asObject(src.targetPrice ?? src.target_price)
  return {
    action: pickStr(src.action, '--'),
    actionEn: pickStr(src.actionEn, src.action_en, '--'),
    position: pickStr(src.position, '--'),
    positionRange: pickStr(src.positionRange, src.position_range, '--'),
    confidence: pickNum(src.confidence, 0),
    compositeScore: pickNum(src.compositeScore, src.composite_score, 0),
    targetPrice: {
      low: pickNum(target.low, 0),
      high: pickNum(target.high, 0),
      horizon: pickStr(target.horizon, '--'),
    },
    stopLoss: pickNum(src.stopLoss, src.stop_loss, 0),
    stopLossPercent: pickNum(src.stopLossPercent, src.stop_loss_percent, 0),
    coreReason: cleanDisplayText(src.coreReason ?? src.core_reason ?? ''),
    keyRisks: cleanStringList(asArray(src.keyRisks ?? src.key_risks)),
    dissentSummary: cleanDisplayText(src.dissentSummary ?? src.dissent_summary ?? ''),
  }
}

function normalizeReflection(raw) {
  let src = raw?.reflection ?? raw?.reflectionReport ?? raw?.reflection_report
  if (typeof src === 'string') {
    src = { summary: src, metaReflection: src }
  }
  const rawObj = asObject(src)
  return normalizeReflectionPayload({
    ...rawObj,
    _source: rawObj,
  })
}

/**
 * 将后端 result 统一转换为前端可用结构（保证字段完整，避免渲染崩溃）
 */
export function normalizeAnalysisResult(raw = {}, options = {}) {
  const { _fallback = false } = options
  try {
    const payload = unwrapResult(raw)
    const params = asObject(payload.params ?? raw.params)
    const stock = normalizeStock(payload, params)
    const chartData = normalizeChartData(payload)
    const analysts = normalizeAnalysts(payload)
    const routerWeights = normalizeRouterWeights(payload)
    const managerDecision = normalizeManagerDecision(payload)
    const riskItems = normalizeRiskList(payload)
    const finalDecision = normalizeFinalDecision(payload)
    const reflection = normalizeReflection(payload)

    const normalized = {
      taskId: payload.taskId ?? payload.task_id ?? raw.taskId ?? null,
      analysisMode: payload.analysisMode ?? null,
      params,
      stock,
      chartData,
      analysts,
      routerWeights,
      managerDecision,
      riskAssessment: { items: riskItems },
      finalDecision,
      reflection,
      stockInfo: stock,
      marketChart: chartData,
      routingWeights: routerWeights,
      managerDecisionTree: managerDecision.tree,
      managerPreReflection: managerDecision.preReflection,
      reflectionReport: reflection,
      riskList: riskItems,
    }

    const workbench = enrichWorkbenchData(normalized)
    normalized.managerDecisionTree = workbench.decisionTree
    normalized.managerDecision = {
      ...managerDecision,
      tree: workbench.decisionTree,
      preReflection: workbench.preReflection,
    }
    normalized.managerPreReflection = workbench.preReflection
    normalized.riskList = workbench.riskAssessment
    normalized.riskAssessment = { items: workbench.riskAssessment }
    normalized.reflection = workbench.reflection
    normalized.reflectionReport = workbench.reflection
    normalized.workbench = workbench

    return normalized
  } catch (error) {
    if (_fallback) throw error
    console.warn('normalizeAnalysisResult failed, fallback to mock:', error)
    return normalizeAnalysisResult(
      { ...analysisMock, analysisMode: 'mock', taskId: raw?.taskId, params: raw?.params },
      { _fallback: true },
    )
  }
}

async function fetchAndNormalizeResult(fetcher) {
  const raw = await fetcher()
  assertNoApiError(raw, '分析结果返回错误')
  return normalizeAnalysisResult(raw)
}

/**
 * 启动分析任务
 * POST /api/analyze/start
 * @param {{ stockCode: string, analysisDate: string, llmConfig?: object, dataConfig?: object }} params
 */
export async function startAnalysis(params) {
  if (USE_MOCK) {
    return mockStartAnalysis(params)
  }
  const body = buildAnalyzeStartBody(params)
  const res = await client.post('/api/analyze/start', body)
  assertNoApiError(res, '启动分析失败')
  return res
}

/**
 * 查询分析任务进度
 * GET /api/analyze/status/{taskId}
 * @param {string} taskId
 * @returns {Promise<{
 *   taskId: string,
 *   status: 'running' | 'completed' | 'failed',
 *   currentStep: number,
 *   totalSteps: number,
 *   progress: number,
 *   steps?: Array,
 *   params?: object,
 *   message?: string
 * }>}
 */
export async function getAnalysisStatus(taskId) {
  if (USE_MOCK) {
    return mockGetAnalysisStatus(taskId)
  }
  const status = normalizeTaskStatus(await client.get(`/api/analyze/status/${taskId}`))
  assertNoApiError(status, '查询分析状态失败')
  return status
}

/**
 * 获取分析结果（任务完成后调用）
 * GET /api/analyze/result/{taskId}
 * @param {string} taskId
 */
export async function getAnalysisResult(taskId) {
  if (USE_MOCK) {
    return fetchAndNormalizeResult(() => mockGetAnalysisResult(taskId))
  }
  return fetchAndNormalizeResult(() => client.get(`/api/analyze/result/${taskId}`))
}

export async function getReflectionStatus(taskId) {
  if (USE_MOCK) {
    return { taskId, status: 'completed', reflection: analysisMock.reflection }
  }
  return client.get(`/api/analyze/reflection/${taskId}`)
}

/**
 * 获取历史分析记录列表
 * GET /api/analysis/history
 */
export async function getHistoryList() {
  if (USE_MOCK) {
    return mockGetHistoryList()
  }
  return client.get('/api/analysis/history')
}

/**
 * 系统健康检查
 * GET /api/health
 */
export async function checkHealth() {
  if (USE_MOCK) {
    await delay(200)
    return { status: 'ok', mode: 'mock', message: 'Mock 模式运行中' }
  }
  const res = await client.get('/api/health')
  assertNoApiError(res, '健康检查失败')
  return res
}

/**
 * 轮询任务状态直至完成或失败
 * @param {string} taskId
 * @param {{
 *   onStatus?: (status: object) => void,
 *   interval?: number,
 *   signal?: AbortSignal
 * }} [options]
 */
export async function pollAnalysisUntilComplete(taskId, options = {}) {
  const { onStatus, interval = DEFAULT_POLL_INTERVAL_MS, signal } = options

  while (true) {
    if (signal?.aborted) {
      throw new Error('分析已取消')
    }

    const status = await getAnalysisStatus(taskId)
    onStatus?.(status)

    if (status.status === 'completed') {
      return status
    }
    if (isTaskFailed(status)) {
      throw new Error(await resolveTaskFailureMessage(taskId, status))
    }

    await delay(interval)
  }
}

/**
 * 完整分析工作流：start → poll status → get result
 *
 * 仅在任务 status 为 completed 后请求 result。
 *
 * @param {{ stockCode: string, analysisDate: string }} params
 * @param {{
 *   onStatus?: (status: object) => void,
 *   onResult?: (result: object, meta: { partial: boolean }) => void,
 *   interval?: number,
 *   signal?: AbortSignal
 * }} [options]
 */
export async function runAnalysisWorkflow(params, options = {}) {
  const {
    onStatus,
    onResult,
    onModuleEvent,
    onStreamState,
    interval = DEFAULT_POLL_INTERVAL_MS,
    signal,
  } = options

  const { taskId } = await startAnalysis(params)
  let closeEvents = () => {}
  let resolveTerminal
  const terminalEvent = new Promise((resolve) => {
    resolveTerminal = resolve
  })

  if (!USE_MOCK && globalThis.EventSource) {
    closeEvents = subscribeAnalysisEvents(
      taskId,
      {
        onOpen: () => onStreamState?.('connected'),
        onConnectionError: () => onStreamState?.('reconnecting'),
        onModule: onModuleEvent,
        onCompleted: (event) => resolveTerminal(event),
        onFailed: (event) => resolveTerminal(event),
        onProtocolError: () => onStreamState?.('reconnecting'),
      },
      { baseUrl: API_BASE_URL },
    )
    onStreamState?.('connecting')
  }

  try {
    while (true) {
      if (signal?.aborted) {
        throw new Error('分析已取消')
      }

      const status = await getAnalysisStatus(taskId)
      onStatus?.(status)

      if (status.status === 'completed') {
        try {
          const result = { ...(await getAnalysisResult(taskId)), taskId }
          onResult?.(result, { partial: false })
          return { taskId, status, result }
        } catch (err) {
          throw new Error(extractTaskErrorMessage(err, '获取分析结果失败'))
        }
      }

      if (isTaskFailed(status)) {
        throw new Error(await resolveTaskFailureMessage(taskId, status))
      }

      const terminal = await Promise.race([
        delay(interval).then(() => null),
        terminalEvent,
      ])
      if (terminal?.type === 'failed') {
        throw new Error(terminal.message || '分析任务失败')
      }
      if (terminal?.type === 'completed') {
        const result = { ...(await getAnalysisResult(taskId)), taskId }
        onResult?.(result, { partial: false })
        return { taskId, status: { ...status, status: 'completed', progress: 100 }, result }
      }
    }
  } finally {
    closeEvents()
  }
}

export {
  API_BASE_URL,
  USE_MOCK,
  ANALYSIS_STEPS,
  DEFAULT_POLL_INTERVAL_MS,
  REQUEST_TIMEOUT_MS,
  BACKEND_UNAVAILABLE_MSG,
}
export default client
