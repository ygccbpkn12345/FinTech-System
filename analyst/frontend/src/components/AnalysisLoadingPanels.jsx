import { Col, Row, Skeleton } from 'antd'
import TerminalCard from './TerminalCard'
import AnalysisModuleStream from './AnalysisModuleStream'

function AnalysisLoadingPanels({ modules, currentNode, taskStatus, streamState }) {
  return (
    <>
      <TerminalCard title="行情层：市场概览" subtitle="Market Overview" extra="Loading">
        <Row gutter={[12, 12]}>
          {[1, 2, 3, 4].map((i) => (
            <Col key={i} xs={12} sm={6}>
              <Skeleton.Input active block style={{ height: 48 }} />
            </Col>
          ))}
        </Row>
      </TerminalCard>

      <TerminalCard title="行情层：K 线趋势" subtitle="Price Chart" extra="Loading">
        <Skeleton.Node active style={{ width: '100%', height: 280 }}>
          <div />
        </Skeleton.Node>
      </TerminalCard>

      <TerminalCard title="感知层：多分析师研判" subtitle="Perception Layer" extra="Loading">
        <AnalysisModuleStream
          modules={modules}
          currentNode={currentNode}
          taskStatus={taskStatus}
          streamState={streamState}
        />
      </TerminalCard>
    </>
  )
}

export default AnalysisLoadingPanels
