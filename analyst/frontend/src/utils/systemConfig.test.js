import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cacheSystemConfig,
  hasUsableTushareToken,
  loadCachedSystemConfig,
  normalizeSystemConfig,
} from './systemConfig.js'

function installSessionStorage() {
  const storage = new Map()
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
  }
}

test('cached public configuration preserves data source and credential flags', () => {
  installSessionStorage()
  const config = normalizeSystemConfig({
    dataSource: 'tushare',
    crawlUrl: 'https://finance.example/',
    tushareTokenConfigured: true,
    maskedTushareToken: 'tok****1234',
    apiKeyConfigured: true,
    maskedApiKey: 'sk-****5678',
  })

  cacheSystemConfig(config)
  const loaded = loadCachedSystemConfig()

  assert.equal(loaded.dataSource, 'tushare')
  assert.equal(loaded.crawlUrl, 'https://finance.example/')
  assert.equal(loaded.tushareTokenConfigured, true)
  assert.equal(loaded.maskedTushareToken, 'tok****1234')
  assert.equal(loaded.apiKeyConfigured, true)
})

test('saved server token is usable without returning plaintext to the browser', () => {
  assert.equal(hasUsableTushareToken({ tushareToken: '', tushareTokenConfigured: true }), true)
  assert.equal(hasUsableTushareToken({ tushareToken: '', tushareTokenConfigured: false }), false)
})
