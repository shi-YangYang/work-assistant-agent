import { createInfra, rejectLegacy } from './local-infra/compose.mjs'
import { createLifecycle } from './local-infra/lifecycle.mjs'

export function usesLocalDatabase(values) {
  const address = new URL(
    values.DATABASE_URL || 'postgresql://paa:local@127.0.0.1:5432/paa_company',
  )
  return (
    ['localhost', '127.0.0.1'].includes(address.hostname) &&
    (!address.port || address.port === String(values.PAA_LOCAL_POSTGRES_PORT || 5432)) &&
    !address.searchParams.has('host') &&
    !address.searchParams.has('port')
  )
}

export async function startLocalDatabase({ signal, infra, lifecycle } = {}) {
  infra ??= await createInfra()
  if (!usesLocalDatabase(infra.values)) return
  const own = !lifecycle
  lifecycle ??= await createLifecycle(infra, { signal })
  try {
    await rejectLegacy(infra, signal, ['postgres'])
    await lifecycle.start('postgres')
    console.log('本地数据库已就绪。')
  } finally {
    if (own) await lifecycle.stop()
  }
}
