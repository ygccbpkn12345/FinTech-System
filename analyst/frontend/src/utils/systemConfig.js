/** 默认路径与模型配置（不含 API Key） */
export const DEFAULT_DATA_CONFIG = {
  dataDir: './data',
  dataCache: './data_cache',
  resultDir: './result',
}

export const DEFAULT_LLM_CONFIG = {
  deepThinkLlm: 'deepseek-reasoner',
  quickThinkLlm: 'deepseek-chat',
  baseUrl: 'https://api.deepseek.com',
  timeout: 120,
  maxRetries: 3,
}

export const FALLBACK_STOCK_CODES = ['000063', '000157', '000333', '000921', '000988']

/** 启动分析必需的数据类型 */
export const CORE_DATA_KEYS = [
  'technical_indicators',
  'news',
  'fundamentals',
  'result',
]

/** 不影响能否分析，仅影响反思/记忆能力 */
export const OPTIONAL_DATA_KEYS = ['train_memory_zip', 'test_memory_zip']

export const CORE_DATA_LABELS = {
  technical_indicators: '技术指标',
  news: '新闻',
  fundamentals: '基本面',
  result: 'result',
}

export const OPTIONAL_DATA_LABELS = {
  train_memory_zip: 'train 记忆库',
  test_memory_zip: 'test 记忆库',
}

export const QUICK_LLM_PRESETS = [
  'deepseek-chat',
  'deepseek-reasoner',
  'qwen-plus',
  'qwen-turbo',
  'gpt-4o-mini',
]

export const DEEP_LLM_PRESETS = [
  'deepseek-reasoner',
  'deepseek-chat',
  'qwen-max',
  'gpt-4o',
]

export const BASE_URL_PRESETS = [
  'https://api.deepseek.com',
  'https://dashscope.aliyuncs.com/compatible-mode/v1',
  'https://api.openai.com/v1',
]

export const DATA_TYPE_OPTIONS = [
  { value: 'technical_indicators', label: 'technical_indicators · 技术指标' },
  { value: 'news', label: 'news · 新闻数据' },
  { value: 'fundamentals', label: 'fundamentals · 公司基本面' },
  { value: 'result', label: 'result · 真实结果/价格变化' },
  { value: 'train_memory_zip', label: 'train_memory_zip · 训练记忆库' },
  { value: 'test_memory_zip', label: 'test_memory_zip · 测试记忆库' },
]

const CONFIG_CACHE_KEY = 'stock_llm_system_config_cache'

/** 仅内存保存，刷新页面即失效 */
let sessionApiKey = null

export function setSessionApiKey(value) {
  sessionApiKey = value?.trim() ? value.trim() : null
}

export function getSessionApiKey() {
  return sessionApiKey
}

export function clearSessionApiKey() {
  sessionApiKey = null
}

function pick(obj, ...keys) {
  if (!obj || typeof obj !== 'object') return undefined
  for (const key of keys) {
    if (obj[key] != null && obj[key] !== '') return obj[key]
  }
  return undefined
}

export function normalizeDataConfig(raw = {}) {
  return {
    dataDir: pick(raw, 'dataDir', 'data_dir') ?? DEFAULT_DATA_CONFIG.dataDir,
    dataCache: pick(raw, 'dataCache', 'data_cache') ?? DEFAULT_DATA_CONFIG.dataCache,
    resultDir: pick(raw, 'resultDir', 'result', 'result_dir') ?? DEFAULT_DATA_CONFIG.resultDir,
  }
}

export function normalizeLlmConfig(raw = {}) {
  return {
    deepThinkLlm:
      pick(raw, 'deepThinkLlm', 'deep_think_llm') ?? DEFAULT_LLM_CONFIG.deepThinkLlm,
    quickThinkLlm:
      pick(raw, 'quickThinkLlm', 'quick_think_llm') ?? DEFAULT_LLM_CONFIG.quickThinkLlm,
    baseUrl: pick(raw, 'baseUrl', 'base_url') ?? DEFAULT_LLM_CONFIG.baseUrl,
    timeout: Number(pick(raw, 'timeout') ?? DEFAULT_LLM_CONFIG.timeout),
    maxRetries: Number(pick(raw, 'maxRetries', 'max_retries') ?? DEFAULT_LLM_CONFIG.maxRetries),
    maskedApiKey: pick(raw, 'maskedApiKey', 'masked_api_key') ?? '',
  }
}

export function normalizeSystemConfig(raw = {}) {
  const payload = raw.config && typeof raw.config === 'object' ? raw.config : raw
  return {
    dataConfig: normalizeDataConfig(payload.dataConfig ?? payload.data_config ?? payload),
    llmConfig: normalizeLlmConfig(payload.llmConfig ?? payload.llm_config ?? payload),
    dataSource: pick(payload, 'dataSource', 'data_source') ?? 'local_file',
    crawlUrl:
      pick(payload, 'crawlUrl', 'crawl_url') ?? 'https://finance.eastmoney.com/',
    apiKeyConfigured: Boolean(pick(payload, 'apiKeyConfigured', 'api_key_configured')),
    tushareTokenConfigured: Boolean(
      pick(payload, 'tushareTokenConfigured', 'tushare_token_configured'),
    ),
    maskedTushareToken:
      pick(payload, 'maskedTushareToken', 'masked_tushare_token') ?? '',
  }
}

export function hasUsableTushareToken({ tushareToken, tushareTokenConfigured } = {}) {
  return Boolean(tushareToken?.trim() || tushareTokenConfigured)
}

export function cacheSystemConfig(config) {
  if (typeof window === 'undefined') return
  const normalized = normalizeSystemConfig(config)
  try {
    window.sessionStorage.setItem(
      CONFIG_CACHE_KEY,
      JSON.stringify(normalized),
    )
  } catch {
    /* ignore quota errors */
  }
}

export function loadCachedSystemConfig() {
  if (typeof window === 'undefined') {
    return {
      dataConfig: { ...DEFAULT_DATA_CONFIG },
      llmConfig: { ...DEFAULT_LLM_CONFIG, maskedApiKey: '' },
    }
  }
  try {
    const raw = window.sessionStorage.getItem(CONFIG_CACHE_KEY)
    if (!raw) {
      return {
        dataConfig: { ...DEFAULT_DATA_CONFIG },
        llmConfig: { ...DEFAULT_LLM_CONFIG, maskedApiKey: '' },
      }
    }
    return normalizeSystemConfig(JSON.parse(raw))
  } catch {
    return {
      dataConfig: { ...DEFAULT_DATA_CONFIG },
      llmConfig: { ...DEFAULT_LLM_CONFIG, maskedApiKey: '' },
    }
  }
}

/** 构建 analyze/start 请求体（不含空 apiKey） */
export function buildAnalyzeStartBody({
  stockCode,
  analysisDate,
  dataSource,
  llmConfig,
  dataConfig,
} = {}) {
  const body = {
    stockCode,
    analysisDate,
  }
  if (dataSource) body.dataSource = dataSource

  if (llmConfig && Object.keys(llmConfig).length > 0) body.llmConfig = { ...llmConfig }
  if (dataConfig && Object.keys(dataConfig).length > 0) body.dataConfig = { ...dataConfig }

  return body
}

/** 构建 POST /api/config 请求体；apiKey 仅在有新输入时附带 */
export function buildConfigSaveBody({ dataConfig, llmConfig, apiKeyInput }) {
  const body = {
    dataConfig: normalizeDataConfig(dataConfig),
    llmConfig: {
      deepThinkLlm: llmConfig.deepThinkLlm,
      quickThinkLlm: llmConfig.quickThinkLlm,
      baseUrl: llmConfig.baseUrl,
      timeout: Number(llmConfig.timeout),
      maxRetries: Number(llmConfig.maxRetries),
    },
  }

  if (apiKeyInput?.trim()) {
    body.llmConfig.apiKey = apiKeyInput.trim()
  }

  return body
}

export function normalizeDataStatusValue(value) {
  if (value === true || value === 'ready' || value === 'configured' || value === 'complete') {
    return 'ready'
  }
  if (value === 'partial' || value === 'partially') return 'partial'
  if (value === 'optional' || value === 'not_required') return 'optional'
  if (value === false || value === 'missing' || value === 'none' || value == null) return 'missing'
  return 'missing'
}

function hasExplicitFieldStatus(statusMap = {}) {
  return Object.keys(statusMap).length > 0
}

function resolveFieldStatus(value, { explicit, backendAvailable, optional = false }) {
  if (explicit && value != null && value !== '') {
    return normalizeDataStatusValue(value)
  }
  if (backendAvailable === true) {
    return optional ? 'optional' : 'ready'
  }
  if (optional) return 'optional'
  return normalizeDataStatusValue(value)
}

function collectMissingByKeys(statusMap = {}, keys = []) {
  return keys.filter((key) => {
    const val = statusMap[key] ?? statusMap[key.replace(/_([a-z])/g, (_, c) => c.toUpperCase())]
    return normalizeDataStatusValue(val) === 'missing'
  })
}

/** 根据核心数据是否齐全，计算能否分析 */
export function computeAnalyzable({ backendAvailable, statusMap = {}, symbol = '' } = {}) {
  const explicit = hasExplicitFieldStatus(statusMap)
  const coreMissing = collectMissingByKeys(statusMap, CORE_DATA_KEYS)

  if (typeof backendAvailable === 'boolean') {
    if (explicit && coreMissing.length > 0) return false
    return backendAvailable
  }

  if (!symbol || symbol === '--') return false
  if (!explicit) return true
  return coreMissing.length === 0
}

export function normalizeSymbolRecord(raw = {}) {
  const symbol = pick(raw, 'symbol', 'stockCode', 'stock_code', 'code') ?? '--'
  const statusMap =
    raw.status ?? raw.dataStatus ?? raw.data_status ?? raw.files ?? {}
  const explicit = hasExplicitFieldStatus(statusMap)
  const backendAvailable = pick(raw, 'available', 'analyzable', 'ready')
  const backendAvailableBool = typeof backendAvailable === 'boolean' ? backendAvailable : undefined

  const record = {
    symbol,
    name: pick(raw, 'name', 'stockName', 'stock_name') ?? '--',
    technicalIndicators: resolveFieldStatus(
      pick(raw, 'technicalIndicators', 'technical_indicators', 'technical') ??
        statusMap.technical_indicators ??
        statusMap.technicalIndicators,
      { explicit, backendAvailable: backendAvailableBool, optional: false },
    ),
    news: resolveFieldStatus(pick(raw, 'news') ?? statusMap.news, {
      explicit,
      backendAvailable: backendAvailableBool,
      optional: false,
    }),
    fundamentals: resolveFieldStatus(pick(raw, 'fundamentals') ?? statusMap.fundamentals, {
      explicit,
      backendAvailable: backendAvailableBool,
      optional: false,
    }),
    result: resolveFieldStatus(pick(raw, 'result') ?? statusMap.result, {
      explicit,
      backendAvailable: backendAvailableBool,
      optional: false,
    }),
    trainMemory: resolveFieldStatus(
      pick(raw, 'trainMemory', 'train_memory', 'train', 'train_memory_zip') ??
        statusMap.train_memory_zip ??
        statusMap.train_memory ??
        statusMap.train,
      { explicit, backendAvailable: backendAvailableBool, optional: true },
    ),
    testMemory: resolveFieldStatus(
      pick(raw, 'testMemory', 'test_memory', 'test', 'test_memory_zip') ??
        statusMap.test_memory_zip ??
        statusMap.test_memory ??
        statusMap.test,
      { explicit, backendAvailable: backendAvailableBool, optional: true },
    ),
    available: computeAnalyzable({
      backendAvailable: backendAvailableBool,
      statusMap: explicit ? statusMap : {},
      symbol,
    }),
  }

  return record
}

export function normalizeSymbolDataStatus(raw = {}, symbol = '') {
  const statusMap =
    raw.status ??
    raw.dataStatus ??
    raw.data_status ??
    raw.files ??
    {}

  const explicit = hasExplicitFieldStatus(statusMap)
  const coreMissing = Array.isArray(raw.missing)
    ? raw.missing.filter((k) => CORE_DATA_KEYS.includes(k))
    : collectMissingByKeys(statusMap, CORE_DATA_KEYS)
  const optionalMissing = collectMissingByKeys(statusMap, OPTIONAL_DATA_KEYS)

  const record = normalizeSymbolRecord({
    symbol: pick(raw, 'symbol', 'stockCode', 'stock_code') ?? symbol,
    name: pick(raw, 'name', 'stockName'),
    status: statusMap,
    available: typeof raw.available === 'boolean' ? raw.available : undefined,
  })

  const available = computeAnalyzable({
    backendAvailable: typeof raw.available === 'boolean' ? raw.available : record.available,
    statusMap: explicit ? statusMap : {},
    symbol: record.symbol,
  })

  return {
    ...record,
    available,
    missing: coreMissing,
    optionalMissing,
    raw,
  }
}

export function buildFallbackSymbols() {
  return FALLBACK_STOCK_CODES.map((symbol) => ({
    ...normalizeSymbolRecord({
      symbol,
      name: symbol,
      technicalIndicators: 'ready',
      news: 'ready',
      fundamentals: 'ready',
      result: 'ready',
      trainMemory: 'ready',
      testMemory: 'ready',
      available: true,
    }),
  }))
}

export function buildFallbackDataStatus(symbol) {
  const normalized = symbol?.trim?.() ?? ''
  const available = FALLBACK_STOCK_CODES.includes(normalized)
  return normalizeSymbolDataStatus(
    {
      symbol: normalized,
      available,
      missing: available
        ? []
        : ['technical_indicators', 'news', 'fundamentals', 'result'],
    },
    normalized,
  )
}
