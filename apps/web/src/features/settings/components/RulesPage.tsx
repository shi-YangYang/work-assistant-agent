import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import formFieldStyles from '../../../components/FormField.module.css'
import styles from './RulesPage.module.css'
import type { Rules, Schedule } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ConflictRecovery } from '@web/components/ConflictRecovery'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { PanelSection } from '@web/components/PanelSection'
import { TimeField } from '@web/components/TimeField'
import {
  readReportRules,
  reportRulesPath,
  saveReportRules,
} from '@web/features/settings/api/requests'
import { useResource } from '@web/hooks/useResource'
import { reportRuleErrors, revealRuleErrors } from '@web/features/settings/utils/rule-validation'
import { useWorkspace } from '@web/lib/workspace'
import { companyTimezones, timezoneLabel } from '@web/utils/timezones'
import { useLayoutEffect, useRef, useState } from 'react'

export function RulesPage() {
  const { data, error, refresh } = useResource<Rules>(reportRulesPath())
  const { identity, drafts, setDraft, notify } = useWorkspace()
  const value = (drafts.rules as Rules | undefined) ?? data
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const [attempted, setAttempted] = useState(0)
  const form = useRef<HTMLFormElement>(null)
  const fieldErrors = attempted && value ? reportRuleErrors(value) : {}
  useLayoutEffect(() => {
    if (attempted && form.current) revealRuleErrors(form.current)
  }, [attempted])
  const canEdit = identity.member.role === 'admin'
  const update = (kind: 'daily' | 'weekly', schedule: Schedule) => {
    if (value) setDraft('rules', { ...value, [kind]: schedule })
  }
  return (
    <div className={layoutStyles['settings-page']}>
      <h2>汇报规则</h2>
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      {value && !canEdit && (
        <div className={`${layoutStyles['sectioned-panel']} ${styles['rule-summary']}`}>
          <div className={`${layoutStyles['panel-intro']} ${utilitiesStyles['muted']}`}>
            公司时区：{timezoneLabel(value.timezone)}
          </div>
          {(['daily', 'weekly'] as const).map((kind) => (
            <PanelSection
              separated={kind === 'daily'}
              key={kind}
              title={kind === 'daily' ? '日报' : '周报'}
              status={value[kind].enabled ? '已启用' : '未启用'}
              defaultOpen={value[kind].enabled}
            >
              {value[kind].enabled ? (
                <dl className={styles['summary-grid']}>
                  <div className={layoutStyles['full-field']}>
                    <dt>周期</dt>
                    <dd>
                      {value[kind].days
                        .map((day) => ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][day])
                        .join('、')}
                    </dd>
                  </div>
                  <div>
                    <dt>草稿生成</dt>
                    <dd>{value[kind].generateTime}</dd>
                  </div>
                  <div>
                    <dt>提交截止</dt>
                    <dd>{value[kind].deadline}</dd>
                  </div>
                </dl>
              ) : (
                <p className={utilitiesStyles['muted']}>可在我的报告中手动准备报告。</p>
              )}
              {value[kind].enabled && (
                <p className={utilitiesStyles['muted']}>
                  {value[kind].reminders === false
                    ? '站内提醒已关闭'
                    : `草稿就绪、截止前 ${value[kind].beforeMinutes ?? 30} 分钟及逾期后提醒`}
                </p>
              )}
              {value.effectivePeriods?.[kind] && (
                <p className={utilitiesStyles['muted']}>
                  当前设置从 {value.effectivePeriods[kind]} 起的周期生效
                </p>
              )}
            </PanelSection>
          ))}
        </div>
      )}
      {value && canEdit && (
        <form
          ref={form}
          noValidate
          className={layoutStyles['sectioned-panel']}
          onSubmit={async (e) => {
            e.preventDefault()
            setAttempted((previous) => previous + 1)
            setFailure('')
            if (Object.keys(reportRuleErrors(value)).length) return
            setBusy(true)
            try {
              await saveReportRules({
                timezone: value.timezone,
                daily: value.daily,
                weekly: value.weekly,
                expectedRevision: value.revision,
              })
              setDraft('rules', undefined)
              refresh()
              notify('汇报规则已保存，从后续安排生效')
            } catch (e) {
              setFailure(e as Error)
            } finally {
              setBusy(false)
            }
          }}
        >
          <PanelSection title="时间设置" status={timezoneLabel(value.timezone)} defaultOpen>
            <label className={styles['timezone-field']}>
              公司时区
              <select
                value={value.timezone}
                disabled={!canEdit}
                onChange={(e) => setDraft('rules', { ...value, timezone: e.target.value })}
              >
                {[...new Set([...companyTimezones, value.timezone])].map((zone) => (
                  <option key={zone} value={zone}>
                    {timezoneLabel(zone)}
                  </option>
                ))}
              </select>
            </label>
          </PanelSection>
          {(['daily', 'weekly'] as const).map((kind) => (
            <PanelSection
              separated={kind === 'daily'}
              key={kind}
              title={kind === 'daily' ? '日报' : '周报'}
              status={
                value[kind].enabled
                  ? `${value[kind].generateTime} 生成 · ${value[kind].deadline} 截止`
                  : '未启用'
              }
              defaultOpen={kind === 'daily'}
            >
              <div className={styles['schedule-panel']}>
                <label className={`${layoutStyles['check']} ${styles['slot-check']}`}>
                  <input
                    type="checkbox"
                    checked={value[kind].enabled}
                    onChange={(e) => update(kind, { ...value[kind], enabled: e.target.checked })}
                  />
                  启用汇报安排
                </label>
                <div className={styles['weekdays']}>
                  {['一', '二', '三', '四', '五', '六', '日'].map((day, index) => (
                    <label key={day}>
                      <input
                        type={kind === 'weekly' ? 'radio' : 'checkbox'}
                        name={kind}
                        checked={value[kind].days.includes(index)}
                        aria-invalid={fieldErrors[`${kind}.days`] ? true : undefined}
                        aria-describedby={
                          fieldErrors[`${kind}.days`] ? `${kind}-days-error` : undefined
                        }
                        onChange={(e) =>
                          update(kind, {
                            ...value[kind],
                            days:
                              kind === 'weekly'
                                ? [index]
                                : e.target.checked
                                  ? [...value[kind].days, index].sort()
                                  : value[kind].days.filter((d) => d !== index),
                          })
                        }
                      />
                      <span>周{day}</span>
                    </label>
                  ))}
                </div>
                {fieldErrors[`${kind}.days`] && (
                  <small
                    className={formFieldStyles['form-field-error']}
                    id={`${kind}-days-error`}
                    role="alert"
                  >
                    {fieldErrors[`${kind}.days`]}
                  </small>
                )}
                <div className={layoutStyles['two-columns']}>
                  <label>
                    草稿生成时间
                    <TimeField
                      required={value[kind].enabled}
                      error={fieldErrors[`${kind}.generateTime`]}
                      value={value[kind].generateTime}
                      onChange={(time) => update(kind, { ...value[kind], generateTime: time })}
                    />
                  </label>
                  <label>
                    提交截止时间
                    <TimeField
                      required={value[kind].enabled}
                      error={fieldErrors[`${kind}.deadline`]}
                      value={value[kind].deadline}
                      onChange={(time) => update(kind, { ...value[kind], deadline: time })}
                    />
                  </label>
                </div>
                <div className={styles['reminder-settings']}>
                  <label className={`${layoutStyles['check']} ${styles['slot-check']}`}>
                    <input
                      type="checkbox"
                      checked={value[kind].reminders ?? true}
                      onChange={(e) =>
                        update(kind, { ...value[kind], reminders: e.target.checked })
                      }
                    />
                    站内提醒
                  </label>
                  <label className={formFieldStyles['form-field']}>
                    截止前提醒（分钟）
                    <input
                      type="number"
                      min={0}
                      max={1440}
                      step={1}
                      aria-invalid={fieldErrors[`${kind}.beforeMinutes`] ? true : undefined}
                      aria-describedby={
                        fieldErrors[`${kind}.beforeMinutes`] ? `${kind}-minutes-error` : undefined
                      }
                      disabled={value[kind].reminders === false}
                      value={value[kind].beforeMinutes ?? 30}
                      onChange={(e) =>
                        update(kind, { ...value[kind], beforeMinutes: Number(e.target.value) })
                      }
                    />
                    {fieldErrors[`${kind}.beforeMinutes`] && (
                      <small
                        className={formFieldStyles['form-field-error']}
                        id={`${kind}-minutes-error`}
                        role="alert"
                      >
                        {fieldErrors[`${kind}.beforeMinutes`]}
                      </small>
                    )}
                  </label>
                </div>
                {value.effectivePeriods?.[kind] && (
                  <p className={utilitiesStyles['muted']}>
                    当前设置从 {value.effectivePeriods[kind]} 起的周期生效
                  </p>
                )}
              </div>
            </PanelSection>
          ))}
          <div className={layoutStyles['panel-footer']}>
            <p className={utilitiesStyles['muted']}>
              时间按公司时区计算。修改后不重复生成历史周期，也不会改写已提交报告。
            </p>
            {failure instanceof ApiError && failure.status === 409 && canEdit && (
              <ConflictRecovery<Rules>
                load={() => readReportRules()}
                render={(latest) => (
                  <>
                    <p>公司时区：{timezoneLabel(latest.timezone)}</p>
                    {(['daily', 'weekly'] as const).map((kind) => (
                      <p key={kind}>
                        {kind === 'daily' ? '日报' : '周报'}：
                        {latest[kind].enabled
                          ? `${latest[kind].generateTime} 生成，${latest[kind].deadline} 截止`
                          : '自动生成未启用'}
                      </p>
                    ))}
                  </>
                )}
                keep={(latest) => {
                  setDraft('rules', { ...value, revision: latest.revision })
                  setFailure('')
                }}
                replace={(latest) => {
                  setDraft('rules', latest)
                  setFailure('')
                }}
              />
            )}
            <div className={`${layoutStyles['form-actions']} ${layoutStyles['editor-actions']}`}>
              <BusyButton busy={busy} className={controlsStyles['primary']}>
                保存汇报规则
              </BusyButton>
            </div>
          </div>
        </form>
      )}
    </div>
  )
}
