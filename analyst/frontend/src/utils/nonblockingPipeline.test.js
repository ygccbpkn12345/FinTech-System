import test from 'node:test'
import assert from 'node:assert/strict'

import { FLOW_STEPS } from './processStepUtils.js'
import { VISIBLE_ANALYSIS_MODULES } from './analysisModuleDefinitions.js'
import { describeReflectionLifecycle } from './reflectionLifecycle.js'

test('analysis progress ends at final decision', () => {
  assert.equal(FLOW_STEPS.at(-1).key, 'decision')
  assert.equal(FLOW_STEPS.some((step) => step.key === 'reflection'), false)
  assert.equal(
    FLOW_STEPS.some((step) => step.nodes.includes('environment_simulation')),
    false,
  )
})

test('live module cards exclude postprocessing modules', () => {
  assert.equal(VISIBLE_ANALYSIS_MODULES.includes('environment_simulation'), false)
  assert.equal(VISIBLE_ANALYSIS_MODULES.includes('reflector'), false)
  assert.equal(VISIBLE_ANALYSIS_MODULES.includes('weekly_reflector'), false)
  assert.equal(VISIBLE_ANALYSIS_MODULES.at(-1), 'final_decision')
})

test('reflection lifecycle descriptions cover every backend state', () => {
  assert.match(describeReflectionLifecycle({ status: 'pending' }).message, /后台/)
  assert.match(describeReflectionLifecycle({ status: 'running' }).message, /后台/)
  assert.equal(describeReflectionLifecycle({ status: 'completed' }).kind, 'success')
  assert.equal(describeReflectionLifecycle({ status: 'failed' }).kind, 'error')
  assert.match(describeReflectionLifecycle({ status: 'not_applicable' }).message, /当天/)
})
