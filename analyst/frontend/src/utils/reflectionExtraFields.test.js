import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeReflectionExtraFields } from './reflectionExtraFields.js'

test('preserves complete role and weekly reflection text', () => {
  const longText = '完整反思。'.repeat(100)
  const normalized = normalizeReflectionExtraFields({
    full_text: longText,
    router_reflection: '{"market_analyst":0.4}',
    weekly_summary: '完整周度反思',
    role_reflections: [{ role: '经理', content: longText }],
  })

  assert.equal(normalized.fullText, longText)
  assert.equal(normalized.roleReflections[0].content, longText)
  assert.equal(normalized.weeklySummary, '完整周度反思')
  assert.equal(normalized.routerReflection, '{"market_analyst":0.4}')
})
