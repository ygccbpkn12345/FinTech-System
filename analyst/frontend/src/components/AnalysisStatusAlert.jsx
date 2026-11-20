import { useEffect, useState } from 'react'
import { Alert } from 'antd'
import { CheckCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { ANALYSIS_RUNNING_MSG } from '@/api/analysisApi'

const SUCCESS_HIDE_MS = 4000

function AnalysisStatusAlert({ loading, analyzed, error, onCloseError }) {
  const [showSuccess, setShowSuccess] = useState(false)

  useEffect(() => {
    if (analyzed && !loading && !error) {
      setShowSuccess(true)
      const timer = setTimeout(() => setShowSuccess(false), SUCCESS_HIDE_MS)
      return () => clearTimeout(timer)
    }
    setShowSuccess(false)
  }, [analyzed, loading, error])

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message="分析请求失败"
        description={error}
        closable
        onClose={onCloseError}
        style={{ marginTop: 8 }}
      />
    )
  }

  if (loading) {
    return (
      <Alert
        type="info"
        showIcon
        icon={<LoadingOutlined spin />}
        message={ANALYSIS_RUNNING_MSG}
        style={{ marginTop: 8 }}
      />
    )
  }

  if (showSuccess) {
    return (
      <Alert
        type="success"
        showIcon
        icon={<CheckCircleOutlined />}
        message="分析完成"
        style={{ marginTop: 8 }}
      />
    )
  }

  return null
}

export default AnalysisStatusAlert
