import assert from 'node:assert/strict'
import test from 'node:test'

import { checkAnalysisDateAvailability } from './analysisDateGuard.js'

test('unavailable analysis date returns warning and blocks start', () => {
  assert.deepEqual(
    checkAnalysisDateAvailability('2026-08-10', ['2026-08-08', '2026-08-11']),
    {
      allowed: false,
      message: '分析日期 2026-08-10 没有可用数据，请重新选择日期',
    },
  )
})

test('available analysis date permits start', () => {
  assert.deepEqual(checkAnalysisDateAvailability('2026-08-11', ['2026-08-11']), {
    allowed: true,
    message: '',
  })
})
