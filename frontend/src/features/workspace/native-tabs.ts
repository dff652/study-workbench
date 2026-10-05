export function wireWorkspaceTabs(root: HTMLElement, initial: string, onChange: (value: string) => void) {
  const groups = Array.from(root.querySelectorAll<HTMLElement>('[data-workspace-tabs]'))
  const select = (value: string, notify = false) => {
    for (const group of groups) {
      const buttons = Array.from(group.querySelectorAll<HTMLButtonElement>('[data-workspace-tab]'))
      const selected = buttons.find((button) => button.dataset.workspaceTab === value) || buttons[0]
      if (!selected) continue
      const panels = Array.from(root.querySelectorAll<HTMLElement>('[data-workspace-panel]'))
      for (const button of buttons) {
        const active = button === selected
        button.setAttribute('aria-selected', String(active))
        button.tabIndex = active ? 0 : -1
        const panel = panels.find((item) => item.id === button.getAttribute('aria-controls'))
        if (panel) panel.hidden = !active
      }
      if (notify) onChange(selected.dataset.workspaceTab || '')
    }
  }
  const click = (event: MouseEvent) => {
    const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('button[data-workspace-tab]') : null
    if (button && root.contains(button)) select(button.dataset.workspaceTab || '', true)
  }
  const keydown = (event: KeyboardEvent) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    const button = event.target instanceof HTMLButtonElement ? event.target : null
    const group = button?.closest<HTMLElement>('[data-workspace-tabs]')
    if (!button || !group) return
    const buttons = Array.from(group.querySelectorAll<HTMLButtonElement>('[data-workspace-tab]'))
    const index = buttons.indexOf(button)
    if (index < 0) return
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
    event.preventDefault()
    buttons[next]?.focus()
  }
  select(initial)
  root.addEventListener('click', click)
  root.addEventListener('keydown', keydown)
  return { select, dispose: () => { root.removeEventListener('click', click); root.removeEventListener('keydown', keydown) } }
}

export function revealWorkspacePanel(element: Element) {
  const panel = element.closest<HTMLElement>('[data-workspace-panel]')
  const root = panel?.closest('.workspace-page')
  if (!panel?.hidden || !root) return
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('[data-workspace-tab]'))
    .find((item) => item.getAttribute('aria-controls') === panel.id)
  button?.click()
}
