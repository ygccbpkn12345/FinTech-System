import { Tag } from 'antd'

import { BranchesOutlined, NodeIndexOutlined } from '@ant-design/icons'

import { isFinalBranch } from '@/utils/workbenchDataUtils'
import { DisplayParagraphs } from '@/components/DisplayText'



function ManagerDecisionTree({ decisionTree = [] }) {

  const tree = Array.isArray(decisionTree) ? decisionTree : []

  const branches = tree.filter((n) => !isFinalBranch(n?.branch))

  const finalNode = tree.find((n) => isFinalBranch(n?.branch)) ?? tree[tree.length - 1]



  if (!tree.length) {

    return (

      <div className="cockpit-placeholder-body" style={{ minHeight: 80 }}>

        暂无经理决策树数据

      </div>

    )

  }



  return (

    <div className="manager-tree-viz">

      <div className="tree-root-node">

        <NodeIndexOutlined />

        <span>根节点：综合决策</span>

        <Tag className="tag-neutral">Decision Root</Tag>

      </div>



      <div className="tree-trunk" />



      <div className="tree-branches">

        {branches.map((node, index) => {

          const scoreChange = node?.scoreChange

          const branchName = node?.branch ?? `分支 ${index + 1}`

          return (

            <div key={`${branchName}-${index}`} className="tree-branch-node">

              <div className="tree-branch-connector">

                <span className="tree-branch-line" />

                <span className="tree-branch-dot" />

              </div>

              <div className="tree-branch-card">

                <div className="tree-branch-head">

                  <span className="tree-branch-index">{index + 1}</span>

                  <span className="tree-branch-name">{branchName}</span>

                  {scoreChange && (

                    <Tag

                      className={

                        /\+/.test(String(scoreChange)) && !String(scoreChange).includes('±')

                          ? 'tag-up'

                          : 'tag-neutral'

                      }

                    >

                      {scoreChange}

                    </Tag>

                  )}

                </div>

                <div className="tree-branch-row">

                  <span className="tree-field-label">触发</span>

                  <code className="manager-condition-code">{node?.condition ?? '--'}</code>

                </div>

                <div className="tree-branch-row">

                  <span className="tree-field-label">动作</span>

                  <strong className="tree-action-text">{node?.action ?? '--'}</strong>

                </div>

                {node?.rationale ? (

                  <DisplayParagraphs className="tree-branch-rationale" children={node.rationale} />

                ) : null}

              </div>

            </div>

          )

        })}

      </div>



      {finalNode && (

        <div className="tree-final-node">

          <BranchesOutlined />

          <div className="tree-final-content">

            <div className="tree-final-title">{finalNode.branch ?? '综合决策分支'}</div>

            <div className="tree-final-action">

              <Tag className="tag-up" style={{ fontSize: 14, padding: '4px 14px' }}>

                {finalNode.action ?? '--'} · 仓位 {finalNode.suggestedPosition ?? '--'}

              </Tag>

            </div>

            <div className="tree-final-condition">{finalNode.condition ?? '--'}</div>

            {finalNode.rationale ? (

              <DisplayParagraphs className="tree-final-rationale" children={finalNode.rationale} />

            ) : null}

          </div>

        </div>

      )}

    </div>

  )

}



export default ManagerDecisionTree

