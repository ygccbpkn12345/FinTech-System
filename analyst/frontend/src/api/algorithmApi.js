import client from '@/api/analysisApi'

export const fetchAlgorithms = () => client.get('/api/algorithms')
export const fetchLocalTools = () => client.get('/api/algorithms/local-tools')
export const createAlgorithm = (body) => client.post('/api/algorithms', body)
export const updateAlgorithm = (name, body) => client.put(`/api/algorithms/${encodeURIComponent(name)}`, body)
export const deleteAlgorithm = (name) => client.delete(`/api/algorithms/${encodeURIComponent(name)}`)
