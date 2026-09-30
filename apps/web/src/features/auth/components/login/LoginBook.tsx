import brandMark from '@paa/ui-web/mark.png'
import styles from './LoginBook.module.css'
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
      className={styles['book-login']}
      data-open={opened}
      data-ready={ready}
      data-instant={instant}
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
      <header className={styles['masthead']}>
        <button className={styles['wordmark']} type="button" onClick={close} disabled={busy}>
          Noria
          <span className={styles['wordmark-line']} aria-hidden="true" />
          <span className={styles['wordmark-en']}>YOUR AI COMPANION</span>
        </button>
        <button
          className={styles['quiet-button']}
          type="button"
          hidden={phase !== 'closed'}
          onClick={() => open(true)}
        >
          直接登录 <span aria-hidden="true">↗</span>
        </button>
        <button
          className={styles['quiet-button']}
          type="button"
          ref={closeRef}
          hidden={phase === 'closed'}
          disabled={!ready || busy}
          onClick={close}
        >
          <span aria-hidden="true">↶</span> 合上书本
        </button>
      </header>
      <main className={styles['book-main']}>
        <div className={styles['top-note']} aria-hidden="true">
          <span className={styles['chapter-dot']} />
          <span>{opened ? 'WELCOME ABOARD' : 'A NEW CHAPTER BEGINS'}</span>
        </div>
        <section className={styles['scene']} aria-label="Noria 登录">
          <div className={styles['book-shadow']} aria-hidden="true" />
          <div className={styles['book']}>
            <div className={styles['back-board']} aria-hidden="true" />
            <div className={styles['page-stack']} aria-hidden="true" />
            <section className={styles['right-page']} aria-label="登录书页" inert={!ready}>
              <div className={styles['page-running-head']} aria-hidden="true">
                <span>Noria</span>
                <span>YOUR NEXT CHAPTER</span>
              </div>
              <div className={styles['login-host']} id="book-login-form" ref={hostRef}>
                {children}
              </div>
              <div className={styles['page-number']} aria-hidden="true">
                01
              </div>
            </section>
            <div className={styles['cover']}>
              <button
                className={styles['cover-front']}
                type="button"
                inert={phase !== 'closed'}
                aria-label="打开书本，进入登录页"
                aria-expanded={opened}
                aria-controls="book-login-form"
                onClick={() => open()}
              >
                <span className={styles['cover-border']} aria-hidden="true" />
                <span className={styles['ribbon']} aria-hidden="true" />
                <span className={styles['cover-brand']}>
                  <img src={brandMark} className={styles['cover-logo']} alt="" aria-hidden="true" />
                  <span className={styles['cover-edition']}>YOUR PERSONAL ARK</span>
                </span>
                <span className={styles['cover-title']}>
                  A little ark
                  <br />
                  for your
                  <br />
                  <em>ideas.</em>
                </span>
                <span className={styles['cover-rule']} aria-hidden="true" />
                <span className={styles['cover-subtitle']}>载着想法，陪你向前。</span>
                <span className={styles['cover-bottom']}>
                  <span>Noria</span>
                  <span>VOL. 01</span>
                </span>
              </button>
              <section className={styles['cover-back']} aria-label="欢迎书页" inert={!ready}>
                <span className={styles['inside-eyebrow']}>A NOTE TO YOU</span>
                <div className={styles['welcome-copy']}>
                  <span className={styles['welcome-pretitle']}>欢迎登上你的方舟。</span>
                  <h2 className={styles['welcome-title']}>
                    让想法，
                    <br />
                    有处安放，
                    <br />
                    <em>有人同行。</em>
                  </h2>
                  <p>
                    我是 Noria，你的 AI 伙伴。
                    <br />
                    帮你理清思路，接住灵感，
                    <br />
                    一起把想法变成行动。
                  </p>
                </div>
                <div className={styles['inside-signoff']}>
                  <span>Your ideas, our journey.</span>
                  <span className={styles['signature']}>Noria</span>
                </div>
              </section>
            </div>
          </div>
        </section>
        <div className={styles['below-book']}>
          <button
            className={styles['open-button']}
            type="button"
            ref={openRef}
            hidden={phase !== 'closed'}
            onClick={() => open()}
          >
            <span className={styles['book-icon']} aria-hidden="true">
              ⌑
            </span>
            翻开，和 Noria 一起出发{' '}
            <span className={styles['open-arrow']} aria-hidden="true">
              ↗
            </span>
          </button>
          <p className={styles['cover-hint']} hidden={phase !== 'closed'}>
            也可以轻触封面
          </p>
          <p className={styles['open-hint']} hidden={!ready}>
            你的下一程，有我同行。
          </p>
        </div>
      </main>
      <footer className={styles['site-footer']}>
        <span>YOUR IDEAS, OUR JOURNEY.</span>
        <div
          className={styles['stage-indicator']}
          aria-label={opened ? '当前步骤：登录' : '当前步骤：封面'}
        >
          <span data-active={!opened}>01 封面</span>
          <i aria-hidden="true" />
          <span data-active={opened}>02 登录</span>
        </div>
        <span className={styles['project-label']}>NORIA</span>
      </footer>
      <p className={'sr-only'} role="status" aria-live="polite">
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
