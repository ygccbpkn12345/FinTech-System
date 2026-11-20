export function buildCrawlDashboardState(result = {}, fallbackSymbol = '') {
  const state = {
    stockCode: result.symbol || fallbackSymbol,
    analysisDate: result.latestDate || null,
    dataStatus: result.dataStatus || null,
    dataFetched: true,
  }
  if (result.status) state.fetchStatus = result.status
  if (Array.isArray(result.failedModules)) state.failedModules = result.failedModules
  return state
}

export function buildCrawlRequest({
  symbol,
  dataSource = 'baostock',
  crawlUrl = 'https://finance.eastmoney.com/',
  tushareToken = '',
  startDate,
  endDate,
} = {}) {
  if (!startDate || !endDate) throw new Error('请选择爬取开始日期和结束日期')
  if (startDate > endDate) throw new Error('爬取开始日期不能晚于结束日期')
  return { symbol, dataSource, crawlUrl, tushareToken, startDate, endDate }
}
