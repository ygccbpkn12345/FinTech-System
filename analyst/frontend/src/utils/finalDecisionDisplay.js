export function buildFinalDecisionDisplay(decision = {}) {
  const raw = String(decision?.action ?? '').trim().toLowerCase()
  const isBuy = raw.includes('买入') || raw.includes('buy')
  return isBuy
    ? { action: '买入', actionEn: 'Buy' }
    : { action: '观望', actionEn: 'Hold' }
}
