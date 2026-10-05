import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProgressWorkspace } from './workspace'
import type { Attempt, LearnerProgressResponse, ReviewSchedule, SchedulesResponse } from '../../types'

const learner = { id: 'learner-1', display_name: '小林', grade: '五年级', profile_url: '/profile/', report_url: '/report/' }
const opaqueContext = { version: 4, stamp: 'context-must-stay-private' }

const learnerProgress: LearnerProgressResponse = {
  schema_version: 'swb.api.v1',
  scope: { household_id: 'home-1', learner_id: 'learner-1', metric_version: 'progress.v1', as_of: '2026-10-04' },
  groups: [
    { id: 'knowledge-1', kind: 'knowledge', label: '分数运算', question_count: 2, attempt_count: 3, independent_success_count: 1, unknown_evidence_count: 1, source_counts: { independent_answer: 2, unknown: 1 }, node_url: '/knowledge/1/' },
    { id: 'method-1', kind: 'method', label: '通分', question_count: 2, attempt_count: 0, independent_success_count: 0, unknown_evidence_count: 0, source_counts: {}, node_url: null },
    { id: 'type-1', kind: 'question_type', label: '异分母加法', question_count: 1, attempt_count: 1, independent_success_count: 0, unknown_evidence_count: 1, source_counts: { unknown: 1 }, node_url: '/question-types/1/' },
  ],
}

const plannedSchedule: ReviewSchedule = {
  id: 21, question_id: 44, question_text: '计算 1/3 + 1/6', goal: '独立完成通分', prompt_plan: '先不提示，卡住后观察步骤',
  due_date: '2026-10-06', state: 'planned', overdue: false, target_stale: false, context: opaqueContext,
  detail_url: '/learning/schedules/21/', question_url: '/knowledge/questions/44/', record_attempt_url: '/learning/attempts/new/?question=44&kind=retest',
  attempt_count: 3,
  latest_attempt: {
    attempt_id: 'attempt-1', attempt_revision_id: 'attempt-revision-old', attempt_kind: 'retest', attempt_kind_label: '复测',
    source_kind: 'independent_answer', source_kind_label: '独立作答', independence: 'confirmed_independent', independence_label: '人工确认独立',
    prompt_status: 'none_confirmed', prompt_status_label: '人工确认无提示', prompts: [], actual_date_state: 'unknown', actual_date: null,
    legibility: 'readable', legibility_label: '清楚可辨', answer_text: '解题过程摘要', state: 'active', state_label: '有效',
    question_id: '44', question_revision_id: 'question-rev-44-old', question_text: '计算 1/3 + 1/6', independent_success: true,
    sources: [], assessments: [{ assessment_id: 'assessment-1', assessment_revision_id: 'assessment-rev-1', attempt_revision_id: 'attempt-revision-old',
      review_state: 'accepted', current: true, review_state_label: '已接受', published: true, reviewer_id: 'reviewer-1', dimensions: [{
        dimension: 'method', judgment: 'correct', basis: 'source_verified', dimension_label: '解题过程', judgment_label: '正确', basis_label: '原图核实',
        rationale: '通分步骤与来源一致。', unknown_reason: '', sources: [],
      }] }],
    attempt_url: '/learning/attempts/old/', question_url: '/knowledge/questions/44/', previous_attempt_id: null,
  } satisfies Attempt,
  history: [{ revision_no: 1, action: 'planned', due_date: '2026-10-06', reason: '本周复习', attempt_revision_id: null, actual_date: null, recorded_at: '2026-10-04T08:00:00+08:00' }],
  attempt_choices: [{ revision_id: 'attempt-revision-1', label: '一次已保存的独立作答', actual_date: null, source_kind: 'independent_answer' }],
}

const completedSchedule: ReviewSchedule = {
  ...plannedSchedule,
  id: 22,
  question_text: '计算 2/5 + 1/5',
  state: 'completed',
  overdue: false,
  history: [{ revision_no: 2, action: 'completed', due_date: '2026-10-02', reason: '复测完成', attempt_revision_id: 'attempt-revision-2', actual_date: null, recorded_at: '2026-10-04T09:30:00+08:00' }],
  attempt_choices: [],
}

const schedules: SchedulesResponse = {
  schema_version: 'swb.api.v1', scope: { household_id: 'home-1', learner_id: 'learner-1', as_of: '2026-10-06' },
  counts: { pending: 1, overdue: 0, completed: 1, cancelled: 0 }, items: [plannedSchedule, completedSchedule],
}

function mountWorkspace(
  role: 'owner' | 'reviewer' | 'viewer' = 'owner',
  postResponse?: () => Promise<Response>,
  scheduleResponse: SchedulesResponse = schedules,
  workspaceProps: {
    initialTab?: string
    onTabChange?: (value: string) => void
    onUnsavedChange?: (dirty: boolean) => void
  } = {},
) {
  const unauthorized = vi.fn()
  let currentScheduleResponse = scheduleResponse
  const calls: Array<{ url: URL; init?: RequestInit }> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin)
    calls.push({ url, init })
    if (init?.method === 'POST') {
      if (postResponse) return postResponse()
      return Response.json({ schema_version: 'swb.api.v1', schedule_id: 88 })
    }
    if (url.pathname === '/api/v1/learners/learner-1/progress/') return Response.json(learnerProgress)
    if (url.pathname === '/api/v1/learners/learner-1/schedules/options/') {
      return Response.json({ schema_version: 'swb.api.v1', questions: [{ revision_id: 'question-revision-7', label: '第 7 题 · 分数加法' }], context: opaqueContext })
    }
    if (url.pathname === '/api/v1/learners/learner-1/schedules/') return Response.json(currentScheduleResponse)
    throw new Error(`unexpected request: ${url.pathname}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const view = render(<ProgressWorkspace householdId='home-1' learner={learner} csrfToken='csrf-test' canWrite={role === 'owner' || role === 'reviewer'} onUnauthorized={unauthorized} {...workspaceProps} />)
  return { calls, fetchMock, unauthorized, view, setScheduleResponse: (value: SchedulesResponse) => { currentScheduleResponse = value } }
}

describe('ProgressWorkspace', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('keeps materials processing out of learner progress and reads only learner evidence and schedules', async () => {
    const { calls } = mountWorkspace()
    const user = userEvent.setup()
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['复测计划', '学习证据'])
    expect(screen.queryByRole('tab', { name: '资料进度' })).toBeNull()
    await user.click(screen.getByRole('tab', { name: '学习证据' }))
    expect(await screen.findByRole('heading', { name: '知识、方法与题型进度' })).toBeTruthy()
    expect(screen.getByText('分数运算')).toBeTruthy()
    expect(screen.getByText('通分')).toBeTruthy()
    expect(screen.getByText('异分母加法')).toBeTruthy()
    await user.click(screen.getByRole('tab', { name: '复测计划' }))
    await screen.findByRole('button', { name: '详情' })
    await user.click(screen.getByRole('button', { name: '详情' }))
    const eventRows = screen.getAllByRole('row', { name: /计算 1\/3 \+ 1\/6/ })
    const plannedRow = eventRows[0]
    const plannedDetailsRow = eventRows[1]
    expect(within(plannedRow).getByText(/实际日期未知.*独立作答.*人工确认独立/)).toBeTruthy()
    expect(within(plannedDetailsRow).getByText(/解题过程：正确 · 原图核实/)).toBeTruthy()
    expect(within(plannedDetailsRow).getByRole('link', { name: '查看本次作答' }).getAttribute('href')).toBe('/learning/attempts/old/')
    expect(screen.getByRole('link', { name: '打开题目' }).getAttribute('href')).toBe('/knowledge/questions/44/')
    expect(screen.getByRole('link', { name: '记录复测' }).getAttribute('href')).toContain('kind=retest')
    expect(screen.queryByText(/掌握率|掌握百分比|context-must-stay-private/)).toBeNull()
    await user.click(screen.getByRole('tab', { name: '学习证据' }))
    expect(await screen.findByRole('heading', { name: '知识、方法与题型进度' })).toBeTruthy()
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls.map(({ url }) => url.pathname).sort()).toEqual([
      '/api/v1/learners/learner-1/progress/',
      '/api/v1/learners/learner-1/schedules/',
    ])
    expect(calls.every(({ url }) => url.searchParams.get('household') === 'home-1')).toBe(true)
    expect(calls.every(({ init }) => init?.cache === 'no-store' && init?.credentials === 'same-origin')).toBe(true)
  })

  it('keeps an unknown actual date separate from the schedule recorded time and hides writes from viewers', async () => {
    const user = userEvent.setup()
    mountWorkspace('viewer')
    await screen.findByRole('button', { name: '详情' })
    await user.click(screen.getByRole('button', { name: '详情' }))
    expect(screen.queryByRole('button', { name: '改期' })).toBeNull()
    expect(screen.queryByRole('button', { name: '记录复测完成' })).toBeNull()
    expect(screen.queryByRole('button', { name: '取消计划' })).toBeNull()
    await user.click(screen.getByRole('button', { name: /完成\s+1/ }))
    await user.click(screen.getByRole('button', { name: '详情' }))
    expect(screen.getByRole('heading', { name: '计划与完成历史' })).toBeTruthy()
    expect(screen.getByText('实际作答日期：未知 · 已关联真实作答。')).toBeTruthy()
    const recordTimes = screen.getAllByText(/记录时间（本地）：2026/)
    expect(recordTimes).toHaveLength(2)
    expect(recordTimes.some((node) => node.textContent?.includes('09:30'))).toBe(true)
    expect(screen.queryByRole('button', { name: '新增复测计划' })).toBeNull()
    expect(screen.queryByRole('button', { name: '改期' })).toBeNull()
    expect(screen.queryByRole('button', { name: '记录复测完成' })).toBeNull()
  })

  it('creates a plan with the opaque options context, a request key and CSRF', async () => {
    const user = userEvent.setup()
    const { calls } = mountWorkspace('reviewer')
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    await user.type(screen.getByLabelText('复测日期（必填）'), '2026-10-20')
    await user.type(screen.getByLabelText('复测目标（必填）'), '独立完成两题')
    await user.type(screen.getByLabelText('提示安排（可留空）'), '先不提示')
    await user.type(screen.getByLabelText('创建原因（必填）'), '本周复习安排')
    await user.click(screen.getByRole('button', { name: '创建复测计划' }))

    await screen.findByText('新计划已创建。')
    const createCall = calls.find(({ url, init }) => init?.method === 'POST' && url.pathname === '/api/v1/learners/learner-1/schedules/')
    expect(createCall?.url.searchParams.get('household')).toBe('home-1')
    expect(createCall?.init?.headers).toMatchObject({ 'X-CSRFToken': 'csrf-test' })
    const body = JSON.parse(String(createCall?.init?.body))
    expect(body).toMatchObject({
      question_revision_id: 'question-revision-7', due_date: '2026-10-20',
      goal: '独立完成两题', prompt_plan: '先不提示', reason: '本周复习安排', expected: opaqueContext,
    })
    expect(body.request_key).toMatch(/^[0-9a-f-]{36}$/i)
    expect(screen.queryByText('context-must-stay-private')).toBeNull()
  })

  it('allows an empty prompt plan for an independent retest', async () => {
    const user = userEvent.setup()
    const { calls } = mountWorkspace()
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    await user.type(screen.getByLabelText('复测日期（必填）'), '2026-10-20')
    await user.type(screen.getByLabelText('复测目标（必填）'), '不提示独立完成')
    await user.type(screen.getByLabelText('创建原因（必填）'), '安排独立复测')
    expect(screen.getByRole('button', { name: '创建复测计划' }).matches(':disabled')).toBe(false)
    await user.click(screen.getByRole('button', { name: '创建复测计划' }))
    await waitFor(() => expect(calls.some(({ init }) => init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find(({ init }) => init?.method === 'POST')?.init?.body))
    expect(body.prompt_plan).toBe('')
    expect(body.expected).toEqual(opaqueContext)
  })

  it('locks question and refresh controls while a plan is being created', async () => {
    const user = userEvent.setup()
    let releasePost!: (response: Response) => void
    const pendingPost = new Promise<Response>((resolve) => { releasePost = resolve })
    mountWorkspace('owner', () => pendingPost)
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    await user.type(screen.getByLabelText('复测日期（必填）'), '2026-10-20')
    await user.type(screen.getByLabelText('复测目标（必填）'), '独立完成')
    await user.type(screen.getByLabelText('创建原因（必填）'), '安排复测')
    await user.click(screen.getByRole('button', { name: '创建复测计划' }))
    await screen.findByRole('button', { name: '正在保存…' })
    expect((screen.getByLabelText('题目') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '重新读取题目' }) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => { releasePost(Response.json({ schema_version: 'swb.api.v1', schedule_id: 88 })) })
    await screen.findByText('新计划已创建。')
  })

  it.each([200, 401])('preserves a reopened create form when the discarded request returns %s', async (status) => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let releasePost!: (response: Response) => void
    const pendingPost = new Promise<Response>((resolve) => { releasePost = resolve })
    const onUnsavedChange = vi.fn()
    const { unauthorized } = mountWorkspace('owner', () => pendingPost, schedules, { onUnsavedChange })
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    await user.type(screen.getByLabelText('复测日期（必填）'), '2026-10-20')
    await user.type(screen.getByLabelText('复测目标（必填）'), '已提交的旧计划')
    await user.type(screen.getByLabelText('创建原因（必填）'), '安排复测')
    await user.click(screen.getByRole('button', { name: '创建复测计划' }))
    await screen.findByRole('button', { name: '正在保存…' })

    await user.click(screen.getByRole('button', { name: '收起新计划' }))
    await user.click(screen.getByRole('button', { name: '新增复测计划' }))
    const newGoal = await screen.findByLabelText('复测目标（必填）') as HTMLInputElement
    await user.type(newGoal, '新的未保存计划')
    expect(onUnsavedChange.mock.calls).toEqual([[true], [false], [true]])

    await act(async () => {
      releasePost(Response.json(status === 200 ? { schema_version: 'swb.api.v1', schedule_id: 88 } : { detail: 'unauthorized' }, { status }))
    })

    expect(newGoal.isConnected).toBe(true)
    expect(newGoal.value).toBe('新的未保存计划')
    expect(screen.getByRole('button', { name: '收起新计划' })).toBeTruthy()
    expect(onUnsavedChange.mock.calls).toEqual([[true], [false], [true]])
    expect(screen.queryByText('新计划已创建。')).toBeNull()
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('aggregates dirty rows and keeps another row input when one is saved', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    const secondSchedule: ReviewSchedule = { ...plannedSchedule, id: 23, question_text: '另一道复测题' }
    const twoSchedules: SchedulesResponse = { ...schedules, counts: { pending: 2, overdue: 0, completed: 1, cancelled: 0 }, items: [plannedSchedule, secondSchedule, completedSchedule] }
    const { calls } = mountWorkspace('owner', undefined, twoSchedules, { onUnsavedChange })
    await screen.findByText('另一道复测题')

    await user.click(screen.getAllByRole('button', { name: '详情' })[0])
    await user.click(screen.getByRole('button', { name: '详情' }))
    await screen.findAllByRole('button', { name: '改期' })
    await user.click(screen.getAllByRole('button', { name: '改期' })[0])
    await user.click(screen.getAllByRole('button', { name: '改期' })[1])
    await user.type(screen.getAllByLabelText('本次操作原因（必填）')[0], '第一项改期原因')
    await user.type(screen.getAllByLabelText('本次操作原因（必填）')[1], '第二项改期原因')
    expect(onUnsavedChange.mock.calls).toEqual([[true]])

    await user.click(screen.getAllByRole('button', { name: '保存改期' })[0])
    await screen.findByText('已保存')
    const remainingReason = screen.getByLabelText('本次操作原因（必填）') as HTMLInputElement
    expect(remainingReason.value).toBe('第二项改期原因')
    expect(onUnsavedChange.mock.calls).toEqual([[true]])
    expect(calls.filter(({ init }) => init?.method === 'POST')).toHaveLength(1)
  })

  it('locks the submitted action fields until its response arrives', async () => {
    const user = userEvent.setup()
    let releasePost!: (response: Response) => void
    const pendingPost = new Promise<Response>((resolve) => { releasePost = resolve })
    mountWorkspace('owner', () => pendingPost)
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(screen.getByRole('button', { name: '改期' }))
    const reason = screen.getByLabelText('本次操作原因（必填）') as HTMLInputElement
    await user.type(reason, '本次已提交的原因')
    await user.click(screen.getByRole('button', { name: '保存改期' }))
    await screen.findByRole('button', { name: '正在保存…' })
    for (const label of ['新的复测日期（必填）', '复测目标', '提示安排', '本次操作原因（必填）']) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(true)
    }
    await user.type(reason, '不应加入等待中的输入')
    expect(reason.value).toBe('本次已提交的原因')
    await act(async () => { releasePost(Response.json({ schema_version: 'swb.api.v1', schedule_id: 21 })) })
    await screen.findByText('复测计划已保存，历史记录已更新。')
  })

  it('keeps failed action inputs, preserves them when discard is declined, and clears them when confirmed', async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onUnsavedChange = vi.fn()
    mountWorkspace('owner', async () => Response.json({ detail: 'stale schedule' }, { status: 409 }), schedules, { onUnsavedChange })
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(screen.getByRole('button', { name: '改期' }))
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '需要保留的改期原因')
    await user.click(screen.getByRole('button', { name: '保存改期' }))
    await screen.findByRole('alert')
    expect(onUnsavedChange.mock.calls).toEqual([[true]])

    await user.click(screen.getByRole('button', { name: '返回' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect((screen.getByLabelText('本次操作原因（必填）') as HTMLInputElement).value).toBe('需要保留的改期原因')
    expect(onUnsavedChange.mock.calls).toEqual([[true]])

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: '返回' }))
    expect(screen.queryByLabelText('本次操作原因（必填）')).toBeNull()
    expect(onUnsavedChange.mock.calls).toEqual([[true], [false]])
  })

  it('confirms before collapsing or refreshing away dirty create inputs', async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onUnsavedChange = vi.fn()
    mountWorkspace('owner', undefined, schedules, { onUnsavedChange })
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')

    await user.click(screen.getByRole('button', { name: '收起新计划' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect((screen.getByLabelText('题目') as HTMLSelectElement).value).toBe('question-revision-7')
    expect(onUnsavedChange.mock.calls).toEqual([[true]])

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: '收起新计划' }))
    expect(screen.queryByLabelText('题目')).toBeNull()
    expect(onUnsavedChange.mock.calls).toEqual([[true], [false]])

    await user.click(screen.getByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    confirm.mockReturnValue(false)
    await user.click(screen.getByRole('button', { name: '刷新全部' }))
    expect(confirm).toHaveBeenCalledTimes(3)
    expect((screen.getByLabelText('题目') as HTMLSelectElement).value).toBe('question-revision-7')

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: '刷新全部' }))
    await screen.findByRole('button', { name: '新增复测计划' })
    expect(screen.queryByLabelText('题目')).toBeNull()
    expect(onUnsavedChange.mock.calls.at(-1)).toEqual([false])
  })

  it('requires explicit selection of a server-provided real attempt before completing a plan', async () => {
    const user = userEvent.setup()
    const { calls } = mountWorkspace()
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(await screen.findByRole('button', { name: '记录复测完成' }))
    const submit = screen.getByRole('button', { name: '确认关联作答并完成' })
    expect(submit.matches(':disabled')).toBe(true)
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '孩子独立完成复测')
    expect(submit.matches(':disabled')).toBe(true)
    await user.selectOptions(screen.getByLabelText('选择这次复测对应的真实作答'), 'attempt-revision-1')
    await user.click(submit)

    await waitFor(() => expect(calls.some(({ init }) => init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find(({ init }) => init?.method === 'POST')?.init?.body))
    expect(body).toMatchObject({
      action: 'completed', expected: opaqueContext, reason: '孩子独立完成复测',
      attempt_revision_id: 'attempt-revision-1',
    })
    expect(body.request_key).toMatch(/^[0-9a-f-]{36}$/i)
  })

  it('keeps distinct same-day event labels and binds the explicitly selected revision', async () => {
    const choices = ['首次', '重做', '复测'].map((kind, index) => ({
      revision_id: `same-day-revision-${index}`,
      label: `2026-10-01 · ${kind} · 独立作答 · 人工确认独立／人工确认无提示 · 8 · #event00${index}`,
      actual_date: '2026-10-01', source_kind: 'independent_answer' as const,
    }))
    const { calls } = mountWorkspace('owner', undefined, { ...schedules, items: [{ ...plannedSchedule, attempt_choices: choices }] })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(screen.getByRole('button', { name: '记录复测完成' }))
    for (const choice of choices) expect(screen.getByRole('option', { name: choice.label }).textContent).toBe(choice.label)
    await user.selectOptions(screen.getByLabelText('选择这次复测对应的真实作答'), choices[1].revision_id)
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '明确选择第二次真实作答')
    await user.click(screen.getByRole('button', { name: '确认关联作答并完成' }))
    await waitFor(() => expect(calls.some(({ init }) => init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find(({ init }) => init?.method === 'POST')?.init?.body))
    expect(body.attempt_revision_id).toBe(choices[1].revision_id)
  })

  it('sends the same native context, reason and unique request key for reschedule and cancellation', async () => {
    const user = userEvent.setup()
    const { calls } = mountWorkspace()
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(await screen.findByRole('button', { name: '改期' }))
    await user.clear(screen.getByLabelText('新的复测日期（必填）'))
    await user.type(screen.getByLabelText('新的复测日期（必填）'), '2026-10-22')
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '需要调整时间')
    await user.click(screen.getByRole('button', { name: '保存改期' }))
    await waitFor(() => expect(calls.filter(({ init }) => init?.method === 'POST')).toHaveLength(1))
    const reschedule = JSON.parse(String(calls.find(({ init }) => init?.method === 'POST')?.init?.body))
    expect(reschedule).toMatchObject({ action: 'rescheduled', due_date: '2026-10-22', expected: opaqueContext, reason: '需要调整时间' })
    expect(reschedule.request_key).toMatch(/^[0-9a-f-]{36}$/i)

    await user.click(await screen.findByRole('button', { name: '取消计划' }))
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '本周暂停复习')
    await user.click(screen.getByRole('button', { name: '确认取消计划' }))
    await waitFor(() => expect(calls.filter(({ init }) => init?.method === 'POST')).toHaveLength(2))
    const cancellation = JSON.parse(String(calls.filter(({ init }) => init?.method === 'POST')[1].init?.body))
    expect(cancellation).toMatchObject({ action: 'cancelled', expected: opaqueContext, reason: '本周暂停复习' })
    expect(cancellation.request_key).toMatch(/^[0-9a-f-]{36}$/i)
  })

  it('aborts progress reads when the selected learner changes', async () => {
    let resolveOld!: (response: Response) => void
    let oldSignal: AbortSignal | null = null
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve })
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/learners/old/progress/') {
        oldSignal = init?.signal || null
        return oldResponse
      }
      if (url.pathname === '/api/v1/learners/new/progress/') return Promise.resolve(Response.json({ ...learnerProgress, scope: { ...learnerProgress.scope, learner_id: 'new' } }))
      if (url.pathname.endsWith('/schedules/')) return Promise.resolve(Response.json(schedules))
      throw new Error(`unexpected request: ${url.pathname}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const props = { householdId: 'home-1', csrfToken: 'csrf-test', canWrite: false, onUnauthorized: vi.fn() }
    const view = render(<ProgressWorkspace {...props} learner={{ ...learner, id: 'old' }} />)
    view.rerender(<ProgressWorkspace {...props} learner={{ ...learner, id: 'new' }} />)
    await waitFor(() => expect(oldSignal?.aborted).toBe(true))
    await act(async () => { resolveOld(Response.json(learnerProgress)) })
    expect(screen.queryByText('正在读取学习者的知识、方法和题型进度…')).toBeNull()
  })

  it('ignores a late save callback from an unmounted workspace after the new workspace becomes dirty', async () => {
    const user = userEvent.setup()
    let releasePost!: (response: Response) => void
    const pendingPost = new Promise<Response>((resolve) => { releasePost = resolve })
    const onUnsavedChange = vi.fn()
    const previous = mountWorkspace('owner', () => pendingPost, schedules, { onUnsavedChange })
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    await user.type(screen.getByLabelText('复测日期（必填）'), '2026-10-20')
    await user.type(screen.getByLabelText('复测目标（必填）'), '独立完成')
    await user.type(screen.getByLabelText('创建原因（必填）'), '计划原因')
    await user.click(screen.getByRole('button', { name: '创建复测计划' }))
    await screen.findByRole('button', { name: '正在保存…' })
    expect(onUnsavedChange.mock.calls).toEqual([[true]])

    previous.view.unmount()
    const next = mountWorkspace('owner', undefined, schedules, { onUnsavedChange })
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(screen.getByRole('button', { name: '改期' }))
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '新工作区仍有未保存内容')
    expect(onUnsavedChange.mock.calls).toEqual([[true], [true]])

    await act(async () => { releasePost(Response.json({ schema_version: 'swb.api.v1', schedule_id: 88 })) })
    expect(onUnsavedChange.mock.calls).toEqual([[true], [true]])
    expect((screen.getByLabelText('本次操作原因（必填）') as HTMLInputElement).value).toBe('新工作区仍有未保存内容')
    next.view.unmount()
  })

  it('validates external tabs, reports tab changes, and keeps create and action inputs across tab switches', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onTabChange = vi.fn()
    const mounted = mountWorkspace('owner', undefined, schedules, { initialTab: 'materials', onTabChange })
    const view = mounted.view
    const props = { householdId: 'home-1', learner, csrfToken: 'csrf-test', canWrite: true, onUnauthorized: mounted.unauthorized, onTabChange }
    expect((await screen.findByRole('tab', { name: '复测计划' })).getAttribute('aria-selected')).toBe('true')
    expect(onTabChange).toHaveBeenLastCalledWith('plans')
    await user.click(await screen.findByRole('button', { name: '新增复测计划' }))
    await user.selectOptions(await screen.findByLabelText('题目'), 'question-revision-7')
    await user.type(screen.getByLabelText('复测日期（必填）'), '2026-10-20')
    await user.type(screen.getByLabelText('复测目标（必填）'), '独立完成两题')
    await user.click(screen.getByRole('tab', { name: '学习证据' }))
    await user.click(screen.getByRole('tab', { name: '复测计划' }))
    expect((screen.getByLabelText('题目') as HTMLSelectElement).value).toBe('question-revision-7')
    expect((screen.getByLabelText('复测日期（必填）') as HTMLInputElement).value).toBe('2026-10-20')

    await user.click(screen.getByRole('button', { name: '取消' }))
    await user.click(await screen.findByRole('button', { name: '详情' }))
    await user.click(screen.getByRole('button', { name: '改期' }))
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '调整后的说明')
    await user.click(screen.getByRole('tab', { name: '学习证据' }))
    await user.click(screen.getByRole('tab', { name: '复测计划' }))
    expect((screen.getByLabelText('本次操作原因（必填）') as HTMLInputElement).value).toBe('调整后的说明')
    await user.click(screen.getByRole('button', { name: /近期（7天内）/ }))
    expect(screen.getByText('近期没有待到期计划')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /今天\s+1/ }))
    await user.click(screen.getByRole('button', { name: /已完成\s+1/ }))
    await user.click(screen.getByRole('button', { name: /今天\s+1/ }))
    expect((screen.getByLabelText('本次操作原因（必填）') as HTMLInputElement).value).toBe('调整后的说明')

    await user.click(screen.getByRole('button', { name: '返回' }))
    await user.click(screen.getByRole('button', { name: '记录复测完成' }))
    await user.type(screen.getByLabelText('本次操作原因（必填）'), '本次实际复测')
    await user.selectOptions(screen.getByLabelText('选择这次复测对应的真实作答'), 'attempt-revision-1')
    await user.click(screen.getByRole('tab', { name: '学习证据' }))
    await user.click(screen.getByRole('tab', { name: '复测计划' }))
    expect((screen.getByLabelText('选择这次复测对应的真实作答') as HTMLSelectElement).value).toBe('attempt-revision-1')

    view.rerender(<ProgressWorkspace {...props} initialTab='invalid' />)
    await waitFor(() => expect(screen.getByRole('tab', { name: '复测计划' }).getAttribute('aria-selected')).toBe('true'))
  })

  it('shows the empty state for zero plans and filters one hundred rows by server status', async () => {
    const user = userEvent.setup()
    const empty: SchedulesResponse = { ...schedules, counts: { pending: 0, overdue: 0, completed: 0, cancelled: 0 }, items: [] }
    const mounted = mountWorkspace('viewer', undefined, empty)
    expect(await screen.findByText('还没有复测计划')).toBeTruthy()

    const one: SchedulesResponse = { ...schedules, counts: { pending: 1, overdue: 0, completed: 0, cancelled: 0 }, items: [plannedSchedule] }
    mounted.setScheduleResponse(one)
    mounted.view.rerender(<ProgressWorkspace householdId='home-2' learner={learner} csrfToken='csrf-test' canWrite={false} onUnauthorized={mounted.unauthorized} />)
    await screen.findByRole('button', { name: '计算 1/3 + 1/6' })
    expect(screen.getAllByRole('button', { name: '详情' })).toHaveLength(1)

    const twentyItems = Array.from({ length: 20 }, (_, index): ReviewSchedule => ({
      ...plannedSchedule,
      id: index + 200,
      question_text: `第 ${index + 1} 项复测`,
      state: index < 10 ? 'planned' : index < 15 ? 'completed' : 'cancelled',
      overdue: index < 5,
    }))
    const twenty: SchedulesResponse = { ...schedules, counts: { pending: 10, overdue: 5, completed: 5, cancelled: 5 }, items: twentyItems }
    mounted.setScheduleResponse(twenty)
    mounted.view.rerender(<ProgressWorkspace householdId='home-3' learner={learner} csrfToken='csrf-test' canWrite={false} onUnauthorized={mounted.unauthorized} />)
    await screen.findByText('第 6 项复测')
    expect(screen.getAllByRole('button', { name: '详情' })).toHaveLength(5)
    await user.click(screen.getByRole('button', { name: /已完成\s+5/ }))
    expect(screen.getAllByRole('button', { name: '详情' })).toHaveLength(5)
    await user.click(screen.getByRole('button', { name: /逾期\s+5/ }))
    expect(screen.getAllByRole('button', { name: '详情' })).toHaveLength(5)

    const items = Array.from({ length: 100 }, (_, index): ReviewSchedule => {
      const state: ReviewSchedule['state'] = index < 50 ? 'planned' : index < 75 ? 'completed' : 'cancelled'
      return {
        ...plannedSchedule,
        id: index + 100,
        question_text: `百项第 ${index + 1} 项复测`,
        state,
        overdue: index >= 25 && index < 50,
      }
    })
    const many: SchedulesResponse = { ...schedules, counts: { pending: 50, overdue: 25, completed: 25, cancelled: 25 }, items }
    mounted.setScheduleResponse(many)
    mounted.view.rerender(<ProgressWorkspace householdId='home-4' learner={learner} csrfToken='csrf-test' canWrite={false} onUnauthorized={mounted.unauthorized} />)
    await screen.findByText('百项第 1 项复测')
    await user.click(screen.getByRole('button', { name: /今天\s+25/ }))
    expect(screen.getAllByRole('button', { name: '详情' })).toHaveLength(25)
    await user.click(screen.getByRole('button', { name: /逾期\s+25/ }))
    expect(screen.getAllByRole('button', { name: '详情' })).toHaveLength(25)
    expect(screen.getAllByText('已逾期')).toHaveLength(25)
  }, 15000)

  it('groups plans by the service date and lets an empty today view reach real upcoming work', async () => {
    const user = userEvent.setup()
    const upcoming: ReviewSchedule = { ...plannedSchedule, id: 31, question_text: '近期复测题', due_date: '2026-10-08' }
    const overdue: ReviewSchedule = { ...plannedSchedule, id: 32, question_text: '逾期复测题', due_date: '2026-10-05', overdue: true }
    const mounted = mountWorkspace('viewer', undefined, { ...schedules, items: [upcoming, overdue] })

    expect(await screen.findByText('今天没有安排的复测')).toBeTruthy()
    expect(screen.getByText(/计划为空不代表没有待办/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /查看近期计划/ }))
    expect(await screen.findByRole('button', { name: '近期复测题' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /逾期\s+1/ }))
    expect(screen.getByRole('button', { name: '逾期复测题' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '近期复测题' })).toBeNull()
    mounted.view.unmount()
  })

  it('separates today, near-term, later, unscheduled, completed and cancelled plans', async () => {
    const user = userEvent.setup()
    const today = { ...plannedSchedule, id: 41, question_text: '今天复测题' }
    const upcoming = { ...plannedSchedule, id: 42, question_text: '近期复测题', due_date: '2026-10-08' }
    const later = { ...plannedSchedule, id: 43, question_text: '之后复测题', due_date: '2026-10-20' }
    const unscheduled = { ...plannedSchedule, id: 44, question_text: '日期未知复测题', due_date: '' }
    const overdue = { ...plannedSchedule, id: 45, question_text: '逾期复测题', due_date: '2026-10-05', overdue: true }
    const completed = { ...completedSchedule, question_text: '已完成复测题' }
    const cancelled = { ...plannedSchedule, id: 46, question_text: '已取消复测题', state: 'cancelled' as const }
    const { view } = mountWorkspace('viewer', undefined, { ...schedules, items: [today, upcoming, later, unscheduled, overdue, completed, cancelled] })
    expect(await screen.findByRole('button', { name: '今天复测题' })).toBeTruthy()
    const filters: Array<[RegExp, string]> = [
      [/近期（7天内）\s+1/, '近期复测题'],
      [/逾期\s+1/, '逾期复测题'],
      [/之后\s+1/, '之后复测题'],
      [/日期未记录\s+1/, '日期未知复测题'],
      [/已完成\s+1/, '已完成复测题'],
      [/已取消\s+1/, '已取消复测题'],
    ]
    for (const [filter, question] of filters) {
      await user.click(screen.getByRole('button', { name: filter }))
      expect(screen.getByRole('button', { name: question })).toBeTruthy()
      expect(screen.queryByRole('button', { name: '今天复测题' })).toBeNull()
    }
    view.unmount()
  })
})
