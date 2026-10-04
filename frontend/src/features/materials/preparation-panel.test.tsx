import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkflowPreparationPanel } from './preparation-panel'
import type { MaterialPage, PreparationStage, WorkflowJob, WorkflowPreparationResponse } from '../../types'

if (!window.PointerEvent) Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent })

const job: WorkflowJob = {
  id: 'job-1', material_id: 'material-1', state: 'ready', context: { version: 7, source_stamp: 'workflow-stamp' },
  created_at: '2026-10-04T10:00:00Z', updated_at: '2026-10-04T10:00:00Z', error_code: null, record_count: 0, result: { learner_id: null },
}
const page: MaterialPage = { id: 'page-1', position: 1, sha256: 'hidden-hash', width: 100, height: 100, page_url: '/page/', preview_url: '/preview/' }
const config = { enabled: true, outbound_scope: 'selected_regions', max_requests: 4, max_seconds: 600, budget_usd: '0.1000' }
const limits = { used_requests: 0, max_requests: 4, max_seconds: 600 }
const stageExpected = { job: { version: 7 }, material: { source_stamp: 'material-stamp' }, stage_id: 'stage-secret', state: 'awaiting_review', response_sha256: 'response-secret' }
const stageSource = [{ page_id: 'page-1', bbox: [5, 6, 55, 66] as [number, number, number, number] }]

function stage(overrides: Partial<PreparationStage> = {}): PreparationStage {
  return {
    id: 'stage-1', state: 'awaiting_review', question_id: 'question-secret', sources: stageSource,
    proposal: { printed_text: '模型识别题面', missing_fields: ['answer'], nodes: [{ kind: 'knowledge', data: { definition: '分数相加' } }], answer: { body: '答案草稿', formulas: [{ t: 'f', f: '1/2 + 1/3' }], basis: '同分母计算' } },
    can_confirm: true, expected: stageExpected, error_code: null, record_count: 3, created_at: '2026-10-04T10:30:00Z',
    ...overrides,
  }
}

function response(stages: PreparationStage[] = [], changes: Partial<WorkflowPreparationResponse> = {}): WorkflowPreparationResponse {
  return { schema_version: 'swb.api.v1', job, config, stages, limits, ...changes }
}

function mount({
  initial = response(),
  afterRefresh,
  onOpenContent = vi.fn(),
  onBusyChange = vi.fn(),
}: {
  initial?: WorkflowPreparationResponse
  afterRefresh?: (count: number) => WorkflowPreparationResponse
  onOpenContent?: () => void
  onBusyChange?: (busy: boolean) => void
} = {}) {
  const calls: Array<{ url: URL; init?: RequestInit; body?: Record<string, unknown> }> = []
  let getCount = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin)
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    calls.push({ url, init, body })
    if (init?.method === 'GET' && url.pathname.endsWith('/preparation/')) {
      getCount += 1
      return Response.json(afterRefresh && getCount > 1 ? afterRefresh(getCount) : initial)
    }
    if (init?.method === 'POST' && url.pathname.endsWith('/preparation/')) return Response.json({ schema_version: 'swb.api.v1', job, stage_id: 'stage-2' })
    if (init?.method === 'POST' && url.pathname.endsWith('/confirm/')) return Response.json({ schema_version: 'swb.api.v1', job, question_id: 'question-secret', revision_id: 'revision-2' })
    if (init?.method === 'POST' && url.pathname.endsWith('/cancel/')) return Response.json({ schema_version: 'swb.api.v1', job })
    throw new Error(`unexpected request: ${init?.method || 'GET'} ${url.pathname}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const onUnauthorized = vi.fn()
  render(<WorkflowPreparationPanel jobId='job-1' workflowJob={job} pages={[page]} canWrite hasUnreviewedSourcePackage={false} csrfToken='csrf-test' onUnauthorized={onUnauthorized} onJobUpdated={vi.fn()} onBusyChange={onBusyChange} onOpenContent={onOpenContent} />)
  return { calls, fetchMock, onBusyChange, onOpenContent, onUnauthorized }
}

async function selectRegion(user: ReturnType<typeof userEvent.setup>, buttonName = '确认添加准备来源') {
  const image = await screen.findByAltText('资料页 1 原图')
  Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 })
  Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 })
  fireEvent.load(image)
  const overlay = await screen.findByRole('img', { name: '资料页 1 区域选框' })
  vi.spyOn(overlay, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, toJSON: () => ({}) })
  fireEvent.pointerDown(overlay, { button: 0, pointerId: 1, clientX: 5, clientY: 6 })
  fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 55, clientY: 66 })
  await user.click(await screen.findByRole('button', { name: buttonName }))
}

describe('WorkflowPreparationPanel', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('sends one explicit request with selected source, job context and CSRF, then waits for manual refresh', async () => {
    const user = userEvent.setup()
    const { calls, onBusyChange } = mount()
    await screen.findByText('模型准备已启用')
    await selectRegion(user)
    await user.type(screen.getByLabelText('准备原因（必填）'), '只核对选定的原图题目')
    const submit = screen.getByRole('button', { name: '明确发送准备请求' })
    expect((submit as HTMLButtonElement).disabled).toBe(true)
    await user.click(screen.getByRole('checkbox', { name: /我已对照原图并明确选定/ }))
    await user.click(submit)

    const queue = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/preparation/')))
    expect(queue?.url.pathname).toBe('/api/v1/workflows/job-1/preparation/')
    expect(queue?.init?.headers).toMatchObject({ 'X-CSRFToken': 'csrf-test' })
    expect(queue?.body).toMatchObject({
      expected: job.context,
      reason: '只核对选定的原图题目',
      sources: [{ page_id: 'page-1', bbox: [5, 6, 55, 66] }],
    })
    expect(queue?.body?.request_key).toEqual(expect.stringMatching(/^[0-9a-f-]{36}$/i))
    expect(queue?.body).not.toHaveProperty('question_id')
    expect(calls.filter(({ init, url }) => init?.method === 'GET' && url.pathname.endsWith('/preparation/'))).toHaveLength(1)
    expect(await screen.findByText(/不会自动刷新或重试/)).toBeTruthy()
    expect(onBusyChange).toHaveBeenCalledWith(true)
    expect(onBusyChange).toHaveBeenLastCalledWith(false)
  })

  it('keeps a manual content path available when model preparation is disabled', async () => {
    const onOpenContent = vi.fn()
    const { calls } = mount({ initial: response([], { config: { ...config, enabled: false } }), onOpenContent })
    await screen.findByText('模型准备未启用')
    await userEvent.setup().click(screen.getByRole('button', { name: '打开同页人工核对' }))
    expect(onOpenContent).toHaveBeenCalledOnce()
    expect(screen.queryByRole('button', { name: '明确发送准备请求' })).toBeNull()
    expect(calls.filter(({ init }) => init?.method === 'POST')).toHaveLength(0)
  })

  it('confirms a reviewed proposal with immutable stage context, fixed sources and preserved formulas', async () => {
    const user = userEvent.setup()
    const { calls } = mount({ initial: response([stage()]) })
    await screen.findByText('准备阶段历史')
    expect(screen.getByText('本阶段固定原图来源')).toBeTruthy()
    expect(screen.getByText('家长答案待核对')).toBeTruthy()
    await user.clear(screen.getByLabelText('模型草稿题干（必填）'))
    await user.type(screen.getByLabelText('模型草稿题干（必填）'), '人工核对后的题面')
    await user.clear(screen.getByLabelText('家长核对的答案或解答（必填）'))
    await user.type(screen.getByLabelText('家长核对的答案或解答（必填）'), '人工复核答案')
    await user.type(screen.getByLabelText('本阶段确认原因（必填）'), '对照原图修正识别错误')
    await user.click(screen.getByRole('checkbox', { name: /我已对照本阶段原图区域/ }))
    await user.click(screen.getByRole('button', { name: '确认本阶段内容' }))

    const confirm = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/confirm/')))
    expect(confirm?.url.pathname).toBe('/api/v1/workflows/job-1/preparation/stage-1/confirm/')
    expect(confirm?.body).toMatchObject({
      expected: stageExpected,
      reason: '对照原图修正识别错误',
      checked: true,
      printed_text: '人工核对后的题面',
      original_number: '',
      sources: stageSource,
      answer: { body: '人工复核答案', basis: '同分母计算', formulas: [{ t: 'f', f: '1/2 + 1/3' }] },
      nodes: [{ kind: 'knowledge', data: { definition: '分数相加' } }],
    })
    expect(confirm?.body?.request_key).toEqual(expect.stringMatching(/^[0-9a-f-]{36}$/i))
    expect(screen.queryByText(/stage-secret|response-secret|question-secret|hidden-hash/)).toBeNull()
    expect(await screen.findByText('本阶段内容已人工确认并保存；其他阶段历史仍保留。')).toBeTruthy()
    expect(screen.getByRole('button', { name: '刷新准备阶段' })).toBeTruthy()
  })

  it('lets an operator cancel a failed stage and retry it with the identical fixed source', async () => {
    const user = userEvent.setup()
    const failed = stage({ state: 'failed', can_confirm: false, error_code: 'provider_error', proposal: null })
    const retryStage = stage({ id: 'stage-2', state: 'queued', can_confirm: false, proposal: null, created_at: '2026-10-04T10:45:00Z' })
    const { calls } = mount({ initial: response([failed]), afterRefresh: () => response([{ ...failed, state: 'cancelled' }, retryStage], { limits: { ...limits, used_requests: 2 } }) })
    await screen.findByText('准备阶段历史')
    await user.type(screen.getByLabelText('取消阶段原因'), '明确跳过失败阶段')
    await user.click(screen.getByRole('button', { name: '取消本模型阶段' }))
    const cancel = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/cancel/')))
    expect(cancel?.body).toMatchObject({ expected: stageExpected, reason: '明确跳过失败阶段' })
    expect((await screen.findByText('已取消')).textContent).toContain('已取消')

    await user.click(screen.getByRole('button', { name: '按原来源重做阶段' }))
    expect((screen.getByLabelText('来源页') as HTMLSelectElement).disabled).toBe(true)
    expect(screen.getByText('重做阶段会固定沿用原来源')).toBeTruthy()
    await user.type(screen.getByLabelText('准备原因（必填）'), '按原图重做识别')
    await user.click(screen.getByRole('checkbox', { name: /我已对照原图并明确选定/ }))
    await user.click(screen.getByRole('button', { name: '明确发送准备请求' }))
    const queue = await waitFor(() => calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/preparation/')))
    expect(queue?.body).toMatchObject({
      expected: job.context, question_id: 'question-secret',
      sources: stageSource, reason: '按原图重做识别',
    })

    await user.click(screen.getByRole('button', { name: '刷新准备阶段' }))
    expect(await screen.findByText('2 个阶段')).toBeTruthy()
    expect((calls.filter(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/preparation/'))).length).toBe(1)
  })

  it('allows explicit rejection of a proposed answer while confirming the reviewed question', async () => {
    const user = userEvent.setup()
    const { calls } = mount({ initial: response([stage()]) })
    await screen.findByText('准备阶段历史')
    await user.click(screen.getByRole('checkbox', { name: '可选家长答案' }))
    expect(screen.queryByLabelText('家长核对的答案或解答（必填）')).toBeNull()
    await user.type(screen.getByLabelText('本阶段确认原因（必填）'), '答案依据不足，保留待补，只确认题面')
    await user.click(screen.getByRole('checkbox', { name: /我已对照本阶段原图区域/ }))
    await user.click(screen.getByRole('button', { name: '确认本阶段内容' }))
    const confirmation = calls.find(({ url, init }) => init?.method === 'POST' && url.pathname.endsWith('/confirm/'))
    expect(confirmation?.body).not.toHaveProperty('answer')
    expect(confirmation?.body).toMatchObject({ printed_text: '模型识别题面', sources: stageSource, checked: true })
  })
})
