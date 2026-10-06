import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DocumentCatalogue } from './catalogue'
import { notifyLearningUpdate } from '../../lib/learning-updates'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const data = (title: string) => ({ schema_version: 'swb.api.v1', items: [{ id: title, title, category_label: '练习', created_at: '2026-10-06T00:00:00Z', state_label: '已生成', detail_url: '/prints/', message: '', zip_url: null, checks: { word_pc: { status: 'not_tested' } }, documents: [] }], total: 1, page: 1, has_next: false })
it('ignores a late previous-family response and refreshes only its own scope', async () => {
  let previous!: (response: Response) => void
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { previous = resolve })).mockResolvedValue(new Response(JSON.stringify(data('家庭 B 成果'))))
  vi.stubGlobal('fetch', fetcher)
  const unauthorized = vi.fn()
  const view = render(<DocumentCatalogue householdId='a' onUnauthorized={unauthorized} />)
  view.rerender(<DocumentCatalogue householdId='b' onUnauthorized={unauthorized} />)
  await screen.findByRole('heading', { name: '家庭 B 成果' })
  previous(new Response(JSON.stringify(data('家庭 A 私有成果'))))
  await waitFor(() => expect(screen.queryByText('家庭 A 私有成果')).toBeNull())
  expect((fetcher.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true)
  notifyLearningUpdate({ householdId: 'a' })
  expect(fetcher).toHaveBeenCalledTimes(2)
  fetcher.mockResolvedValue(new Response(JSON.stringify(data('家庭 B 更新'))))
  notifyLearningUpdate({ householdId: 'b' })
  await screen.findByRole('heading', { name: '家庭 B 更新' })
})
it('searches every category, distinguishes no match, and keeps untested Word status', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(data('合成成果')))).mockImplementation(async () => new Response(JSON.stringify({ schema_version: 'swb.api.v1', items: [], total: 0, page: 1, has_next: false })))
  vi.stubGlobal('fetch', fetcher)
  render(<DocumentCatalogue householdId='a' onUnauthorized={vi.fn()} />)
  await screen.findByText(/Microsoft Word 尚未实开/)
  await userEvent.type(screen.getByRole('searchbox'), '分数')
  await userEvent.click(screen.getByRole('button', { name: '查找成果' }))
  await screen.findByText('当前筛选没有匹配成果，已有文档仍保留。')
  const url = new URL(fetcher.mock.calls.at(-1)![0] as string, 'http://localhost')
  expect(url.searchParams.get('q')).toBe('分数')
  expect(url.searchParams.get('category')).toBe('')
  await userEvent.click(screen.getByRole('button', { name: '清除筛选' }))
  await screen.findByText('还没有生成成果。可先选择资料整理讲解或制作练习。')
})
