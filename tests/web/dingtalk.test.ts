import type { Member } from '@paa/api-contracts'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'
import { composerDraftLifecycle } from '../../apps/web/src/features/assistant/lib/composer-drafts'
import {
  dingtalkDraftSummary,
  dingtalkResult,
  officialDingTalkUrl,
} from '../../apps/web/src/features/auth/utils/dingtalk-flow'
import { DingTalkAccountPage } from '../../apps/web/src/features/settings/components/AccountPage'
import { SessionDrafts } from '../../apps/web/src/lib/session-drafts'

it('only accepts the fixed official authorization page before leaving the app', () => {
  expect(officialDingTalkUrl('https://login.dingtalk.com/oauth2/auth?state=controlled')).toBe(
    'https://login.dingtalk.com/oauth2/auth?state=controlled',
  )
  for (const url of [
    'https://evil.test/oauth2/auth',
    'https://login.dingtalk.com.evil.test/oauth2/auth',
    'http://login.dingtalk.com/oauth2/auth',
    'https://user:secret@login.dingtalk.com/oauth2/auth',
    'https://login.dingtalk.com/other',
    'javascript:alert(1)',
  ])
    expect(() => officialDingTalkUrl(url)).toThrow()
})

it('uses fixed callback messages and never echoes provider errors or arbitrary request IDs', () => {
  expect(dingtalkResult('?dingtalk=failed&reason=cancelled')?.message).toContain('取消')
  expect(dingtalkResult('?dingtalk=failed&reason=denied')?.message).toContain('本公司')
  expect(dingtalkResult('?dingtalk=failed&reason=permission')?.message).toContain(
    '尚未开通所需接口权限',
  )
  expect(dingtalkResult('?dingtalk=failed&reason=upstream-secret&requestId=secret')).toEqual({
    failed: true,
    message: '钉钉授权未完成，请重新发起。',
    requestId: null,
  })
  expect(dingtalkResult('?dingtalk=verified')?.failed).toBe(false)
  expect(dingtalkResult('')).toBeNull()
})

it('exposes pending text and attachment count for the external-login guard after session expiry without modifying drafts', () => {
  const vault = new SessionDrafts(composerDraftLifecycle)
  vault.writer()('composer:new', {
    text: '未发送的工作内容',
    files: [{ url: 'blob:controlled' }],
    sending: false,
  })
  vault.writer()('composer:older', { text: '另一份草稿', files: [], sending: false })
  vault.suspend()
  const before = vault.getSnapshot()
  expect(dingtalkDraftSummary(before)).toEqual({
    hasDrafts: true,
    text: '未发送的工作内容\n\n另一份草稿',
    files: 1,
  })
  expect(vault.getSnapshot()).toBe(before)
  expect(dingtalkDraftSummary({})).toEqual({ hasDrafts: false, text: '', files: 0 })
})

it.each([false, true])(
  'shows the copyable account and password controls for hasPassword=%s',
  (hasPassword) => {
    const member: Member = {
      id: 'm',
      name: '员工',
      username: 'dd_controlled',
      role: 'employee',
      active: true,
      mustChangePassword: false,
      hasPassword,
    }
    const html = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        {},
        createElement(DingTalkAccountPage, { member, onLogout: () => {} }),
      ),
    )
    expect(html).toContain('dd_controlled')
    expect(html).toContain('复制账号')
    expect(html).toContain(hasPassword ? '已设置密码' : '未设置密码')
    expect(html.includes('name="current"')).toBe(hasPassword)
    if (!hasPassword) expect(html).toContain('disabled=""')
  },
)
