/**
 * 将 LLM 原始输出清理为适合终端 UI 展示的纯文本
 */

const PLACEHOLDER_RE =
  /\[(?:WINNING_POINT|SUGGESTION|ISSUE|TARGET|ACTION|RESULT|PLACEHOLDER|[A-Z][A-Z0-9_]{2,})\]/gi

const TEMPLATE_RE = /\{\{[^}]+\}\}/g

function stripInlineMarkdown(text) {
  let result = text

  result = result.replace(/```[\w-]*\n?([\s\S]*?)```/g, '$1')
  result = result.replace(/`([^`]+)`/g, '$1')

  for (let i = 0; i < 4; i += 1) {
    result = result.replace(/\*\*\*([^*]*)\*\*\*/g, '$1')
    result = result.replace(/\*\*([^*]*?)\*\*/g, '$1')
    result = result.replace(/__([^_]*?)__/g, '$1')
    result = result.replace(/\*([^*\n]+?)\*/g, '$1')
    result = result.replace(/_([^_\n]+?)_/g, '$1')
  }

  result = result.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')

  result = result.replace(/#{1,6}\s*/g, '')
  result = result.replace(/\*+/g, '')
  result = result.replace(/`+/g, '')
  result = result.replace(/~+/g, '')

  return result
}

function stripLinePrefixes(text) {
  return text
    .split('\n')
    .map((line) => {
      let row = line.trim()
      row = row.replace(/^>\s*/, '')
      row = row.replace(/^[*＊]+\s*[:：]\s*/, '')
      row = row.replace(/^[:：*＊\-+#>]+\s*[:：]\s*/, '')
      row = row.replace(/^[:：]\s*/, '')
      row = row.replace(/^[*＊\-+#>]+\s*/, '')
      return row
    })
    .join('\n')
}

function stripReflectionCaseLabels(text) {
  return text
    .replace(/情况\s*\d+\s*[:：]\s*/g, '')
    .replace(/^\s*情况\s*\d+\s+/gm, '')
}

function normalizePunctuation(text) {
  return text
    .replace(/\s*-\s*:\s*/g, '：')
    .replace(/:\s*-\s*:/g, '：')
    .replace(/：{2,}/g, '：')
    .replace(/^\s*建议\s*[:：]\s*/gm, '')
    .replace(/^\s*问题\s*[:：]\s*/gm, '')
    .replace(/^\s*当前\s*[:：]\s*/gm, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\s+([，。；：！？、])/g, '$1')
    .replace(/([，。；：！？、])\s+/g, '$1')
}

export function cleanDisplayText(input) {
  if (input == null) return ''
  if (typeof input !== 'string') input = String(input)
  if (!input.trim()) return ''

  let text = input.replace(/\r\n/g, '\n').replace(/\u00a0/g, ' ')

  text = text.replace(PLACEHOLDER_RE, '')
  text = text.replace(TEMPLATE_RE, '')

  text = stripInlineMarkdown(text)
  text = stripLinePrefixes(text)
  text = text.replace(/^[-*_]{3,}\s*$/gm, '')
  text = text.replace(/^\s*[-*+•]\s+/gm, '')

  text = normalizePunctuation(text)

  text = stripReflectionCaseLabels(text)

  text = stripInlineMarkdown(text)
  text = stripLinePrefixes(text)
  text = normalizePunctuation(text)
  text = text.replace(/^\s*[:：]\s*/gm, '')

  text = stripReflectionCaseLabels(text)

  return text.trim()
}

function normalizeKey(text) {
  return cleanDisplayText(text).replace(/\s+/g, ' ')
}

function normalizeComparable(text) {
  return normalizeKey(text).replace(/(?:\.{2,3}|…)\s*$/g, '').trim()
}

function isRelatedText(a, b) {
  const left = normalizeComparable(a)
  const right = normalizeComparable(b)
  if (!left || !right) return false
  if (left === right) return true
  if (left.startsWith(right) || right.startsWith(left)) return true
  const minLen = Math.min(left.length, right.length, 48)
  return minLen >= 16 && left.slice(0, minLen) === right.slice(0, minLen)
}

function isDuplicateChunk(a, b) {
  return isRelatedText(a, b)
}

function isTruncatedText(text = '') {
  const cleaned = cleanDisplayText(text)
  return Boolean(cleaned && /(?:\.{2,3}|…)\s*$/.test(cleaned))
}

/** 在相关候选文本中选取更完整版本，用于修复摘要/分段被截断的问题 */
export function recoverLongerText(baseText, ...candidates) {
  let best = cleanDisplayText(baseText)

  for (const candidate of candidates) {
    const cleaned = cleanDisplayText(candidate)
    if (!cleaned) continue
    if (!best) {
      best = cleaned
      continue
    }
    if (!isRelatedText(best, cleaned)) continue

    if (cleaned.length > best.length) {
      best = cleaned
    } else if (isTruncatedText(best) && !isTruncatedText(cleaned)) {
      best = cleaned
    }
  }

  return best
}

/** 按编号段落从候选文本中补全被截断的分段 */
export function recoverSectionText(section, ...candidates) {
  let best = recoverLongerText(section, ...candidates)
  const sectionNum = String(section).match(/^((?:[1-9]|1\d|20))\.\s/)?.[1]

  if (!sectionNum) return best

  for (const candidate of candidates) {
    const cleaned = cleanDisplayText(candidate)
    if (!cleaned) continue

    for (const part of splitNumberedSections(cleaned)) {
      const num = part.match(/^((?:[1-9]|1\d|20))\.\s/)?.[1]
      if (num !== sectionNum) continue
      if (!isRelatedText(best, part) && !isRelatedText(section, part)) continue

      if (part.length > best.length) {
        best = part
      } else if (isTruncatedText(best) && !isTruncatedText(part)) {
        best = part
      }
    }
  }

  return best
}

function sectionContentKey(section = '') {
  return normalizeKey(String(section).replace(/^(?:[1-9]|1\d|20)\.\s*/, ''))
}

function isDuplicateSection(a, b) {
  if (isDuplicateChunk(a, b)) return true
  const left = sectionContentKey(a)
  const right = sectionContentKey(b)
  return Boolean(left && right && left === right)
}

export function dedupeSections(sections = []) {
  const result = []

  for (const section of sections) {
    const cleaned = cleanDisplayText(section)
    if (!cleaned) continue

    const existingIndex = result.findIndex((existing) => isDuplicateSection(existing, cleaned))
    if (existingIndex >= 0) {
      if (cleaned.length > result[existingIndex].length) {
        result[existingIndex] = cleaned
      }
      continue
    }
    result.push(cleaned)
  }

  return result
}

/** 同编号段落只保留最长一条，并展开嵌套编号 */
export function collapseNumberedSections(sections = []) {
  const expanded = []

  for (const section of sections) {
    const parts = splitNumberedSections(section)
    expanded.push(...parts)
  }

  const byNumber = new Map()
  const unnumbered = []

  for (const section of dedupeSections(expanded)) {
    const match = section.match(/^((?:[1-9]|1\d|20))\.\s/)
    if (match) {
      const num = match[1]
      const prev = byNumber.get(num)
      if (!prev || section.length > prev.length) {
        byNumber.set(num, section)
      }
    } else {
      unnumbered.push(section)
    }
  }

  const numbered = [...byNumber.entries()]
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([, text]) => text)

  return numbered.length ? numbered : dedupeSections(unnumbered)
}

export function dedupeDisplayTexts(...parts) {
  const result = []

  for (const part of parts) {
    const cleaned = cleanDisplayText(part)
    if (!cleaned) continue

    const chunks = cleaned.split(/\n+/).map((c) => c.trim()).filter(Boolean)
    for (const chunk of chunks.length ? chunks : [cleaned]) {
      const existingIndex = result.findIndex((existing) => isDuplicateChunk(existing, chunk))
      if (existingIndex >= 0) {
        if (chunk.length > result[existingIndex].length) {
          result[existingIndex] = chunk
        }
        continue
      }
      result.push(chunk)
    }
  }

  return result
}

function buildStructuredSections(...parts) {
  const sections = mergeNumberedSections(...parts)
  return collapseNumberedSections(
    sections.map((section) => recoverSectionText(section, ...parts)),
  )
}

/** 按「1. 2. 3.」分段（避免把日期如 2024. 误识别为段落号） */
export function splitNumberedSections(text) {
  const cleaned = cleanDisplayText(text)
  if (!cleaned) return []

  const numberedSplit = /(?=(?:[1-9]|1\d|20)\.\s)/

  const inline = cleaned
    .split(numberedSplit)
    .map((part) => part.trim())
    .filter(Boolean)

  if (inline.length > 1) return inline

  const lines = cleaned.split('\n')
  const sections = []
  let current = ''

  for (const line of lines) {
    const trimmed = line.trim()
    if (/^(?:[1-9]|1\d|20)\.\s/.test(trimmed)) {
      if (current.trim()) sections.push(current.trim())
      current = trimmed
    } else if (current) {
      current = `${current}\n${line}`
    } else {
      current = line
    }
  }

  if (current.trim()) sections.push(current.trim())

  if (sections.length > 1) return sections

  return [cleaned]
}

/** 合并多段文本中的编号条目，同编号保留最长版本 */
export function mergeNumberedSections(...parts) {
  const byNumber = new Map()
  const unnumbered = []

  for (const part of parts) {
    if (part == null || part === '') continue
    const cleaned = cleanDisplayText(part)
    if (!cleaned) continue

    for (const section of splitNumberedSections(cleaned)) {
      const match = section.match(/^((?:[1-9]|1\d|20))\.\s/)
      if (match) {
        const num = match[1]
        const prev = byNumber.get(num)
        if (!prev || section.length > prev.length) {
          byNumber.set(num, section)
        }
      } else {
        const dupIdx = unnumbered.findIndex((existing) => isDuplicateSection(existing, section))
        if (dupIdx >= 0) {
          if (section.length > unnumbered[dupIdx].length) unnumbered[dupIdx] = section
        } else {
          unnumbered.push(section)
        }
      }
    }
  }

  const numbered = dedupeSections(
    [...byNumber.entries()]
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([, text]) => text),
  )

  if (numbered.length) return numbered
  return dedupeSections(unnumbered)
}

export function mergeDisplayFields(...parts) {
  return dedupeDisplayTexts(...parts).join('\n\n')
}

export function collectStringValues(value, bucket = []) {
  if (value == null) return bucket
  if (typeof value === 'string') {
    bucket.push(value)
    return bucket
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectStringValues(item, bucket))
    return bucket
  }
  if (typeof value === 'object') {
    Object.values(value).forEach((item) => collectStringValues(item, bucket))
  }
  return bucket
}

function extractSectionTitle(section = '') {
  const match = section.match(/^\d+\.\s*([^：:\-\n]{2,28})/)
  return match ? match[1].trim() : ''
}

export function cleanRiskImprovementItem(item = {}) {
  const itemTitle = cleanDisplayText(item.item) || cleanDisplayText(item.title) || ''
  const rawParts = [
    item.current,
    item.suggested,
    item.rationale,
    item.text,
    item.content,
    item.body,
    item.description,
    ...(Array.isArray(item.sections) ? item.sections : []),
    ...(Array.isArray(item.extraSources) ? item.extraSources : []),
  ]
  let sections = buildStructuredSections(...rawParts)

  if (!sections.length && !itemTitle) return null

  if (!sections.length && itemTitle) sections = [itemTitle]

  const title =
    itemTitle && !/^风控建议\s*\d*$/.test(itemTitle)
      ? itemTitle
      : extractSectionTitle(sections[0]) || itemTitle || '风控建议'

  const mergedBody = sections.join('\n\n')

  return {
    item: title,
    sections,
    body: mergedBody,
    current: cleanDisplayText(item.current) || '',
    suggested: cleanDisplayText(item.suggested) || mergedBody,
    rationale: cleanDisplayText(item.rationale) || '',
    text: cleanDisplayText(item.text) || '',
    content: cleanDisplayText(item.content) || '',
  }
}

export function cleanPromptOptimizationItem(item = {}) {
  const target = cleanDisplayText(item.target) || cleanDisplayText(item.name) || ''
  const finalSections = buildStructuredSections(
    item.issue,
    item.suggestion,
    item.content,
    item.text,
    item.body,
    item.description,
    ...(Array.isArray(item.sections) ? item.sections : []),
    ...(Array.isArray(item.extraSources) ? item.extraSources : []),
  )

  if (!target && !finalSections.length) return null

  const sections = finalSections.length ? finalSections : target ? [target] : []
  const mergedBody = sections.join('\n\n')

  return {
    target: target || extractSectionTitle(sections[0]) || 'Prompt 优化',
    issue: cleanDisplayText(item.issue) || '',
    suggestion: mergedBody,
    sections,
    body: mergedBody,
  }
}

export function dedupeStructuredItems(items = [], getBody = (item) => item?.body ?? item?.suggestion ?? '') {
  const result = []

  for (const item of items) {
    if (!item) continue
    const body = getBody(item)
    if (result.some((existing) => isDuplicateSection(getBody(existing), body))) continue
    result.push(item)
  }

  return result
}

export function cleanStringList(list = []) {
  if (!Array.isArray(list)) return []
  const seen = new Set()
  return list
    .map((item) =>
      typeof item === 'string' ? cleanDisplayText(item) : cleanDisplayText(item?.text ?? item?.content),
    )
    .filter((item) => {
      if (!item) return false
      const key = normalizeKey(item)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

export function cleanDisplayObjectStrings(obj, keys) {
  if (!obj || typeof obj !== 'object') return obj
  const next = { ...obj }
  for (const key of keys) {
    if (typeof next[key] === 'string') {
      next[key] = cleanDisplayText(next[key])
    }
  }
  return next
}
