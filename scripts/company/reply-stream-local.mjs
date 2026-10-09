import { createInfra, rejectLegacy } from './local-infra/compose.mjs'
import { createLifecycle } from './local-infra/lifecycle.mjs'

export function replyStreamConfig(values) {
  const url = values.PAA_REPLY_STREAM_REDIS_URL || 'redis://127.0.0.1:6379/0'
  const address = new URL(url)
  const local =
    address.protocol === 'redis:' &&
    !address.username &&
    !address.password &&
    ['127.0.0.1', 'localhost'].includes(address.hostname) &&
    (!address.port || address.port === String(values.PAA_LOCAL_REDIS_PORT || 6379))
  return { url, local }
}

export async function startLocalReplyStream({ signal, infra, lifecycle } = {}) {
  infra ??= await createInfra()
  const { url, local } = replyStreamConfig(infra.values)
  if (!local) return { url, stop: async () => {} }
  const own = !lifecycle
  lifecycle ??= await createLifecycle(infra, { signal })
  try {
    await rejectLegacy(infra, signal, ['redis'])
    await lifecycle.start('redis', 30)
    console.log('本地正文流 Redis 已就绪。')
    return { url, stop: own ? lifecycle.stop : async () => {} }
  } catch (error) {
    if (own) await lifecycle.stop()
    throw error
  }
}
