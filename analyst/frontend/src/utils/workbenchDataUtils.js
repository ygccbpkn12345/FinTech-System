import {
  hasReflectionDisplayContent,
  normalizeReflectionPayload,
} from './reflectionUtils'
import { cleanDisplayText } from './displayTextUtils'

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function pickStr(...values) {
  for (const value of values) {
    if (value != null && value !== '') return String(value)
  }
  return ''
}

function isFinalBranch(branch = '') {
  const text = String(branch)
  return (
    text.includes('综合决策') ||
    text.includes('最终决策') ||
    text.toLowerCase().includes('final')
  )
}

export function normalizeDecisionTreeNode(node, index = 0) {
  if (node == null) return null
  if (typeof node === 'string') {
    const text = cleanDisplayText(node)
    return {
      branch: `分支 ${index + 1}`,
      condition: '--',
      action: text || '--',
      rationale: text,
    }
  }
  if (typeof node !== 'object') return null

  const branch = pickStr(
    node.branch,
    node.branchName,
    node.branch_name,
    node.name,
    node.title,
    node.label,
    `分支 ${index + 1}`,
  )

  return {
    branch,
    condition: pickStr(node.condition, node.trigger, node.rule, node.when, node.criteria, '--'),
    action: cleanDisplayText(pickStr(node.action, node.decision, node.result, node.output, '--')) || '--',
    scoreChange: node.scoreChange ?? node.score_change ?? node.scoreDelta ?? null,
    suggestedPosition:
      node.suggestedPosition ?? node.suggested_position ?? node.position ?? null,
    rationale: cleanDisplayText(
      pickStr(node.rationale, node.reason, node.summary, node.description, ''),
    ),
  }
}

export function normalizeDecisionTree(rawTree) {
  return asArray(rawTree)
    .map((node, index) => normalizeDecisionTreeNode(node, index))
    .filter(Boolean)
}

export function normalizePreReflectionCheck(check, index = 0) {
  if (!check || typeof check !== 'object') return null
  return {
    id: pickStr(check.id, check.key, `check_${index}`),
    area: pickStr(check.area, check.category, check.topic, `检查项 ${index + 1}`),
    question: pickStr(check.question, check.prompt, check.title, '--'),
    status: pickStr(check.status, check.result, 'warning'),
    finding: cleanDisplayText(pickStr(check.finding, check.conclusion, check.detail, check.answer, '--')) || '--',
  }
}

export function normalizePreReflection(raw) {
  const src = asObject(raw)
  if (Array.isArray(raw)) {
    return {
      summary: '经理 Agent 对当前决策路径进行事前反思检查。',
      checks: raw.map(normalizePreReflectionCheck).filter(Boolean),
    }
  }

  const checks = asArray(src.checks ?? src.items ?? src.reviews)
    .map(normalizePreReflectionCheck)
    .filter(Boolean)

  return {
    summary: cleanDisplayText(pickStr(src.summary, src.overview, src.description, '')),
    checks,
  }
}

export function normalizeRiskItem(item, index = 0) {
  if (!item) return null
  if (typeof item === 'string') {
    const text = cleanDisplayText(item)
    return {
      riskType: text || `风险项 ${index + 1}`,
      level: 'medium',
      levelLabel: '中等',
      explanation: text,
      mitigation: '请参考最终决策中的止损与仓位建议。',
    }
  }
  if (typeof item !== 'object') return null

  const level = pickStr(item.level, item.severity, item.riskLevel, item.risk_level, 'medium')

  return {
    riskType: pickStr(
      item.riskType,
      item.risk_type,
      item.type,
      item.name,
      item.title,
      `风险项 ${index + 1}`,
    ),
    level,
    levelLabel: pickStr(
      item.levelLabel,
      item.level_label,
      level === 'high' ? '高' : level === 'low' ? '低' : '中等',
    ),
    explanation: cleanDisplayText(
      pickStr(item.explanation, item.description, item.detail, item.reason, item.content, '--'),
    ) || '--',
    mitigation: cleanDisplayText(
      pickStr(
        item.mitigation,
        item.suggestion,
        item.advice,
        item.countermeasure,
        item.response,
        '--',
      ),
    ) || '--',
  }
}

export function normalizeRiskListItems(raw) {
  const val = raw?.riskAssessment ?? raw?.risk_assessment ?? raw?.riskList ?? raw?.risks
  let list = []
  if (Array.isArray(val)) list = val
  else if (val && Array.isArray(val.items)) list = val.items
  else if (val && Array.isArray(val.list)) list = val.list
  else if (val && Array.isArray(val.risks)) list = val.risks

  return list.map(normalizeRiskItem).filter(Boolean)
}

function buildDecisionTreeFromRealData(analysts = [], routerWeights = [], finalDecision = {}) {
  const branches = analysts.map((analyst, index) => {
    const weight = routerWeights.find((w) => w.analystId === analyst.id)
    return {
      branch: `${analyst.name || analyst.role || `分析师${index + 1}`}分支`,
      condition: `${analyst.role || analyst.name} · signal=${analyst.signal ?? 'neutral'}`,
      action: analyst.summary ? analyst.summary.slice(0, 48) : '纳入经理综合评估',
      scoreChange: weight?.finalWeight != null ? `权重 ${Math.round(weight.finalWeight * 100)}%` : null,
      rationale: analyst.summary || analyst.report || '',
    }
  })

  if (finalDecision?.action && finalDecision.action !== '--') {
    branches.push({
      branch: '综合决策分支',
      condition: finalDecision.coreReason
        ? finalDecision.coreReason.slice(0, 120)
        : '综合五位分析师信号与路由权重',
      action: finalDecision.action,
      suggestedPosition: finalDecision.position,
      rationale: finalDecision.coreReason || finalDecision.dissentSummary || '',
    })
  }

  return branches
}

function buildPreReflectionFromRealData(analysts = [], finalDecision = {}, existing = {}) {
  const checks = []

  analysts.forEach((analyst, index) => {
    if (!analyst.summary && !analyst.report) return
    checks.push({
      id: analyst.id || `analyst_${index}`,
      area: analyst.name || analyst.role,
      question: `${analyst.name || '分析师'} 的核心观点是否已纳入经理决策？`,
      status: analyst.signal === 'neutral' ? 'warning' : 'passed',
      finding: analyst.summary || analyst.report.slice(0, 160),
    })
  })

  if (finalDecision?.dissentSummary) {
    checks.push({
      id: 'dissent',
      area: '分歧处理',
      question: '是否回应了分析师之间的分歧？',
      status: 'warning',
      finding: finalDecision.dissentSummary,
    })
  }

  if (finalDecision?.coreReason) {
    checks.push({
      id: 'core',
      area: '决策依据',
      question: '最终动作是否有充分依据支撑？',
      status: 'passed',
      finding: finalDecision.coreReason.slice(0, 200),
    })
  }

  return {
    summary:
      existing.summary ||
      '基于本次真实分析结果整理的经理事前反思：检查各分析师观点与最终决策依据是否一致。',
    checks: checks.length ? checks : existing.checks || [],
  }
}

function buildRiskFromFinalDecision(finalDecision = {}) {
  const keyRisks = asArray(finalDecision.keyRisks)
  if (!keyRisks.length) return []

  return keyRisks.map((risk, index) =>
    normalizeRiskItem(
      typeof risk === 'string'
        ? {
            riskType: risk,
            level: 'medium',
            explanation: risk,
            mitigation: finalDecision.stopLoss
              ? `建议止损参考：${finalDecision.stopLoss}`
              : '请结合仓位与置信度控制暴露。',
          }
        : risk,
      index,
    ),
  ).filter(Boolean)
}

function hasReflectionContent(reflection = {}) {
  return hasReflectionDisplayContent(reflection)
}

function buildReflectionFromRealData(
  reflection = {},
  finalDecision = {},
  routerWeights = [],
  analysts = [],
) {
  const weightAdjustments = routerWeights
    .filter((w) => w.adjustmentReason || w.finalWeight != null)
    .map((w) => ({
      analystId: w.analystId,
      currentWeight: w.historicalWeight ?? w.confidenceWeight ?? 0,
      suggestedWeight: w.finalWeight ?? 0,
      reason:
        w.adjustmentReason ||
        `${w.analystName || w.analystId} 路由权重 ${Math.round((w.finalWeight ?? 0) * 100)}%`,
    }))

  const managerBlindSpots = analysts
    .filter((a) => a.signal === 'neutral' || a.signal === 'bearish')
    .map((a) => ({
      area: a.name || a.role,
      description: a.summary || a.report?.slice(0, 160) || '--',
      suggestion: `关注 ${a.name || a.role} 的中性/偏空观点对最终 ${finalDecision.action || '决策'} 的影响。`,
    }))

  const derivedRisk = buildRiskFromFinalDecision(finalDecision).map((r) => ({
    item: r.riskType,
    current: r.explanation,
    suggested: r.mitigation,
    rationale: finalDecision.coreReason || '',
  }))

  const riskSource =
    reflection.riskControlImprovements?.length || reflection.riskSuggestions?.length
      ? reflection.riskControlImprovements ?? reflection.riskSuggestions
      : derivedRisk

  return normalizeReflectionPayload({
    ...reflection,
    _source: reflection._source ?? reflection,
    summary:
      reflection.summary ||
      reflection.metaReflection ||
      finalDecision.coreReason ||
      '本次分析反思记忆已根据真实决策结果整理。',
    metaReflection:
      reflection.metaReflection ||
      reflection.summary ||
      finalDecision.coreReason ||
      '',
    weightAdjustments: reflection.weightAdjustments?.length
      ? reflection.weightAdjustments
      : weightAdjustments,
    managerBlindSpots: reflection.managerBlindSpots?.length
      ? reflection.managerBlindSpots
      : managerBlindSpots,
    riskControlImprovements: riskSource,
    riskSuggestions: riskSource,
    promptOptimizations: reflection.promptOptimizations ?? [],
  })
}

/**
 * 补齐工作台四 Tab 所需数据（仅使用真实 result 字段推导，不注入 mock）
 */
export function enrichWorkbenchData(normalized = {}) {
  const analysts = normalized.analysts ?? []
  const routerWeights = normalized.routerWeights ?? normalized.routingWeights ?? []
  const finalDecision = normalized.finalDecision ?? {}
  const managerDecision = normalized.managerDecision ?? {}

  let tree = normalizeDecisionTree(
    managerDecision.tree?.length
      ? managerDecision.tree
      : normalized.managerDecisionTree,
  )
  if (!tree.length) {
    tree = buildDecisionTreeFromRealData(analysts, routerWeights, finalDecision)
  }

  let preReflection = normalizePreReflection(
    managerDecision.preReflection ?? normalized.managerPreReflection,
  )
  if (!preReflection.summary && !preReflection.checks.length) {
    preReflection = buildPreReflectionFromRealData(analysts, finalDecision, preReflection)
  }

  let riskList = normalizeRiskListItems(normalized)
  if (!riskList.length) {
    riskList = buildRiskFromFinalDecision(finalDecision)
  }

  let reflection = normalized.reflection ?? {}
  if (typeof reflection === 'string') {
    reflection = { summary: reflection, metaReflection: reflection }
  }
  if (!hasReflectionContent(reflection)) {
    reflection = buildReflectionFromRealData(
      reflection,
      finalDecision,
      routerWeights,
      analysts,
    )
  }

  return {
    decisionTree: tree,
    preReflection,
    riskAssessment: riskList,
    reflection,
  }
}

export { isFinalBranch, hasReflectionContent }
