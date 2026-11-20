import { cleanDisplayText, collapseNumberedSections, mergeDisplayFields } from '@/utils/displayTextUtils'

function LabeledText({ label, children, className }) {
  const text = cleanDisplayText(children)
  if (!text) return null
  return (
    <p className={className}>
      {label}
      {text}
    </p>
  )
}

/** 展示 LLM 文本：自动清理 Markdown 与占位符 */
function DisplayText({ children, className, as: Component = 'span', fallback = null }) {
  const text = cleanDisplayText(children)
  if (!text) return fallback
  return <Component className={className}>{text}</Component>
}

/** 多行文本，按段落渲染 */
function DisplayParagraphs({ children, className }) {
  const text = cleanDisplayText(children)
  if (!text) return null

  const lines = text.split(/\n+/).filter(Boolean)
  if (lines.length <= 1) {
    return <div className={className}>{text}</div>
  }

  return lines.map((line, index) => (
    <div key={index} className={className}>
      {line}
    </div>
  ))
}

/** 反思/风控类长文本：去重后按段落展示 */
function DisplayStructuredBody({ item, className = 'reflection-body-text' }) {
  const sections = collapseNumberedSections(
    Array.isArray(item?.sections) && item.sections.length
      ? item.sections
      : [item?.body, item?.suggestion, item?.suggested, item?.text, item?.content].filter(Boolean),
  )

  if (!sections.length) {
    const fallback = mergeDisplayFields(
      item?.current,
      item?.issue,
      item?.rationale,
    )
    if (!fallback) return null
    return <div className={className}>{fallback}</div>
  }

  if (sections.length === 1) {
    return <div className={className}>{sections[0]}</div>
  }

  return (
    <div className="reflection-structured-body">
      {sections.map((section, index) => (
        <div key={index} className={className}>
          {section}
        </div>
      ))}
    </div>
  )
}

export { DisplayText, DisplayParagraphs, LabeledText, DisplayStructuredBody, cleanDisplayText }
