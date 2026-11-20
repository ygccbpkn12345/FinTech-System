export function normalizeApiBaseUrl(value) {
  return String(value ?? 'http://localhost:8000').trim().replace(/\/+$/, '')
}

export const API_BASE_URL = normalizeApiBaseUrl(import.meta.env?.VITE_API_BASE_URL)
