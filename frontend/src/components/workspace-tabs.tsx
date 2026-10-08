import type { KeyboardEvent, ReactNode } from 'react'
import { cn } from '../lib/utils'

export type WorkspaceTab = { value: string; label: string; count?: number }

export function WorkspaceTabs({ id, label, tabs, value, onChange }: {
  id: string
  label: string
  tabs: readonly WorkspaceTab[]
  value: string
  onChange: (value: string) => void
}) {
  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    if (!buttons?.length) return
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
    event.preventDefault()
    buttons[next]?.focus()
  }

  return <div role='tablist' aria-label={label} className='flex flex-wrap gap-x-5 gap-y-1 border-b'>
    {tabs.map((tab, index) => <button
      key={tab.value}
      type='button'
      role='tab'
      id={`${id}-${tab.value}-tab`}
      aria-controls={`${id}-${tab.value}-panel`}
      aria-selected={value === tab.value}
      tabIndex={value === tab.value ? 0 : -1}
      className={cn('inline-flex min-h-10 items-center gap-2 border-b-2 px-0.5 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring', value === tab.value ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}
      onClick={() => onChange(tab.value)}
      onKeyDown={(event) => moveFocus(event, index)}
    >{tab.label}{tab.count !== undefined ? <span className='text-xs tabular-nums text-muted-foreground'>{tab.count}</span> : null}</button>)}
  </div>
}

export function WorkspacePanel({ id, value, active, children, className }: {
  id: string
  value: string
  active: string
  children: ReactNode
  className?: string
}) {
  return <section id={`${id}-${value}-panel`} role='tabpanel' aria-labelledby={`${id}-${value}-tab`} hidden={active !== value} className={cn('min-w-0 space-y-4', className)}>{children}</section>
}

export function WorkspaceHeading({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  return <header className='flex flex-wrap items-center justify-between gap-3'>
    <h2 className='min-w-0 break-words font-semibold' style={{ fontSize: 'var(--type-section, 1.125rem)' }}>{title}</h2>
    {actions ? <div className='flex flex-wrap items-center gap-2'>{actions}</div> : null}
  </header>
}
