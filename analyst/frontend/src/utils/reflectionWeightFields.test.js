import assert from 'node:assert/strict'
import { normalizeReflectionWeightFields } from './reflectionWeightFields.js'

const legacy = normalizeReflectionWeightFields(
  { analyst: 'news', from: '14%', to: '12%' },
  0,
)
assert.deepEqual(legacy, {
  analystId: 'news',
  currentWeight: 0.14,
  suggestedWeight: 0.12,
})

const invalid = normalizeReflectionWeightFields(
  { analystId: 'company', currentWeight: '', suggestedWeight: 'not-a-number' },
  1,
)
assert.equal(invalid.analystId, 'company')
assert.equal(invalid.currentWeight, 0)
assert.equal(invalid.suggestedWeight, 0)
assert.ok(Number.isFinite(invalid.currentWeight))
assert.ok(Number.isFinite(invalid.suggestedWeight))

console.log('reflection weight field tests passed')
