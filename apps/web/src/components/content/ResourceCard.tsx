import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import { Link, type To } from 'react-router'
import styles from '@web/styles/patterns/ResourceCard.module.css'

export type ResourceCardAction = { label: string } & (
  | { kind: 'route'; to: To; state?: unknown }
  | { kind: 'link'; href: string; download?: string }
  | { kind: 'button'; onClick: () => void; disabled?: boolean; busy?: boolean }
)

type ResourceCardProps = {
  as?: 'div' | 'section' | 'li'
  title: string
  titleAs?: 'strong' | 'h4' | 'span'
  icon: ReactNode
  status?: ReactNode
  subtitle?: ReactNode
  hoverSubtitle?: ReactNode
  primaryAction?: ResourceCardAction
  trailing?: ReactNode
  trailingAction?: {
    action: ResourceCardAction
    icon: ReactNode
    reveal?: 'always' | 'hover'
  }
  variant?: 'compact' | 'preview' | 'auto'
  /** Height of the main area including its border; footer controls remain outside clipping. */
  height?: number
  width?: CSSProperties['width']
  children?: ReactNode
  footer?: ReactNode
  tone?: 'default' | 'warning'
} & Omit<HTMLAttributes<HTMLElement>, 'title' | 'children' | 'onClick'>

function Action({
  action,
  className,
  children,
}: {
  action: ResourceCardAction
  className: string
  children: ReactNode
}) {
  const props = { className, 'aria-label': action.label }
  if (action.kind === 'route')
    return (
      <Link {...props} to={action.to} state={action.state}>
        {children}
      </Link>
    )
  if (action.kind === 'link')
    return (
      <a {...props} href={action.href} download={action.download}>
        {children}
      </a>
    )
  return (
    <button
      {...props}
      type="button"
      onClick={action.onClick}
      disabled={action.disabled}
      aria-busy={action.busy}
    >
      {children}
    </button>
  )
}

/** Presentational shell: callers own permissions, requests, errors, and action state. */
export function ResourceCard({
  as: Root = 'div',
  title,
  titleAs: Title = 'strong',
  icon,
  status,
  subtitle,
  hoverSubtitle,
  primaryAction,
  trailing,
  trailingAction,
  variant = 'compact',
  height,
  width,
  children,
  footer,
  tone = 'default',
  className = '',
  style,
  ...props
}: ResourceCardProps) {
  const TitleRow = Title === 'h4' ? 'div' : 'span'
  const heading = (
    <>
      <TitleRow className={styles.titleRow}>
        <Title className={styles.title} title={title}>
          {title}
        </Title>
        {status && <span className={styles.tag}>{status}</span>}
      </TitleRow>
      {(subtitle || hoverSubtitle) && (
        <span className={`${styles.meta} ${hoverSubtitle ? styles.switchSubtitle : ''}`}>
          <span className={hoverSubtitle ? styles.idleSubtitle : undefined}>{subtitle}</span>
          {hoverSubtitle && (
            <span className={styles.hoverSubtitle} aria-hidden="true">
              {hoverSubtitle}
            </span>
          )}
        </span>
      )}
    </>
  )
  return (
    <Root
      {...props}
      className={`${styles.card} ${className}`}
      data-variant={variant}
      data-interactive={!!primaryAction}
      data-tone={tone}
      style={
        {
          '--resource-card-height': `${height ?? 80}px`,
          width,
          ...style,
        } as CSSProperties
      }
    >
      <div className={styles.main}>
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
        <div className={styles.content}>
          {primaryAction ? (
            <Action action={primaryAction} className={styles.primary}>
              {heading}
            </Action>
          ) : (
            <div className={styles.heading}>{heading}</div>
          )}
          {children && <div className={styles.body}>{children}</div>}
        </div>
        {trailingAction ? (
          <span
            className={styles.accessory}
            data-reveal={trailingAction.reveal ?? 'always'}
            data-busy={trailingAction.action.kind === 'button' && !!trailingAction.action.busy}
          >
            <Action action={trailingAction.action} className={styles.action}>
              {trailingAction.icon}
            </Action>
          </span>
        ) : trailing ? (
          <span className={styles.trailing} aria-hidden="true">
            {trailing}
          </span>
        ) : null}
      </div>
      {footer && <div className={styles.footer}>{footer}</div>}
    </Root>
  )
}

export function ResourceCardGroup({
  as: Root = 'div',
  className = '',
  children,
  ...props
}: { as?: 'div' | 'ul'; children: ReactNode } & HTMLAttributes<HTMLElement>) {
  return (
    <Root {...props} className={`${styles.group} ${className}`}>
      {children}
    </Root>
  )
}
