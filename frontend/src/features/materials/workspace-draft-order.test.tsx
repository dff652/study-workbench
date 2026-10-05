import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { MaterialWorkspace } from './workspace'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it.each(['title', 'workflow'] as const)('preserves and saves new %s input entered while the previous draft is clearing', async (kind) => {
  const user = userEvent.setup()
  const original = { id: 'material-1', title: '原有资料', page_count: 1, created_at: '2026-10-05T00:00:00Z', material_url: '/material/1/', prepare_url: '/prepare/' }
  const created = { ...original, id: 'material-2', title: '第一份新资料' }
  const job = { id: 'job-1', material_id: original.id, state: 'ready', context: { version: 1, source_stamp: 'synthetic' }, created_at: original.created_at, updated_at: original.created_at, error_code: null, record_count: 0, result: { learner_id: null } }
  const readiness = { ready: false, gaps: [], content_gaps: [], questions: [] }
  const draftKey = kind === 'title' ? 'materials:create-title' : 'materials:workflow:material-1'
  let materialCreated = false
  let releaseClear!: (response: Response) => void
  let releaseSave!: (response: Response) => void
  const pendingClear = new Promise<Response>((resolve) => { releaseClear = resolve })
  const pendingSave = new Promise<Response>((resolve) => { releaseSave = resolve })
  const saves: Array<{ payload: Record<string, unknown>; expected_version: number }> = []
  const onUnsavedChange = vi.fn()
  const draftResponse = (version: number, payload: unknown) => Response.json({ schema_version: 'swb.api.v1', draft: { key: draftKey, version, base_stamp: kind === 'title' ? 'material-title:v1' : 'material:material-1', payload, updated_at: original.created_at } })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin)
    if (url.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
    if (url.pathname.startsWith('/api/v1/draft-save/')) {
      const body = JSON.parse(String(init?.body))
      saves.push(body)
      return body.payload.cleared ? pendingClear : pendingSave
    }
    if (url.pathname === '/api/v1/materials/' && init?.method === 'POST') {
      materialCreated = true
      return Response.json({ schema_version: 'swb.api.v1', material: created })
    }
    if (url.pathname === '/api/v1/materials/') return Response.json({ schema_version: 'swb.api.v1', items: materialCreated ? [created, original] : [original], total: materialCreated ? 2 : 1, page: 1, page_size: 20, has_next: false })
    if (url.pathname.endsWith('/workflows/')) return Response.json({ schema_version: 'swb.api.v1', job })
    if (url.pathname.endsWith('/preparation/')) return Response.json({ schema_version: 'swb.api.v1', job, config: { enabled: false, outbound_scope: null, max_requests: 0, max_seconds: 0, budget_usd: null }, stages: [], limits: { used_requests: 0, max_requests: 0, max_seconds: 0 } })
    if (url.pathname.startsWith('/api/v1/workflows/')) return Response.json({ schema_version: 'swb.api.v1', job, sources: [], records: [], readiness, events: [], links: { material_url: original.material_url, prepare_url: original.prepare_url, ai_url: '/ai/' } })
    if (url.pathname.startsWith('/api/v1/materials/')) return Response.json({ schema_version: 'swb.api.v1', material: url.pathname.includes('material-2') ? created : original, pages: [], readiness, jobs: [] })
    throw new Error('Unexpected HTTP request: ' + url.pathname)
  }))
  render(<MaterialWorkspace householdId='home-a' householdName='合成家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={onUnsavedChange} initialTab='tasks' />)
  if (kind === 'title') {
    await user.click(await screen.findByRole('button', { name: '新建资料' }))
    await user.type(screen.getByLabelText('资料名称'), '第一份新资料')
    await user.click(screen.getByRole('button', { name: '创建资料' }))
  } else {
    await user.click(await screen.findByRole('button', { name: '新建整理任务' }))
    await user.click(screen.getByRole('button', { name: '创建并查看任务' }))
  }
  await waitFor(() => expect(saves).toHaveLength(1))
  expect(saves[0].payload).toEqual({ cleared: true })
  if (kind === 'title') {
    await user.click(screen.getByRole('button', { name: '新建资料' }))
    await user.type(screen.getByLabelText('资料名称'), '清理期间输入的第二份资料')
  } else {
    await user.click(await screen.findByRole('button', { name: '新建整理任务' }))
    await user.click(screen.getByLabelText(/所选学习者的全部历史记录/))
  }
  expect(onUnsavedChange.mock.lastCall?.[0]).toBe(true)
  await act(async () => { releaseClear(draftResponse(1, { cleared: true })); await pendingClear })
  await waitFor(() => expect(saves).toHaveLength(2), { timeout: 2400 })
  expect(saves[1].expected_version).toBe(1)
  expect(saves[1].payload).toEqual(kind === 'title'
    ? { title: '清理期间输入的第二份资料' }
    : { learnerId: '', evidenceScope: 'selected_learner_history', hasLocalProposal: false })
  expect(onUnsavedChange.mock.lastCall?.[0]).toBe(true)
  await act(async () => { releaseSave(draftResponse(2, saves[1].payload)); await pendingSave })
  await waitFor(() => expect(onUnsavedChange.mock.lastCall?.[0]).toBe(false))
})
