import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { KnowledgeFormulaTools } from './knowledge-formula-tools'

afterEach(() => { cleanup(); document.querySelector('#synthetic-root')?.remove(); vi.unstubAllGlobals() })
it('previews bounded math and inserts the same text into definition and markup without replacing the definition', async () => {
  const root = document.createElement('div'); root.id = 'synthetic-root'
  root.innerHTML = '<textarea id="id_definition">分数相加\n1/2 + 1/3</textarea><textarea id="id_display_markup"></textarea>'
  document.body.append(root)
  const changed = vi.fn(); root.addEventListener('input', changed)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', formula: ['r', ['t', '('], ['f', ['t', '1'], ['t', '2']], ['t', '+'], ['f', ['t', '1'], ['t', '3']], ['t', ')']] })))
  const user = userEvent.setup(); render(<KnowledgeFormulaTools root={root} csrfToken='synthetic-csrf' />)
  fireEvent.change(screen.getByRole('textbox', { name: '公式辅助' }), { target: { value: '1/2 + 1/3' } })
  await user.click(screen.getByRole('button', { name: '预览公式' }))
  await user.click(await screen.findByRole('button', { name: '加入定义与排版' }))
  expect((root.querySelector('#id_definition') as HTMLTextAreaElement).value).toBe('分数相加\n1/2 + 1/3')
  expect((root.querySelector('#id_display_markup') as HTMLTextAreaElement).value).toBe('分数相加\n[[math:1/2 + 1/3]]')
  expect(changed).toHaveBeenCalledTimes(2)
})
it('does not offer insertion after the parser rejects a formula', async () => {
  const root = document.createElement('div')
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: { message: '公式结构无效' } }, { status:400 })))
  render(<KnowledgeFormulaTools root={root} csrfToken='synthetic-csrf' />)
  fireEvent.change(screen.getByRole('textbox', { name:'公式辅助' }), { target:{value:'bad('} })
  await userEvent.click(screen.getByRole('button', { name:'预览公式' }))
  await screen.findByRole('status')
  expect(screen.queryByRole('button', { name:'加入定义与排版' })).toBeNull()
})
