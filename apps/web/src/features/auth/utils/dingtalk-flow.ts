import type { Composer } from '@web/features/assistant/lib/audio-capture'
import type { DraftStore } from '@web/lib/workspace'

export function dingtalkResult(search: string) {
  const params = new URLSearchParams(search)
  const status = params.get('dingtalk')
  if (!status || status === 'logged-in') return null
  const success: Record<string, string> = {
    bound: '钉钉已绑定，其他设备需要重新登录。',
    verified: '钉钉身份验证成功。密码验证 5 分钟内有效，且只能使用一次。',
  }
  const failures: Record<string, string> = {
    cancelled: '已取消钉钉授权。你可以重新发起，或使用账号密码登录。',
    expired: '钉钉授权已过期或失效，请重新发起。',
    unavailable: '钉钉登录暂不可用，请稍后重试或联系管理员检查配置。',
    permission: '钉钉应用尚未开通所需接口权限。请联系管理员在钉钉后台开通权限并发布应用后重试。',
    denied: '无法确认你是本公司允许登录的有效成员，或授权身份与当前账号不符。请联系管理员检查。',
    conflict: '这个钉钉身份已绑定其他账号，或应用身份发生冲突。请联系管理员处理。',
    failed: '钉钉授权未完成，请重新发起。',
  }
  const id = params.get('requestId')
  return {
    failed: status === 'failed' || !success[status],
    message: success[status] ?? failures[params.get('reason') ?? 'failed'] ?? failures.failed,
    requestId: id && /^[0-9a-f-]{36}$/i.test(id) ? id : null,
  }
}

export function dingtalkDraftSummary(drafts: DraftStore) {
  const composers = Object.entries(drafts)
    .filter(([key]) => key.startsWith('composer:'))
    .map(([, value]) => value as Composer)
  const texts = composers.map((draft) => draft.text).filter((text) => text?.trim())
  return {
    hasDrafts: Object.keys(drafts).length > 0,
    text: texts.join('\n\n'),
    files: composers.reduce((sum, draft) => sum + draft.files.length, 0),
  }
}

export function officialDingTalkUrl(value: string) {
  const url = new URL(value)
  if (
    url.origin !== 'https://login.dingtalk.com' ||
    url.pathname !== '/oauth2/auth' ||
    url.username ||
    url.password ||
    url.hash
  )
    throw new Error('授权地址无效，请刷新后重试。')
  return url.href
}
