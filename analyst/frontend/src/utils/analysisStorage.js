import { USE_MOCK } from '@/api/analysisApi'

const HISTORY_KEY = 'stock_llm_analysis_history'
const LATEST_KEY = 'stock_llm_latest_analysis'
const PENDING_LOAD_KEY = 'stock_llm_pending_load'

function computeRiskScore(riskAssessment = []) {
  if (!riskAssessment.length) return 0
  const map = { high: 82, medium: 55, low: 28 }
  return Math.round(
    riskAssessment.reduce((s, r) => s + (map[r.level] ?? 50), 0) / riskAssessment.length,
  )
}

function safeParse(json, fallback) {
  try {
    return JSON.parse(json) ?? fallback
  } catch {
    return fallback
  }
}

export function loadHistory() {
  if (typeof window === 'undefined') return []
  return safeParse(localStorage.getItem(HISTORY_KEY), [])
}

export function saveAnalysisToHistory(result, meta = {}) {
  if (!result || typeof window === 'undefined') return null

  const riskItems = result.riskList ?? result.riskAssessment?.items ?? []
  const record = {
    id: `${Date.now()}_${result.taskId || 'local'}`,
    stockCode: result.stock?.code ?? meta.stockCode ?? '--',
    stockName: result.stock?.name ?? '--',
    analysisDate:
      result.stock?.analysisDate ?? meta.analysisDate ?? result.params?.analysisDate ?? '--',
    action: result.finalDecision?.action ?? '--',
    position: result.finalDecision?.position ?? '--',
    confidence: result.finalDecision?.confidence ?? 0,
    riskScore: computeRiskScore(riskItems),
    completedAt: new Date().toISOString(),
    source: meta.source ?? (USE_MOCK ? 'mock' : 'real_model'),
    snapshot: result,
  }

  const records = loadHistory()
  records.unshift(record)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(records.slice(0, 100)))

  localStorage.setItem(
    LATEST_KEY,
    JSON.stringify({
      result,
      savedAt: record.completedAt,
      source: record.source,
    }),
  )

  return record
}

export function clearHistory() {
  if (typeof window === 'undefined') return
  localStorage.removeItem(HISTORY_KEY)
}

export function loadLatestAnalysis() {
  if (typeof window === 'undefined') return null
  const data = safeParse(localStorage.getItem(LATEST_KEY), null)
  return data?.result ?? null
}

export function loadLatestMeta() {
  if (typeof window === 'undefined') return null
  return safeParse(localStorage.getItem(LATEST_KEY), null)
}

export function updateStoredReflection(taskId, reflection, lifecycle) {
  if (typeof window === 'undefined' || !taskId) return
  const latest = safeParse(localStorage.getItem(LATEST_KEY), null)
  if (latest?.result?.taskId === taskId) {
    latest.result = { ...latest.result, reflection, reflectionStatus: lifecycle }
    localStorage.setItem(LATEST_KEY, JSON.stringify(latest))
  }
  const records = loadHistory().map((record) => {
    if (record.snapshot?.taskId !== taskId) return record
    return {
      ...record,
      snapshot: { ...record.snapshot, reflection, reflectionStatus: lifecycle },
    }
  })
  localStorage.setItem(HISTORY_KEY, JSON.stringify(records))
}

export function loadLatestCompletedReflection() {
  return loadHistory().find((record) => {
    const value = record.snapshot?.reflection
    return value && Object.keys(value).length > 0
  }) ?? null
}

export function queueLoadRecord(recordId) {
  if (typeof window === 'undefined') return false
  const record = loadHistory().find((r) => r.id === recordId)
  if (!record?.snapshot) return false
  localStorage.setItem(PENDING_LOAD_KEY, JSON.stringify(record))
  return true
}

export function consumePendingLoad() {
  if (typeof window === 'undefined') return null
  const raw = localStorage.getItem(PENDING_LOAD_KEY)
  if (!raw) return null
  localStorage.removeItem(PENDING_LOAD_KEY)
  return safeParse(raw, null)
}

export function getHistoryRecordById(id) {
  return loadHistory().find((r) => r.id === id) ?? null
}
