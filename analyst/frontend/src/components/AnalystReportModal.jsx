import { Descriptions, Drawer, Progress, Tag } from 'antd'

import { FileTextOutlined } from '@ant-design/icons'

import { formatWeight, getSignalTag } from '@/utils/signalUtils'
import { DisplayParagraphs } from '@/components/DisplayText'



function AnalystReportModal({ analyst, open, onClose }) {

  if (!analyst) return null



  const signal = getSignalTag(analyst.signal)



  return (

    <Drawer

      title={

        <div className="analyst-modal-title">

          <FileTextOutlined style={{ color: 'var(--accent-cyan)' }} />

          <span>{analyst.name} · 详细报告</span>

        </div>

      }

      open={open}

      onClose={onClose}

      width={680}

      className="analyst-report-drawer"

      destroyOnClose

    >

      <div className="analyst-modal-meta">

        <Tag className="tag-neutral">{analyst.role}</Tag>

        <Tag className={signal.className}>{signal.label}</Tag>

        <span className="analyst-modal-conf">

          置信度 {formatWeight(analyst.confidence)}

        </span>

      </div>



      <Descriptions

        column={2}

        size="small"

        bordered

        className="analyst-modal-desc"

        style={{ marginBottom: 16 }}

        items={[

          {

            key: 'signal',

            label: '输出信号',

            children: <Tag className={signal.className}>{signal.label}</Tag>,

          },

          {

            key: 'confidence',

            label: '置信度',

            children: (

              <span style={{ fontFamily: 'var(--font-mono)' }}>

                {formatWeight(analyst.confidence)}

              </span>

            ),

          },

        ]}

      />



      <Progress

        percent={Math.round(analyst.confidence * 100)}

        strokeColor={{ from: '#c8161d', to: '#e93030' }}

        style={{ marginBottom: 20 }}

      />



      <div className="analyst-modal-section">

        <div className="analyst-modal-section-title">核心结论</div>

        <DisplayParagraphs className="analyst-modal-summary" children={analyst.summary} />

      </div>



      <div className="analyst-modal-section">

        <div className="analyst-modal-section-title">详细分析</div>

        <DisplayParagraphs className="analyst-modal-report" children={analyst.report} />

      </div>



      <div className="analyst-modal-section">

        <div className="analyst-modal-section-title">使用的数据</div>

        <div className="analyst-modal-data">

          {(analyst.dataUsed ?? []).map((d) => (

            <Tag key={d} className="tag-neutral">

              {d}

            </Tag>

          ))}

        </div>

      </div>

    </Drawer>

  )

}



export default AnalystReportModal

