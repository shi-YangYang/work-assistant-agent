import type { ReactNode } from 'react'
import type { SummaryCitation, SummaryContent } from '../shared/summary-contracts'

export function MinutesAnalysis({
  content,
  references,
}: {
  content: SummaryContent
  references: (ids: string[]) => ReactNode
}): React.JSX.Element {
  const citedList = (field: string, items: (string | SummaryCitation)[]): ReactNode => (
    <ul>
      {items.map((item, index) => (
        <li data-summary-location={`${field}:${index}`} key={index}>
          {typeof item === 'string' ? item : item.text}
          {typeof item !== 'string' && references(item.sources)}
        </li>
      ))}
    </ul>
  )
  const rich = content.version === 2 ? content : null
  return (
    <>
      <h4>{rich ? '会议概览与议题' : '会议摘要'}</h4>
      <p data-summary-location="abstract" className="minutes-abstract">
        {content.abstract}
        {rich && references(rich.overviewSources)}
      </p>
      {!!content.topics.length && (
        <>
          <h5>{rich ? '议题进展' : '讨论要点'}</h5>
          {citedList('topics', content.topics)}
        </>
      )}
      {!!rich?.speakerSummaries.length && (
        <section className="minutes-analysis-section" aria-label="发言人摘要">
          <h4>发言人摘要</h4>
          {rich.speakerSummaries.map((speaker, index) => (
            <div data-summary-location={`speakerSummaries:${index}`} key={speaker.speakerId}>
              <h5>{speaker.name}</h5>
              {!!speaker.points.length && (
                <ul>
                  {speaker.points.map((point, pointIndex) => (
                    <li key={pointIndex}>
                      {point.text}
                      {references(point.sources)}
                    </li>
                  ))}
                </ul>
              )}
              {!!speaker.commitments.length && (
                <>
                  <span className="minutes-detail-label">明确承诺</span>
                  <ul>
                    {speaker.commitments.map((commitment, commitmentIndex) => (
                      <li key={commitmentIndex}>
                        {commitment.text}
                        {references(commitment.sources)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          ))}
        </section>
      )}
      {!!(content.decisions.length || rich?.agreements.length || rich?.disagreements.length) && (
        <section className="minutes-analysis-section" aria-label="共识、决策与分歧">
          <h4>{rich ? '共识、决策与分歧' : '明确决策'}</h4>
          {!!rich?.agreements.length && (
            <>
              <h5>共识</h5>
              {citedList('agreements', rich.agreements)}
            </>
          )}
          {!!content.decisions.length && (
            <>
              {rich && <h5>明确决策</h5>}
              {citedList('decisions', content.decisions)}
            </>
          )}
          {!!rich?.disagreements.length && (
            <>
              <h5>分歧与未定事项</h5>
              {citedList('disagreements', rich.disagreements)}
            </>
          )}
        </section>
      )}
      {!!content.actions.length && (
        <section className="minutes-analysis-section" aria-label="行动项">
          <h4>行动项</h4>
          <ul className="minutes-actions">
            {content.actions.map((item, index) => (
              <li data-summary-location={`actions:${index}`} key={index}>
                <strong>{item.task}</strong>
                <p>
                  负责人：{item.owner ?? '待确认'} · 截止：{item.deadline ?? '待确认'} · 状态：
                  {item.status ?? '待确认'}
                </p>
                {'dependencies' in item && (
                  <p>
                    依赖：{item.dependencies ?? '待确认'} · 阻碍：{item.blocker ?? '待确认'}
                  </p>
                )}
                {references(item.sources)}
              </li>
            ))}
          </ul>
        </section>
      )}
      {!!(content.risks.length || content.openQuestions.length) && (
        <section className="minutes-analysis-section" aria-label="风险与待确认">
          <h4>风险与待确认</h4>
          {!!content.risks.length && (
            <>
              <h5>风险</h5>
              {citedList('risks', content.risks)}
            </>
          )}
          {!!content.openQuestions.length && (
            <>
              <h5>待确认问题</h5>
              {citedList('openQuestions', content.openQuestions)}
            </>
          )}
        </section>
      )}
      {!!rich?.suggestions.length && (
        <section className="minutes-analysis-section minutes-suggestions" aria-label="后续建议">
          <h4>
            后续建议 <span className="minutes-ai-label">AI 建议</span>
          </h4>
          {citedList('suggestions', rich.suggestions)}
        </section>
      )}
    </>
  )
}
