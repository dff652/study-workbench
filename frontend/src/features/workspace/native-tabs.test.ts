import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { revealWorkspacePanel, wireWorkspaceTabs } from './native-tabs'

describe('native workspace tabs', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('preserves form input, keyboard activation and the visible error panel', async () => {
    const user = userEvent.setup()
    document.body.innerHTML = `<div class="workspace-page"><div data-workspace-tabs role="tablist">
      <button type="button" role="tab" id="edit-tab" aria-controls="edit-panel" data-workspace-tab="edit">编辑</button>
      <button type="button" role="tab" id="history-tab" aria-controls="history-panel" data-workspace-tab="history">历史</button></div>
      <section id="edit-panel" role="tabpanel" aria-labelledby="edit-tab" data-workspace-panel><input value="尚未提交的内容"><p role="alert">来源尚未核定</p></section>
      <section id="history-panel" role="tabpanel" aria-labelledby="history-tab" data-workspace-panel>原历史</section></div>`
    const root = document.querySelector<HTMLElement>('.workspace-page')!
    const onChange = vi.fn()
    const tabs = wireWorkspaceTabs(root, 'edit', onChange)
    const buttons = root.querySelectorAll<HTMLButtonElement>('button')
    buttons[0].focus()
    await user.keyboard('{ArrowRight}')
    expect(document.activeElement).toBe(buttons[1])
    expect(buttons[1].getAttribute('aria-selected')).toBe('false')
    await user.keyboard('{Enter}')
    expect(root.querySelector<HTMLElement>('#edit-panel')?.hidden).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('history')
    revealWorkspacePanel(root.querySelector('[role="alert"]')!)
    expect(root.querySelector<HTMLElement>('#edit-panel')?.hidden).toBe(false)
    expect(root.querySelector('input')?.value).toBe('尚未提交的内容')
    expect(onChange).toHaveBeenLastCalledWith('edit')
    tabs.dispose()
  })
})
