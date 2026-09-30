import { Component, useEffect, useState, type ComponentType, type ReactNode } from 'react'
import { PageLoading } from '@web/components/feedback/PageLoading'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'

const MIN_VISIBLE_DURATION = 300

type PageModule<Props> = { default: ComponentType<Props> }
type PageState<Props> =
  | { status: 'loading' }
  | { status: 'ready'; module: PageModule<Props> }
  | { status: 'error'; error: unknown }

class RouteFailure extends Component<
  { children: ReactNode; retry: () => void },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <ErrorNotice retry={this.props.retry} retryLabel="重新加载页面">
        页面未能加载，请检查网络后重试。
      </ErrorNotice>
    ) : (
      this.props.children
    )
  }
}

export function routePage<Props extends object>(load: () => Promise<PageModule<Props>>) {
  // Cache page code only; page state and account data remain owned by the mounted page.
  let loaded: PageModule<Props> | undefined
  let pending: Promise<PageModule<Props>> | undefined
  const loadModule = () => {
    if (loaded) return Promise.resolve(loaded)
    if (!pending)
      pending = Promise.resolve()
        .then(load)
        .then(
          (module) => {
            loaded = module
            pending = undefined
            return module
          },
          (error: unknown) => {
            pending = undefined
            throw error
          },
        )
    return pending
  }

  function DeferredPage(props: Props) {
    const [state, setState] = useState<PageState<Props>>({ status: 'loading' })
    useEffect(() => {
      let cancelled = false
      const visibleAt = performance.now()
      let finishTimer: ReturnType<typeof setTimeout> | undefined
      const finish = (next: PageState<Props>) => {
        if (cancelled) return
        const remaining = MIN_VISIBLE_DURATION - (performance.now() - visibleAt)
        if (remaining > 0) finishTimer = setTimeout(() => setState(next), remaining)
        else setState(next)
      }
      void loadModule().then(
        (module) => finish({ status: 'ready', module }),
        (error: unknown) => finish({ status: 'error', error }),
      )
      return () => {
        cancelled = true
        clearTimeout(finishTimer)
      }
    }, [])

    if (state.status === 'error') throw state.error
    if (state.status === 'loading') return <PageLoading />
    const Page = state.module.default
    return <Page {...props} />
  }

  return function RoutePage(props: Props) {
    const [attempt, setAttempt] = useState(0)
    return (
      <RouteFailure key={attempt} retry={() => setAttempt((value) => value + 1)}>
        <DeferredPage {...props} />
      </RouteFailure>
    )
  }
}
