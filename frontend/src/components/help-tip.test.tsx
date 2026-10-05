import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { HelpTip } from './help-tip'

describe('supplemental help access', () => {
  it('opens on keyboard focus and dismisses with Escape without stealing focus', async () => {
    const user = userEvent.setup()
    render(<HelpTip label='步骤帮助'>先自己尝试，再看讲解。</HelpTip>)
    await user.tab()
    const button = screen.getByRole('button', { name: '步骤帮助' })
    expect(screen.getByRole('tooltip').textContent).toContain('先自己尝试')
    expect(button.getAttribute('aria-describedby')).toBe(screen.getByRole('tooltip').id)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('tooltip')).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('stays open when a touch-like click first focuses the trigger and closes on blur', async () => {
    const user = userEvent.setup()
    render(<><HelpTip label='图片帮助'>原照片会保留。</HelpTip><button>继续</button></>)
    await user.click(screen.getByRole('button', { name: '图片帮助' }))
    expect(screen.getByRole('tooltip').textContent).toContain('原照片会保留')
    fireEvent.mouseLeave(screen.getByRole('button', { name: '图片帮助' }).parentElement!)
    expect(screen.getByRole('tooltip')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '继续' }))
    expect(screen.queryByRole('tooltip')).toBeNull()
    await user.hover(screen.getByRole('button', { name: '图片帮助' }))
    expect(screen.getByRole('tooltip')).toBeTruthy()
  })
})
