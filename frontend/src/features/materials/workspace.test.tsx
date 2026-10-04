import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MaterialWorkspace } from './workspace'
import type { MaterialDetailResponse, WorkflowDetailResponse, WorkflowJob, WorkflowPreparationResponse } from '../../types'

const material = { id: 'material-1', title: '测试资料', page_count: 1, created_at: '2026-10-04T10:00:00Z', material_url: '/materials/material-1/', prepare_url: '/prepare/' }
const jobs: WorkflowJob[] = [1, 2].map((n) => ({
  id: `job-${n}`, material_id: material.id, state: 'ready', context: { version: 1, source_stamp: 'stamp' },
  created_at: `2026-10-04T0${3 - n}:00:00Z`, updated_at: '2026-10-04T10:00:00Z',
  error_code: null, record_count: 0, result: { learner_id: null },
}))
const detail: MaterialDetailResponse = {
  schema_version: 'swb.api.v1', material,
  pages: [{ id: 'page', position: 1, width: 100, height: 100, sha256: 'synthetic', page_url: '/page/', preview_url: '/preview/' }],
  readiness: { ready: true, gaps: [], content_gaps: [], questions: [] }, jobs,
}

function fixture(post?: () => Promise<Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && post) return post()
    const path = String(input)
    if (path.includes('/preparation/')) {
      const job = jobs.find((item) => path.includes(item.id))!
      const response: WorkflowPreparationResponse = {
        schema_version: 'swb.api.v1', job,
        config: { enabled: false, outbound_scope: null, max_requests: 0, max_seconds: 0, budget_usd: null },
        stages: [], limits: { used_requests: 0, max_requests: 0, max_seconds: 0 },
      }
      return Response.json(response)
    }
    if (path.includes('/workflows/')) {
      const job = jobs.find((item) => path.includes(item.id))!
      const response: WorkflowDetailResponse = {
        schema_version: 'swb.api.v1', job, sources: [], records: [], readiness: detail.readiness,
        events: [], links: { material_url: material.material_url, prepare_url: material.prepare_url, ai_url: '/ai/' },
      }
      return Response.json(response)
    }
    return Response.json(path.includes('/materials/material-1/') ? detail : { schema_version: 'swb.api.v1', items: [material], total: 1 })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} />)
  return fetchMock
}

describe('MaterialWorkspace navigation', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('keeps the loaded material and selected task when clicking its current card again', async () => {
    const user = userEvent.setup()
    fixture()
    await screen.findByRole('button', { name: '加入处理队列' })
    await user.click(screen.getByRole('button', { name: /测试资料.*当前资料/ }))
    expect(screen.getByText('资料页 1')).toBeTruthy()
    expect(screen.getByRole('button', { name: '加入处理队列' })).toBeTruthy()
    expect(screen.queryByText('正在读取资料页…')).toBeNull()
  })

  it('prevents task switching while a write is pending and restores navigation afterwards', async () => {
    const user = userEvent.setup()
    let finish!: (response: Response) => void
    const fetchMock = fixture(() => new Promise<Response>((resolve) => { finish = resolve }))
    await user.click(await screen.findByRole('button', { name: '加入处理队列' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '查看任务' }).matches(':disabled')).toBe(true))
    await user.click(screen.getByRole('button', { name: '查看任务' }))
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/workflows/job-2/'))).toBe(false)
    await act(async () => finish(Response.json({ schema_version: 'swb.api.v1', job: { ...jobs[0], state: 'queued', context: { version: 2, source_stamp: 'stamp' } } })))
    await waitFor(() => expect(screen.getByRole('button', { name: '查看任务' }).matches(':disabled')).toBe(false))
  })
})
