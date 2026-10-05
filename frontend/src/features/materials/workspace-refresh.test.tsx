import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { MaterialWorkspace } from './workspace'

vi.mock('./page', () => ({
  MaterialUploadQueue: ({ onUploaded }: { onUploaded: () => void }) => <button onClick={onUploaded}>完成上传</button>,
}))

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('retains task inputs and mounted fields while uploaded pages refresh, including refresh failure', async () => {
  const user = userEvent.setup()
  const material = { id: 'material-1', title: '测试资料', page_count: 1, created_at: '2026-10-05T00:00:00Z', material_url: '/material/material-1/', prepare_url: '/prints/materials/material-1/five-books/' }
  const detail = { schema_version: 'swb.api.v1', material, pages: [], jobs: [], readiness: { ready: false, gaps: [], content_gaps: [], questions: [] } }
  let reads = 0
  let releaseRefresh!: (response: Response) => void
  const refresh = new Promise<Response>((resolve) => { releaseRefresh = resolve })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), window.location.origin).pathname
    if (path.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
    if (path === '/api/v1/materials/') return Response.json({ schema_version: 'swb.api.v1', items: [material], total: 1 })
    if (path === '/api/v1/materials/material-1/') {
      reads += 1
      if (reads === 2) return refresh
      if (reads === 3) return Response.json({ schema_version: 'swb.api.v1', error: { code: 'temporary', message: '服务暂不可用' } }, { status: 503 })
      return Response.json(detail)
    }
    throw new Error(`unexpected request ${path}`)
  }))
  render(<MaterialWorkspace householdId='home-1' householdName='家庭' csrfToken='csrf' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={vi.fn()} initialTab='tasks' />)
  await user.click(await screen.findByRole('button', { name: '新建整理任务' }))
  const choice = screen.getByLabelText(/所选学习者的全部历史记录/) as HTMLInputElement
  await user.click(choice)
  expect(choice.checked).toBe(true)
  await user.click(screen.getByRole('tab', { name: /原图与进度/ }))
  await user.click(screen.getByRole('button', { name: '完成上传' }))
  await waitFor(() => expect(reads).toBe(2))
  expect(choice.isConnected).toBe(true)
  expect(choice.checked).toBe(true)
  await act(async () => releaseRefresh(Response.json(detail)))
  await user.click(screen.getByRole('tab', { name: /整理任务/ }))
  expect(screen.getByLabelText(/所选学习者的全部历史记录/)).toBe(choice)
  expect(choice.checked).toBe(true)
  await user.click(screen.getByRole('tab', { name: /原图与进度/ }))
  await user.click(screen.getByRole('button', { name: '完成上传' }))
  expect(await screen.findByText(/资料暂时无法刷新/)).toBeTruthy()
  expect(choice.isConnected).toBe(true)
  expect(choice.checked).toBe(true)
})
