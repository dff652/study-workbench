import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { WorkspacePanel, WorkspaceTabs } from './workspace-tabs'

function WorkArea() {
  const [tab, setTab] = useState('edit')
  return <><WorkspaceTabs id='test-workspace' label='资料视图' value={tab} onChange={setTab} tabs={[{ value: 'edit', label: '编辑' }, { value: 'history', label: '历史' }]} />
    <WorkspacePanel id='test-workspace' value='edit' active={tab}><label>题干<input /></label></WorkspacePanel>
    <WorkspacePanel id='test-workspace' value='history' active={tab}><p>原记录保持</p></WorkspacePanel></>
}

describe('WorkspaceTabs', () => {
  afterEach(cleanup)

  it('moves keyboard focus separately from activation and keeps editing input mounted', async () => {
    const user = userEvent.setup()
    render(<WorkArea />)
    await user.type(screen.getByLabelText('题干'), '保留编辑内容')
    screen.getByRole('tab', { name: '编辑' }).focus()
    await user.keyboard('{ArrowRight}')
    const history = screen.getByRole('tab', { name: '历史' })
    expect(document.activeElement).toBe(history)
    expect(history.getAttribute('aria-selected')).toBe('false')
    await user.keyboard('{Enter}')
    expect(history.getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tabpanel').textContent).toBe('原记录保持')
    await user.keyboard('{Home}{Enter}')
    expect((screen.getByLabelText('题干') as HTMLInputElement).value).toBe('保留编辑内容')
    const panel = screen.getByRole('tabpanel')
    expect(panel.id).toBe(screen.getByRole('tab', { name: '编辑' }).getAttribute('aria-controls'))
    expect(panel.getAttribute('aria-labelledby')).toBe('test-workspace-edit-tab')
  })
})
