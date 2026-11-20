import axios from 'axios'
import { mockLlmAnalysis, mockPriceHistory, mockStocks } from '@/mock/stockData'

const delay = (ms = 300) => new Promise((resolve) => setTimeout(resolve, ms))

const client = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

client.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
)

export async function fetchStockList() {
  await delay()
  return mockStocks
}

export async function fetchStockDetail(code) {
  await delay()
  const stock = mockStocks.find((item) => item.code === code)
  if (!stock) {
    throw new Error('股票不存在')
  }

  return {
    ...stock,
    priceHistory: mockPriceHistory[code] ?? { dates: [], prices: [] },
    llmAnalysis: mockLlmAnalysis[code] ?? null,
  }
}

export default client
