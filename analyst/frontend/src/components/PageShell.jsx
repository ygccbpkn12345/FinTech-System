import { Breadcrumb, Typography } from 'antd'

function PageShell({ title, subtitle, breadcrumbItems = [], extra, children, className = '' }) {
  return (
    <div className={`page-shell ${className}`.trim()}>
      <div className="page-shell-header">
        {breadcrumbItems.length > 0 && (
          <Breadcrumb className="page-shell-breadcrumb" items={breadcrumbItems} />
        )}
        <div className="page-shell-title-row">
          <div>
            <Typography.Title level={4} className="page-shell-title">
              {title}
            </Typography.Title>
            {subtitle && (
              <Typography.Text type="secondary" className="page-shell-subtitle">
                {subtitle}
              </Typography.Text>
            )}
          </div>
          {extra && <div className="page-shell-extra">{extra}</div>}
        </div>
      </div>
      <div className="page-shell-body">{children}</div>
    </div>
  )
}

export default PageShell
