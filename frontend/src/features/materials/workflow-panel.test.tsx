import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkflowPanel } from './workflow-panel'
import type { WorkflowDetailResponse, WorkflowJob, WorkflowPreparationResponse } from '../../types'

const initialJob: WorkflowJob = {
  id: 'job-1', material_id: 'material-1', state: 'needs_review',
  context: { version: 4, source_stamp: 'stamp-current' }, created_at: '2026-10-04T10:00:00Z',
  updated_at: '2026-10-04T10:00:00Z', error_code: null, record_count: 7, result: { learner_id: null },
}

const records = [
  { id: 'q', kind: 'question', data: { original_number: '1', printed_text: '题面', sources: [{ source_id: 's', bbox: [0, 0, 20, 20] }] } },
  { id: 'k', kind: 'knowledge', data: { definition: '知识定义', sources: [{ source_id: 's', bbox: [0, 0, 20, 20] }] } },
  { id: 'm', kind: 'method', data: { name: '方法名称', sources: [{ source_id: 's', bbox: [0, 0, 20, 20] }] } },
  { id: 't', kind: 'question_type', data: { name: '题型名称', sources: [{ source_id: 's', bbox: [0, 0, 20, 20] }] } },
  { id: 'a', kind: 'answer', data: { question: 'q', body: '答案内容', basis: '答案依据' } },
  { id: 'l', kind: 'link', data: { question: 'q', node: 'm', role: 'primary' } },
  { id: 'o', kind: 'observation', data: { sources: [{ source_id: 's', bbox: [0, 0, 20, 20] }], notes: '观察内容' } },
] as WorkflowDetailResponse['records']

const pages = [{ id: 'page-1', position: 1, sha256: 'secret-hash', width: 100, height: 100, page_url: '/page/', preview_url: '/preview/' }]

function detail(job: WorkflowJob): WorkflowDetailResponse {
  return {
    schema_version: 'swb.api.v1', job, records, sources: [{ id: 's', page_id: 'page-1', sha256: 'secret-hash' }],
    readiness: { ready: true, gaps: [], content_gaps: [], questions: [] },
    links: { material_url: '/materials/material-1/', prepare_url: '/prepare/', ai_url: '/ai/', preview_url: job.state === 'output_check' ? '/preview-packet/' : undefined, download_url: job.state === 'complete' ? '/download/' : undefined },
    events: [{ version: 1, action: 'created', details: {}, created_at: job.created_at }],
  }
}

function preparation(job: WorkflowJob): WorkflowPreparationResponse {
  return { schema_version: 'swb.api.v1', job, config: { enabled: false, outbound_scope: null, max_requests: 4, max_seconds: 600, budget_usd: null }, stages: [], limits: { used_requests: 0, max_requests: 4, max_seconds: 600 } }
}

describe('WorkflowPanel', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('keeps proposal evidence readable while disabling every write for a viewer', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      return Response.json(String(input).includes('/preparation/') ? preparation(initialJob) : detail(initialJob))
    }))
    render(<WorkflowPanel jobId='job-1' csrfToken='csrf-test' canWrite={false} pages={pages} onUnauthorized={vi.fn()} onJobUpdated={vi.fn()} onBusyChange={vi.fn()} onOpenContent={vi.fn()} />)
    expect((await screen.findAllByText('题面')).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '确认整包内容' }).matches(':disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '取消任务' }).matches(':disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '刷新任务' }).matches(':disabled')).toBe(false)
  })

  it('shows every record kind, requires review context and output checks, and only advances on explicit actions', async () => {
    const user = userEvent.setup()
    let state: WorkflowJob['state'] = 'needs_review'
    const actions: Array<Record<string, unknown>> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>
        actions.push(body)
        state = body.action === 'confirm' ? 'ready' : body.action === 'queue' ? 'queued' : 'complete'
        return Response.json({ schema_version: 'swb.api.v1', job: { ...initialJob, state } })
      }
      const job = { ...initialJob, state }
      if (url.pathname.endsWith('/preparation/')) return Response.json(preparation(job))
      return Response.json(detail(job))
    })
    vi.stubGlobal('fetch', fetchMock)
    const onUnauthorized = vi.fn()
    const onJobUpdated = vi.fn()
    const onBusyChange = vi.fn()
    render(<WorkflowPanel jobId='job-1' csrfToken='csrf-test' canWrite pages={pages} onUnauthorized={onUnauthorized} onJobUpdated={onJobUpdated} onBusyChange={onBusyChange} onOpenContent={vi.fn()} />)

    for (const text of ['题面', '知识定义', '方法名称', '题型名称', '答案内容', '主要方法', '观察内容']) {
      expect((await screen.findAllByText(text)).length).toBeGreaterThan(0)
    }
    expect(screen.queryByText('secret-hash')).toBeNull()
    const confirm = screen.getByRole('button', { name: '确认整包内容' })
    expect((confirm as HTMLButtonElement).disabled).toBe(true)
    await user.click(screen.getByRole('checkbox', { name: /已查看并核对/ }))
    await user.type(screen.getByLabelText('确认原因'), '家长核对原图和题目')
    await user.click(confirm)
    expect((await screen.findByRole('button', { name: '加入处理队列' }) as HTMLButtonElement).disabled).toBe(false)
    expect(actions[0]).toMatchObject({ action: 'confirm', reason: '家长核对原图和题目', expected: initialJob.context })
    expect(actions[0].request_key).toEqual(expect.any(String))

    await user.click(screen.getByRole('button', { name: '加入处理队列' }))
    expect((await screen.findByText('排队中')).textContent).toContain('排队中')
    expect(actions[1]).toMatchObject({ action: 'queue', expected: initialJob.context })

    state = 'output_check'
    await user.click(screen.getByRole('button', { name: '刷新任务' }))
    expect((await screen.findByRole('link', { name: '打开五册检查版' })).getAttribute('href')).toBe('/preview-packet/')
    await user.click(screen.getByRole('checkbox', { name: 'PDF 可以阅读' }))
    await user.click(screen.getByRole('checkbox', { name: 'Word 文档可以阅读' }))
    await user.click(screen.getByRole('checkbox', { name: '五册用途均正确' }))
    await user.type(screen.getByLabelText('输出检查原因'), '逐册检查完成')
    const outputConfirm = screen.getByRole('button', { name: '确认输出检查' })
    expect((outputConfirm as HTMLButtonElement).disabled).toBe(false)
    await user.click(outputConfirm)
    const downloadLinks = await screen.findAllByRole('link', { name: '下载完整五册 ZIP' })
    expect(downloadLinks).toHaveLength(2)
    expect(downloadLinks.map((link) => link.getAttribute('href'))).toEqual(['/download/', '/download/'])
    expect(actions[2]).toMatchObject({ action: 'check_output', reason: '逐册检查完成', checks: { pdf: true, docx: true, purposes: true }, expected: initialJob.context })
    expect(onBusyChange).toHaveBeenCalledWith(true)
    expect(onBusyChange).toHaveBeenLastCalledWith(false)
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
