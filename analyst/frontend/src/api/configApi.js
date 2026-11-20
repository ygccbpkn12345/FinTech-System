import client, { USE_MOCK, normalizeStockCodeInput } from '@/api/analysisApi'
import {
  buildFallbackDataStatus,
  buildFallbackSymbols,
  cacheSystemConfig,
  normalizeSymbolDataStatus,
  normalizeSymbolRecord,
  normalizeSystemConfig,
} from '@/utils/systemConfig'

const delay = (ms = 200) => new Promise((resolve) => setTimeout(resolve, ms))

function unwrapList(raw) {
  if (Array.isArray(raw)) return raw
  if (Array.isArray(raw?.symbols)) return raw.symbols
  if (Array.isArray(raw?.items)) return raw.items
  if (Array.isArray(raw?.data)) return raw.data
  return []
}

/**
 * GET /api/config
 */
export async function fetchSystemConfig() {
  if (USE_MOCK) {
    await delay()
    const config = normalizeSystemConfig({
      dataConfig: {},
      llmConfig: { maskedApiKey: 'sk-****demo' },
    })
    cacheSystemConfig(config)
    return config
  }

  try {
    const res = await client.get('/api/config')
    const config = normalizeSystemConfig(res)
    cacheSystemConfig(config)
    return config
  } catch (error) {
    throw error
  }
}

/**
 * POST /api/config
 */
export async function saveSystemConfig(body) {
  if (USE_MOCK) {
    await delay()
    const config = normalizeSystemConfig(body)
    cacheSystemConfig(config)
    return { ok: true, message: 'Mock 配置已保存', config }
  }

  const res = await client.post('/api/config', body)
  const config = normalizeSystemConfig(res?.config ?? res ?? body)
  cacheSystemConfig(config)
  return config
}

/**
 * GET /api/symbols
 */
export async function fetchSymbolList() {
  if (USE_MOCK) {
    await delay()
    return buildFallbackSymbols()
  }

  try {
    const res = await client.get('/api/symbols')
    const list = unwrapList(res).map((item) => normalizeSymbolRecord(item))
    return list.length ? list : buildFallbackSymbols()
  } catch {
    return buildFallbackSymbols()
  }
}

/**
 * GET /api/symbols/{symbol}/data-status
 */
export async function fetchSymbolDataStatus(symbol) {
  const code = String(symbol ?? '').trim()
  if (!code) {
    return normalizeSymbolDataStatus({ symbol: '', available: false, missing: [] })
  }

  if (USE_MOCK) {
    await delay()
    return buildFallbackDataStatus(code)
  }

  try {
    const res = await client.get(`/api/symbols/${encodeURIComponent(code)}/data-status`)
    return normalizeSymbolDataStatus(res, code)
  } catch {
    return buildFallbackDataStatus(code)
  }
}

export async function fetchSymbolAvailableDates(symbol) {
  const code = normalizeStockCodeInput(symbol)
  if (!code) return []
  if (USE_MOCK) return ['2024-01-03', '2026-06-10']
  const res = await client.get(`/api/symbols/${encodeURIComponent(code)}/available-dates`)
  return Array.isArray(res?.dates) ? res.dates : []
}

/**
 * POST /api/data/upload (multipart)
 */
export async function uploadStockData({ symbol, name, dataType, file }) {
  if (!file) throw new Error('请选择要上传的文件')
  if (!symbol?.trim()) throw new Error('请输入股票代码')
  if (!dataType) throw new Error('请选择数据类型')

  if (USE_MOCK) {
    await delay(400)
    return {
      ok: true,
      message: `Mock 已接收 ${symbol} · ${dataType}`,
      symbol: symbol.trim(),
      dataType,
    }
  }

  const formData = new FormData()
  formData.append('symbol', symbol.trim())
  if (name?.trim()) formData.append('name', name.trim())
  formData.append('dataType', dataType)
  formData.append('file', file)

  return client.post('/api/data/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export async function checkStockAnalyzable(code) {
  const symbol = normalizeStockCodeInput(code)
  if (!symbol) {
    return { available: false, symbol: '', missing: [], message: '请输入股票代码' }
  }
  const status = await fetchSymbolDataStatus(symbol)
  return {
    ...status,
    symbol,
    message: status.available
      ? `${symbol} 数据就绪，可启动分析`
      : `缺失数据：${(status.missing ?? []).join('、') || '未知'}`,
  }
}

export async function loadAvailableSymbols() {
  const list = await fetchSymbolList()
  const available = list.filter((item) => item.available)
  if (available.length) return available
  return list.filter((item) =>
    ['000063', '000157', '000333', '000921', '000988'].includes(item.symbol),
  )
}
