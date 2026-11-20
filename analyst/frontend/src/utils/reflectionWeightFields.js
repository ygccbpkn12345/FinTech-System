function firstValue(...values) {
  return values.find((value) => value != null && value !== '')
}

export function normalizeReflectionWeight(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value !== 'string') return 0

  const text = value.trim()
  if (!text) return 0
  const parsed = Number.parseFloat(text.replace('%', ''))
  if (!Number.isFinite(parsed)) return 0
  return text.includes('%') || Math.abs(parsed) > 1 ? parsed / 100 : parsed
}

export function normalizeReflectionWeightFields(raw = {}, index = 0) {
  return {
    analystId: String(
      firstValue(raw.analystId, raw.analyst_id, raw.analyst, raw.analystName, raw.name, raw.id) ??
        `analyst_${index}`,
    ),
    currentWeight: normalizeReflectionWeight(
      firstValue(raw.currentWeight, raw.current_weight, raw.fromWeight, raw.oldWeight, raw.from),
    ),
    suggestedWeight: normalizeReflectionWeight(
      firstValue(raw.suggestedWeight, raw.suggested_weight, raw.toWeight, raw.newWeight, raw.to),
    ),
  }
}
