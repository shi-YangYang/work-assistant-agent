import controlsStyles from '../../../styles/controls.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import recordLayoutStyles from '../../../components/RecordLayout.module.css'
import statusStyles from '../../../components/Status.module.css'
import teamStyles from '../styles/team.module.css'
import type { TeamWorkspacePage } from '@paa/api-contracts'
import { RecordEmpty } from '@web/components/RecordEmpty'
import { Status } from '@web/components/Status'
import { obligationLabel } from '@web/features/reports/utils/obligations'
import { isWork, type TeamRow as Row } from '@web/features/team/types'
import { dateLabel } from '@web/utils/date'
import { BriefcaseBusiness, ChevronRight, ClipboardCheck } from 'lucide-react'

export function TeamResults({
  data,
  list,
  view,
  scope,
  params,
  status,
  update,
  open,
}: {
  data: TeamWorkspacePage<Row> | null
  list: { data: TeamWorkspacePage<Row> | null; error: string | Error; refresh: () => void }
  view: 'reports' | 'work'
  scope: 'updated' | 'current'
  params: URLSearchParams
  status: string
  update: (values: Record<string, string>, reset?: boolean) => void
  open: (row: Row, replace?: boolean) => void
}) {
  return (
    <div className={teamStyles['team-results']}>
      {!data && !list.error && (
        <p className={recordLayoutStyles['records-loading']} role="status">
          正在读取团队记录…
        </p>
      )}
      {data && (
        <div className={teamStyles['team-result-caption']}>
          <span>
            {view === 'work'
              ? scope === 'current'
                ? '当前工作状态'
                : '期间更新 · 截至所选期末的状态'
              : '所选周期的汇报'}{' '}
            · {data.total} 条
          </span>
          {(params.get('q') || params.get('member') || status) && (
            <button
              className={`${controlsStyles['text-button']} ${teamStyles['slot-text-button']}`}
              onClick={() => update({ q: '', member: '', [`${view}Status`]: '' })}
            >
              清除筛选
            </button>
          )}
        </div>
      )}
      {data?.items.length ? (
        <div>
          {data.items.map((row) => (
            <div className={teamStyles['team-record']} key={row.id}>
              <button
                className={teamStyles['team-member']}
                title={`只看${row.member.name}`}
                onClick={() => update({ member: row.member.id })}
              >
                <span className={`${layoutStyles['avatar']} ${teamStyles['slot-avatar']}`}>
                  {row.member.name.slice(0, 1)}
                </span>
                <span>
                  {row.member.name}
                  {!row.member.active && (
                    <small>{row.member.deleted ? '账号已删除' : '已停用'}</small>
                  )}
                </span>
              </button>
              {isWork(row) ? (
                <button className={teamStyles['team-record-content']} onClick={() => open(row)}>
                  <div className={teamStyles['team-record-title']}>
                    <h3>{row.work.title}</h3>
                    <Status value={row.work.status} />
                  </div>
                  <p>{row.work.summary || '暂无工作说明'}</p>
                  {row.work.blocker && row.work.status !== 'done' && (
                    <small className={teamStyles['team-blocker']}>阻碍：{row.work.blocker}</small>
                  )}
                  <div className={teamStyles['team-record-meta']}>
                    <span>
                      {scope === 'updated' ? '更新于' : '最近更新'} {dateLabel(row.work.updatedAt)}
                    </span>
                    {row.work.dueDate && <span>截止 {row.work.dueDate}</span>}
                    <span className={teamStyles['team-read']}>
                      查看工作
                      <ChevronRight size={15} />
                    </span>
                  </div>
                </button>
              ) : (
                <div className={teamStyles['team-report-content']}>
                  <div className={teamStyles['team-record-title']}>
                    <h3>
                      {row.period}
                      {row.kind === 'weekly' ? ` — ${row.periodEnd}` : ''}
                      <small>{row.kind === 'daily' ? '日报' : '周报'}</small>
                    </h3>
                    <span className={statusStyles['status']} data-status={row.state}>
                      {obligationLabel(row.state)}
                    </span>
                  </div>
                  <p>
                    {row.summary ||
                      (row.state === 'cancelled' ? '该周期的汇报安排已撤销' : '尚未提交报告')}
                  </p>
                  <div className={teamStyles['team-record-meta']}>
                    <span>
                      {row.submittedAt
                        ? `提交于 ${dateLabel(row.submittedAt)}`
                        : row.deadlineAt
                          ? `截止 ${new Intl.DateTimeFormat('zh-CN', { timeZone: row.timezone, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(row.deadlineAt))}`
                          : ''}
                    </span>
                    {!row.scheduled && row.reportId && <span>自主提交</span>}
                    {row.reportId && (
                      <button
                        className={`${controlsStyles['text-button']} ${teamStyles['slot-text-button']} ${teamStyles['team-read']}`}
                        onClick={() => open(row)}
                      >
                        查看报告
                        <ChevronRight size={15} />
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        data && (
          <RecordEmpty
            className={teamStyles['team-empty']}
            icon={view === 'work' ? <BriefcaseBusiness size={27} /> : <ClipboardCheck size={27} />}
            title={view === 'work' ? '暂无符合条件的工作' : '暂无符合条件的汇报'}
          >
            {view === 'work'
              ? '员工创建或确认工作后，会显示在这里。'
              : '可以调整日期，查看其他周期的汇报安排与已提交报告。'}
          </RecordEmpty>
        )
      )}
    </div>
  )
}
