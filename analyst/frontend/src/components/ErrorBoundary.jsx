import { Component } from 'react'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="terminal-card error-boundary-card" style={{ margin: 16 }}>
          <div className="card-header">
            <div className="card-title">
              <span className="title-bar" />
              <span>页面渲染异常</span>
            </div>
          </div>
          <div className="card-body">
            <p style={{ color: 'var(--text-secondary)', margin: '0 0 12px' }}>
              页面渲染异常，请检查后端返回数据格式。
            </p>
            <p
              style={{
                color: 'var(--color-up)',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                margin: 0,
                wordBreak: 'break-all',
              }}
            >
              {this.state.error?.message ?? 'Unknown error'}
            </p>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
