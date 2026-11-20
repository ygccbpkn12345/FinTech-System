import {
  cleanDisplayText,
  cleanPromptOptimizationItem,
  cleanRiskImprovementItem,
  collectStringValues,
  collapseNumberedSections,
  dedupeStructuredItems,
  mergeNumberedSections,
  recoverLongerText,
  recoverSectionText,
} from '@/utils/displayTextUtils'
import { normalizeReflectionExtraFields } from './reflectionExtraFields'
import { normalizeReflectionWeightFields } from './reflectionWeightFields'

function pickStr(...values) {
  for (const value of values) {
    if (value != null && value !== '') return String(value)
  }
  return ''
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function riskItemTextParts(raw) {
  if (typeof raw === 'string') return [raw.trim()].filter(Boolean)
  const obj = asObject(raw)
  if (!obj) return []

  return [
    obj.current,
    obj.currentState,
    obj.current_state,
    obj.before,
    obj['现状'],
    obj.status,
    obj.suggested,
    obj.suggestion,
    obj.recommendation,
    obj.after,
    obj.improvement,
    obj.advice,
    obj.proposed,
    obj.change,
    obj.rationale,
    obj.reason,
    obj.why,
    obj.explanation,
    obj.detail,
    obj.comment,
    obj.text,
    obj.message,
    obj.value,
    obj.content,
    obj.contentText,
    obj.body,
    obj.summary,
    obj.description,
    obj.desc,
    ...(Array.isArray(obj.sections) ? obj.sections : []),
  ].filter((part) => part != null && part !== '')
}

/** 将多条风控建议合并为按编号去重后的独立条目，避免「1+2 挤一条」与重复「2.」 */
function flattenRiskImprovements(rawItems = [], extraCandidates = []) {
  const allCandidates = [
    ...extraCandidates,
    ...rawItems.flatMap((item) => collectStringValues(item)),
  ]

  const sectionPool = []

  for (const raw of rawItems) {
    const itemCandidates = [...allCandidates, ...collectStringValues(raw)]
    const parts = riskItemTextParts(raw)

    for (const section of mergeNumberedSections(...parts)) {
      sectionPool.push(recoverSectionText(section, ...itemCandidates))
    }
  }

  const sections = collapseNumberedSections(
    sectionPool.map((section) => recoverSectionText(section, ...allCandidates)),
  )

  return sections
    .map((section, index) =>
      cleanRiskImprovementItem({
        item: section.match(/^\d+\.\s*([^：:\-\n]{2,28})/)?.[1]?.trim() || `风控建议 ${index + 1}`,
        sections: [section],
        body: section,
        suggested: section,
        text: section,
      }),
    )
    .filter(Boolean)
}

function hasVisibleText(...parts) {
  return parts.some((part) => pickStr(part))
}

/** 单条风控改进建议 */
export function normalizeRiskImprovementItem(raw, index = 0, extraSources = []) {
  if (typeof raw === 'string') {
    const text = raw.trim()
    if (!text) return null
    return cleanRiskImprovementItem({
      item: `风控建议 ${index + 1}`,
      text,
      extraSources,
    })
  }

  const obj = asObject(raw)
  if (!obj) return null

  const item = pickStr(
    obj.item,
    obj.title,
    obj.name,
    obj.label,
    obj.riskType,
    obj.risk_type,
    obj.type,
    obj.topic,
    obj.category,
  )
  const payload = {
    item: item || `风控建议 ${index + 1}`,
    current: pickStr(
      obj.current,
      obj.currentState,
      obj.current_state,
      obj.before,
      obj['现状'],
      obj.status,
    ),
    suggested: pickStr(
      obj.suggested,
      obj.suggestion,
      obj.recommendation,
      obj.after,
      obj.improvement,
      obj.advice,
      obj.proposed,
      obj.change,
    ),
    rationale: pickStr(
      obj.rationale,
      obj.reason,
      obj.why,
      obj.explanation,
      obj.detail,
      obj.comment,
    ),
    text: pickStr(obj.text, obj.message, obj.value),
    content: pickStr(obj.content, obj.contentText),
    body: pickStr(obj.body),
    summary: pickStr(obj.summary),
    description: pickStr(obj.description, obj.desc),
    sections: Array.isArray(obj.sections) ? obj.sections : undefined,
    extraSources,
  }

  if (
    !hasVisibleText(
      payload.current,
      payload.suggested,
      payload.rationale,
      payload.text,
      payload.content,
      payload.body,
      payload.summary,
      payload.description,
    )
  ) {
    return null
  }

  return cleanRiskImprovementItem(payload)
}

export function normalizeRiskImprovementsList(list = [], extraSources = []) {
  if (!Array.isArray(list)) return []
  return list
    .map((item, index) => normalizeRiskImprovementItem(item, index, extraSources))
    .filter(Boolean)
}

/** 单条 Prompt 优化建议 */
export function normalizePromptOptimizationItem(raw, index = 0, extraSources = []) {
  if (typeof raw === 'string') {
    const text = raw.trim()
    if (!text) return null
    return cleanPromptOptimizationItem({
      target: `Prompt 优化 ${index + 1}`,
      suggestion: text,
      text,
      extraSources,
    })
  }

  const obj = asObject(raw)
  if (!obj) return null

  const payload = {
    target:
      pickStr(
        obj.target,
        obj.agent,
        obj.role,
        obj.name,
        obj.title,
        obj.prompt,
        obj.promptName,
        obj.prompt_name,
        obj.node,
        obj.module,
      ) || `Prompt 优化 ${index + 1}`,
    issue: pickStr(
      obj.issue,
      obj.problem,
      obj.question,
      obj.current,
      obj.currentIssue,
      obj.current_issue,
      obj.weakness,
    ),
    suggestion: pickStr(
      obj.suggestion,
      obj.improvement,
      obj.recommendation,
      obj.advice,
      obj.optimization,
      obj.fix,
      obj.proposed,
      obj.change,
    ),
    text: pickStr(obj.text, obj.message, obj.value),
    content: pickStr(obj.content, obj.contentText),
    body: pickStr(obj.body),
    description: pickStr(obj.description, obj.desc),
    sections: Array.isArray(obj.sections) ? obj.sections : undefined,
    extraSources,
  }

  if (
    !hasVisibleText(
      payload.issue,
      payload.suggestion,
      payload.text,
      payload.content,
      payload.body,
      payload.description,
    ) &&
    /^Prompt\s*优化\s*\d+$/i.test(payload.target)
  ) {
    return null
  }

  return cleanPromptOptimizationItem(payload)
}

export function normalizePromptOptimizationsList(list = [], extraSources = []) {
  if (!Array.isArray(list)) return []
  return list
    .map((item, index) => normalizePromptOptimizationItem(item, index, extraSources))
    .filter(Boolean)
}

export function normalizeWeightAdjustmentItem(raw, index = 0) {
  if (!raw || typeof raw !== 'object') return null
  const weights = normalizeReflectionWeightFields(raw, index)
  const reason = pickStr(raw.reason, raw.explanation, raw.description, raw.comment, raw.text)
  if (!weights.analystId && !reason) return null
  return {
    ...weights,
    reason: cleanDisplayText(reason) || '--',
  }
}

export function normalizeWeightAdjustmentsList(list = []) {
  if (!Array.isArray(list)) return []
  return list.map((item, i) => normalizeWeightAdjustmentItem(item, i)).filter(Boolean)
}

export function normalizeManagerBlindSpotItem(raw, index = 0) {
  if (typeof raw === 'string') {
    const text = raw.trim()
    if (!text) return null
    return { area: `盲区 ${index + 1}`, description: text, suggestion: '' }
  }
  const obj = asObject(raw)
  if (!obj) return null
  const area = pickStr(obj.area, obj.topic, obj.name, obj.title, obj.category, `盲区 ${index + 1}`)
  const description = pickStr(
    obj.description,
    obj.detail,
    obj.content,
    obj.text,
    obj.summary,
    obj.issue,
  )
  const suggestion = pickStr(obj.suggestion, obj.advice, obj.recommendation, obj.improvement)
  if (!hasVisibleText(area, description, suggestion)) return null
  return {
    area: cleanDisplayText(area) || `盲区 ${index + 1}`,
    description: cleanDisplayText(description) || '--',
    suggestion: cleanDisplayText(suggestion),
  }
}

export function normalizeManagerBlindSpotsList(list = []) {
  if (!Array.isArray(list)) return []
  return list.map((item, i) => normalizeManagerBlindSpotItem(item, i)).filter(Boolean)
}

/** 统一规范化 reflection 对象 */
export function normalizeReflectionPayload(reflection = {}) {
  const src =
    typeof reflection === 'string'
      ? { summary: reflection, metaReflection: reflection }
      : reflection && typeof reflection === 'object'
        ? reflection
        : {}
  const extra = normalizeReflectionExtraFields(src)

  const riskRaw = src.riskSuggestions ?? src.risk_suggestions ?? src.riskControlImprovements ?? src.risk_control_improvements
  const source = asObject(src._source)
  const sourceRisk =
    source?.riskSuggestions ??
    source?.risk_suggestions ??
    source?.riskControlImprovements ??
    source?.risk_control_improvements
  const riskList = Array.isArray(riskRaw) ? riskRaw : []
  const sourceList = Array.isArray(sourceRisk) ? sourceRisk : []
  const mergedRiskRaw = riskList
    .map((item, index) => {
      const sourceItem = asObject(sourceList[index])
      const currentItem = asObject(item)
      if (sourceItem && currentItem) return { ...currentItem, ...sourceItem }
      return currentItem ?? sourceItem ?? item
    })
    .filter(Boolean)

  const promptRaw = src.promptOptimizations ?? src.prompt_optimizations
  const sourcePrompt = source?.promptOptimizations ?? source?.prompt_optimizations
  const promptList = Array.isArray(promptRaw) ? promptRaw : []
  const sourcePromptList = Array.isArray(sourcePrompt) ? sourcePrompt : []
  const promptOptimizations = dedupeStructuredItems(
    promptList
      .map((item, index) => {
        const sourceItem = asObject(sourcePromptList[index])
        const currentItem = asObject(item)
        const merged =
          sourceItem && currentItem
            ? { ...currentItem, ...sourceItem }
            : currentItem ?? sourceItem ?? item
        return normalizePromptOptimizationItem(merged, index)
      })
      .filter(Boolean),
  )

  const promptBodies = promptOptimizations.map((item) => item.body || item.suggestion)
  const textCandidates = [
    ...collectStringValues(source),
    ...collectStringValues(src),
    ...promptBodies,
    ...mergedRiskRaw.flatMap((item) => collectStringValues(item)),
  ]

  let riskControlImprovements = dedupeStructuredItems(
    flattenRiskImprovements(mergedRiskRaw, textCandidates),
    (item) => item?.body ?? item?.suggested ?? '',
  )

  const rawSummary = pickStr(src.summary, src.metaReflection, src.meta_reflection)
  const summary = recoverLongerText(rawSummary, ...textCandidates)
  const metaReflection = recoverLongerText(
    pickStr(src.metaReflection, src.meta_reflection, src.summary),
    summary,
    ...textCandidates,
  )

  return {
    summary: summary || '',
    metaReflection: metaReflection || summary || '',
    fullText: extra.fullText || summary || '',
    routerReflection: extra.routerReflection,
    weeklySummary: extra.weeklySummary,
    roleReflections: extra.roleReflections,
    weightAdjustments: normalizeWeightAdjustmentsList(
      src.weightAdjustments ?? src.weight_adjustments ?? [],
    ),
    managerBlindSpots: normalizeManagerBlindSpotsList(
      src.managerBlindSpots ?? src.manager_blind_spots ?? [],
    ),
    riskControlImprovements,
    riskSuggestions: riskControlImprovements,
    promptOptimizations,
  }
}

export function hasReflectionDisplayContent(reflection = {}) {
  const normalized = normalizeReflectionPayload(reflection)
  return Boolean(
    normalized.summary ||
      normalized.metaReflection ||
      normalized.weightAdjustments.length ||
      normalized.managerBlindSpots.length ||
      normalized.riskControlImprovements.length ||
      normalized.promptOptimizations.length ||
      normalized.roleReflections.length ||
      normalized.weeklySummary
  )
}
