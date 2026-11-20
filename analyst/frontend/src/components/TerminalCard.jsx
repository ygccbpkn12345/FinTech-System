import { Tag, Tooltip } from 'antd'

function TerminalCard({
  title,
  subtitle,
  extra,
  icon,
  children,
  className = '',
  bodyClassName = '',
  accent = 'blue',
}) {
  const extraNode =
    typeof extra === 'string' ? (
      <Tag className="terminal-card-extra-tag">{extra}</Tag>
    ) : (
      extra
    )

  return (
    <div className={`terminal-card terminal-card--${accent} ${className}`.trim()}>
      <div className="card-header">
        <div className="card-title">
          <span className="title-bar" />
          {icon && <span className="card-title-icon">{icon}</span>}
          <div className="card-title-text">
            <span className="card-title-cn">{title}</span>
            {subtitle && (
              <Tooltip title={subtitle}>
                <span className="card-subtitle">{subtitle}</span>
              </Tooltip>
            )}
          </div>
        </div>
        {extra != null && extra !== '' && (
          <span className="card-extra">{extraNode}</span>
        )}
      </div>
      <div className={`card-body ${bodyClassName}`.trim()}>{children}</div>
    </div>
  )
}

export default TerminalCard
