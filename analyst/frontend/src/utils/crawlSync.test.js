import assert from 'node:assert/strict'
import test from 'node:test'

import { buildCrawlDashboardState, buildCrawlRequest } from './crawlSync.js'

test('crawl result selects fetched symbol and latest date for dashboard', () => {
  assert.deepEqual(
    buildCrawlDashboardState(
      { symbol: '000063', latestDate: '2026-08-10', dataStatus: { available: true } },
      'fallback',
    ),
    {
      stockCode: '000063',
      analysisDate: '2026-08-10',
      dataStatus: { available: true },
      dataFetched: true,
    },
  )
})

test('crawl request includes manually selected ISO date range', () => {
  assert.deepEqual(
    buildCrawlRequest({
      symbol: '600519',
      dataSource: 'baostock',
      crawlUrl: 'https://finance.eastmoney.com/',
      startDate: '2026-01-01',
      endDate: '2026-08-10',
    }),
    {
      symbol: '600519',
      dataSource: 'baostock',
      crawlUrl: 'https://finance.eastmoney.com/',
      tushareToken: '',
      startDate: '2026-01-01',
      endDate: '2026-08-10',
    },
  )
})

test('crawl request rejects a reversed date range', () => {
  assert.throws(
    () => buildCrawlRequest({ symbol: '600519', startDate: '2026-08-10', endDate: '2026-01-01' }),
    /开始日期不能晚于结束日期/,
  )
})

test('partial crawl result preserves failed modules for warning and status refresh', () => {
  assert.deepEqual(
    buildCrawlDashboardState(
      {
        status: 'partial',
        symbol: '600519',
        latestDate: '2026-08-11',
        failedModules: ['news'],
        dataStatus: { available: false },
      },
      'fallback',
    ),
    {
      stockCode: '600519',
      analysisDate: '2026-08-11',
      dataStatus: { available: false },
      dataFetched: true,
      fetchStatus: 'partial',
      failedModules: ['news'],
    },
  )
})
