import test from 'node:test'
import assert from 'node:assert/strict'

import { buildFinalDecisionDisplay } from './finalDecisionDisplay.js'

for (const action of ['谨慎买入', '买入', 'Buy', 'Cautious Buy']) {
  test(`${action} displays as 买入`, () => {
    assert.deepEqual(buildFinalDecisionDisplay({ action }), {
      action: '买入',
      actionEn: 'Buy',
    })
  })
}

for (const action of ['观望', 'Hold', '', '减仓']) {
  test(`${action || 'empty'} displays as 观望`, () => {
    assert.deepEqual(buildFinalDecisionDisplay({ action, position: '8%' }), {
      action: '观望',
      actionEn: 'Hold',
    })
  })
}
