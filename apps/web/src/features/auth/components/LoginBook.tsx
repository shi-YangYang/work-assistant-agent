import { useBookOpening } from '@web/features/auth/hooks/useBookOpening'
import type { ReactNode } from 'react'

export function LoginBook({
  children,
  initiallyOpen,
  busy,
  onClose,
}: {
  children: ReactNode
  initiallyOpen: boolean
  busy: boolean
  onClose: () => void
}) {
  const { phase, instant, hostRef, openRef, closeRef, open, close } = useBookOpening(
    initiallyOpen,
    busy,
    onClose,
  )
  const opened = phase === 'opening' || phase === 'open'
  const ready = phase === 'open'
  return (
    <div
      className={`book-login${opened ? ' is-open' : ''}${ready ? ' is-ready' : ''}${instant ? ' is-instant' : ''}`}
      data-state={phase}
      onKeyDown={(event) => {
        if (
          event.key === 'Escape' &&
          !event.defaultPrevented &&
          !(event.target as HTMLElement).closest('dialog')
        ) {
          close()
        }
      }}
    >
      <header className="masthead">
        <button className="wordmark" type="button" onClick={close} disabled={busy}>
          公司工作助手
          <span className="wordmark-line" aria-hidden="true" />
          <span className="wordmark-en">WORK ASSISTANT</span>
        </button>
        <button
          className="quiet-button"
          type="button"
          hidden={phase !== 'closed'}
          onClick={() => open(true)}
        >
          直接登录 <span aria-hidden="true">↗</span>
        </button>
        <button
          className="quiet-button"
          type="button"
          ref={closeRef}
          hidden={phase === 'closed'}
          disabled={!ready || busy}
          onClick={close}
        >
          <span aria-hidden="true">↶</span> 合上书本
        </button>
      </header>
      <main className="book-main">
        <div className="top-note" aria-hidden="true">
          <span className="chapter-dot" />
          <span>{opened ? 'YOUR WORK, IN FOCUS' : 'A NEW CHAPTER BEGINS'}</span>
        </div>
        <section className="scene" aria-label="公司工作助手登录">
          <div className="book-shadow" aria-hidden="true" />
          <div className="book">
            <div className="back-board" aria-hidden="true" />
            <div className="page-stack" aria-hidden="true" />
            <section className="right-page" aria-label="登录书页" inert={!ready}>
              <div className="page-running-head" aria-hidden="true">
                <span>工作助手</span>
                <span>YOUR NEXT CHAPTER</span>
              </div>
              <div className="login-host" id="book-login-form" ref={hostRef}>
                {children}
              </div>
              <div className="page-number" aria-hidden="true">
                01
              </div>
            </section>
            <div className="cover">
              <button
                className="cover-front"
                type="button"
                inert={phase !== 'closed'}
                aria-label="打开书本，进入登录页"
                aria-expanded={opened}
                aria-controls="book-login-form"
                onClick={() => open()}
              >
                <span className="cover-border" aria-hidden="true" />
                <span className="cover-edition">THE WORK EDITION</span>
                <span className="cover-title">
                  Good work
                  <br />
                  begins with
                  <br />
                  <em>you.</em>
                </span>
                <span className="cover-rule" aria-hidden="true" />
                <span className="cover-subtitle">让每一份工作，都有回应。</span>
                <span className="cover-bottom">
                  <span>工作助手</span>
                  <span>VOL. 01</span>
                </span>
              </button>
              <section className="cover-back" aria-label="欢迎书页" inert={!ready}>
                <span className="inside-eyebrow">A NOTE TO YOU</span>
                <div className="welcome-copy">
                  <span className="welcome-pretitle">翻开工作的新一页。</span>
                  <h2 className="welcome-title">
                    让想法，
                    <br />
                    成为清晰的
                    <br />
                    <em>下一步。</em>
                  </h2>
                  <p>
                    欢迎回来。
                    <br />
                    记录进展，梳理工作，
                    <br />
                    和团队一起，把事情做好。
                  </p>
                </div>
                <div className="inside-signoff">
                  <span>From ideas to progress.</span>
                  <span className="signature">Work Assistant</span>
                </div>
              </section>
            </div>
            <div className="ribbon" aria-hidden="true" />
          </div>
        </section>
        <div className="below-book">
          <button
            className="open-button"
            type="button"
            ref={openRef}
            hidden={phase !== 'closed'}
            onClick={() => open()}
          >
            <span className="book-icon" aria-hidden="true">
              ⌑
            </span>
            翻开，开启新一章{' '}
            <span className="open-arrow" aria-hidden="true">
              ↗
            </span>
          </button>
          <p className="cover-hint" hidden={phase !== 'closed'}>
            也可以轻触封面
          </p>
          <p className="open-hint" hidden={!ready}>
            每次回来，都是新的开始。
          </p>
        </div>
      </main>
      <footer className="site-footer">
        <span>YOUR WORK, IN FOCUS.</span>
        <div className="stage-indicator" aria-label={opened ? '当前步骤：登录' : '当前步骤：封面'}>
          <span className={!opened ? 'active' : ''}>01 封面</span>
          <i aria-hidden="true" />
          <span className={opened ? 'active' : ''}>02 登录</span>
        </div>
        <span className="project-label">WORK-ASSISTANT-AGENT</span>
      </footer>
      <p className="sr-only" role="status" aria-live="polite">
        {ready
          ? '登录页已打开。'
          : phase === 'closed'
            ? '点击封面或翻开按钮进入登录页。'
            : phase === 'opening'
              ? '正在翻开书本。'
              : '正在合上书本。'}
      </p>
    </div>
  )
}
