import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EvidenceWorkspace } from './workspace'
import type { AttemptResponse, Learner, OverviewResponse } from '../../types'

const learner = (id: string): Learner => ({ id, display_name: id, grade: null, profile_url: `/learning/profile/${id}/`, report_url: '/report/' })

function attempts(questionText: string): AttemptResponse {
  return {
    schema_version: 'swb.api.v1',
    scope: { household_id: 'home-1', learner_id: 'learner-1', date_from: null, date_to: null, source_kind: null, metric_version: 'evidence.v1' },
    items: [{
      attempt_id: 'attempt-private', attempt_revision_id: 'revision-private', attempt_kind: 'written', attempt_kind_label: '书面作答',
      source_kind: 'unknown', source_kind_label: '来源未知', independence: 'unknown', prompt_status: 'unknown', prompts: [],
      actual_date_state: 'unknown', actual_date: null, legibility: 'unknown', answer_text: '', state: 'active',
      question_id: 'question-private', question_revision_id: 'question-revision-private', question_text: questionText,
      independent_success: false, sources: [], assessments: [], attempt_url: '/web/attempts/view/', question_url: null, previous_attempt_id: null,
    }],
    total: 1, page: 1, page_size: 20,
  }
}

function emptyOverview(): OverviewResponse {
  return {
    schema_version: 'swb.api.v1',
    history_attempt_count: 0,
    recent_attempts: [],
    scope: { household_id: 'home-1', learner_id: 'learner-1', date_from: null, date_to: null, source_kind: null, metric_version: 'evidence.v1' },
    metrics: { attempt_count: 0, question_count: 0, source_counts: {}, unknown_date_count: 0, independent_success_count: 0, independent_success_rate: null, rate_state: 'not_provided', repeated_error_count: 0, insufficient_evidence_count: 0 },
    findings: { observed_correct_methods: [], insufficient_evidence: [], repeated_errors: [], known_actual_date_intervals: [] },
    links: { profile_url: '/learning/profile/learner-1/', record_attempt_url: '/learning/profile/learner-1/attempt/new/', report_url: null, schedule_url: null },
  }
}

describe('EvidenceWorkspace', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('keeps unknown dates and missing answers explicit, and sends the chosen filters', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.endsWith('/overview/')) return Response.json(emptyOverview())
      return Response.json(attempts('题干待核对'))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<EvidenceWorkspace householdId='home-1' learner={learner('learner-1')} activePage='attempts' onUnauthorized={vi.fn()} />)
    expect((await screen.findByText('来源未知')).textContent).toContain('来源未知')
    expect(screen.getByText('日期未知')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '查看详情' }))
    expect(screen.getByText('实际作答日期未知')).toBeTruthy()
    expect(screen.getByText('作答内容未记录。')).toBeTruthy()
    expect(screen.getByText('尚无评价记录，不能据此推断掌握状态。')).toBeTruthy()
    expect(screen.getByRole('link', { name: '查看这次作答及完整历史' }).getAttribute('href')).toBe('/web/attempts/view/')
    expect(screen.queryByText('active')).toBeNull()
    expect(screen.queryByText('unknown')).toBeNull()

    fireEvent.change(screen.getByLabelText('实际作答日期起'), { target: { value: '2026-10-01' } })
    await user.selectOptions(screen.getByLabelText('作答来源'), 'unknown')
    expect((await screen.findAllByText('题干待核对')).length).toBeGreaterThan(0)
    const requestUrls = fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin))
    expect(requestUrls.some((url) => url.searchParams.get('date_from') === '2026-10-01' && url.searchParams.get('source_kind') === 'unknown')).toBe(true)
  })

  it('offers a retry after request failures and displays an empty result without invented data', async () => {
    const user = userEvent.setup()
    let calls = 0
    const fetchMock = vi.fn(async () => {
      calls += 1
      if (calls === 1) return Response.json({ schema_version: 'swb.api.v1', error: { code: 'temporary', message: '服务暂不可用' } }, { status: 503 })
      return Response.json({ ...attempts(''), items: [], total: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<EvidenceWorkspace householdId='home-1' learner={learner('learner-1')} activePage='attempts' onUnauthorized={vi.fn()} />)
    expect((await screen.findByText('服务暂不可用')).textContent).toContain('服务暂不可用')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect((await screen.findByText('还没有作答记录')).textContent).toContain('还没有作答记录')
    expect(screen.getByRole('link', { name: '记录首次作答' }).getAttribute('href')).toBe('/learning/profile/learner-1/attempt/new/')
    expect(calls).toBe(2)
  })

  it('explains the counting conditions without rendering a success percentage', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(emptyOverview())))
    render(<EvidenceWorkspace householdId='home-1' learner={learner('learner-1')} activePage='overview' onUnauthorized={vi.fn()} />)
    expect((await screen.findByText(/日期筛选只匹配已知的实际作答日期/)).textContent).toContain('不等于长期掌握')
    expect(screen.getByText('实际日期未知（来源范围）')).toBeTruthy()
    expect(screen.queryByText('not_provided')).toBeNull()
    expect(screen.queryByText(/独立成功比例/)).toBeNull()
  })

  it('initializes and restores filters from route state, and reports user changes', async () => {
    const onFiltersChange = vi.fn()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      return url.pathname.endsWith('/overview/') ? Response.json(emptyOverview()) : Response.json(attempts(''))
    })
    vi.stubGlobal('fetch', fetchMock)
    const props = {
      householdId: 'home-1',
      learner: learner('learner-1'),
      activePage: 'overview' as const,
      onUnauthorized: vi.fn(),
      onFiltersChange,
    }
    const view = render(<EvidenceWorkspace {...props} initialFilters={{ dateFrom: '2026-10-01', dateTo: '', sourceKind: '' }} />)
    await screen.findByRole('heading', { name: '当前范围摘要' })
    expect((screen.getByLabelText('实际作答日期起') as HTMLInputElement).value).toBe('2026-10-01')

    fireEvent.change(screen.getByLabelText('实际作答日期止'), { target: { value: '2026-10-06' } })
    expect(onFiltersChange).toHaveBeenLastCalledWith({ dateFrom: '2026-10-01', dateTo: '2026-10-06', sourceKind: '' })

    view.rerender(<EvidenceWorkspace {...props} initialFilters={{ dateFrom: '', dateTo: '2026-10-03', sourceKind: 'independent_answer' }} />)
    expect((screen.getByLabelText('实际作答日期起') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('实际作答日期止') as HTMLInputElement).value).toBe('2026-10-03')
    expect((screen.getByLabelText('作答来源') as HTMLSelectElement).value).toBe('independent_answer')
    const urls = fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin))
    expect(urls.some((url) => url.searchParams.get('date_to') === '2026-10-03' && url.searchParams.get('source_kind') === 'independent_answer')).toBe(true)
  })

  it('separates an empty history from a filtered zero result and clears conditions', async () => {
    const user = userEvent.setup()
    const response = { ...emptyOverview(), history_attempt_count: 3 }
    const fullHistory = {
      ...response,
      metrics: { ...response.metrics, attempt_count: 3, question_count: 2 },
      recent_attempts: [attempts('已恢复的历史记录').items[0]],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      return Response.json(url.searchParams.has('date_from') ? response : fullHistory)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<EvidenceWorkspace
      householdId='home-1'
      learner={learner('learner-1')}
      activePage='overview'
      initialFilters={{ dateFrom: '2026-10-01', dateTo: '', sourceKind: '' }}
      onUnauthorized={vi.fn()}
    />)

    expect(await screen.findByText('当前筛选范围没有作答记录')).toBeTruthy()
    expect(screen.queryByText('还没有作答记录')).toBeNull()
    await user.click(screen.getByRole('button', { name: '查看全部作答记录' }))
    expect((screen.getByLabelText('实际作答日期起') as HTMLInputElement).value).toBe('')
    expect(await screen.findByText('已恢复的历史记录')).toBeTruthy()
    expect(screen.queryByText('当前筛选范围没有作答记录')).toBeNull()
    const urls = fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin))
    expect(urls.some((url) => url.pathname.endsWith('/overview/') && !url.searchParams.has('date_from'))).toBe(true)
  })

  it('shows recent real events in date order and keeps each unresolved event and revision distinct', async () => {
    const user = userEvent.setup()
    const response = emptyOverview()
    response.history_attempt_count = 4
    response.metrics = {
      attempt_count: 4, question_count: 3, source_counts: { independent_answer: 4 }, unknown_date_count: 1,
      independent_success_count: 1, independent_success_rate: null, rate_state: 'not_provided', repeated_error_count: 0, insufficient_evidence_count: 2,
    }
    const datedA = attempts('最近题目 A').items[0]
    datedA.attempt_id = 'attempt-date-a'
    datedA.actual_date_state = 'known'
    datedA.actual_date = '2026-10-06'
    datedA.attempt_kind_label = '复测'
    const datedB = { ...datedA, attempt_id: 'attempt-date-b', actual_date: '2026-10-03', question_text: '最近题目 B' }
    const unknown = { ...datedA, attempt_id: 'attempt-unknown', actual_date_state: 'unknown', actual_date: null, question_text: '日期未知题目' }
    response.recent_attempts = [datedA, datedB, unknown]
    const older = { ...datedA, attempt_id: 'attempt-older', actual_date: '2026-09-28', question_text: '较早但可辨认的题目', attempt_url: '/web/attempts/older/' }
    response.finding_attempts = [older]
    response.findings.observed_correct_methods = [
      { attempt_id: 'attempt-date-a', attempt_revision_id: 'attempt-rev-a', assessment_revision_id: 'assessment-rev-a1', question_id: 'question-a', question_revision_id: 'question-rev-a', dimension: 'process', dimension_label: '解题过程', sources: [] },
      { attempt_id: 'attempt-date-a', attempt_revision_id: 'attempt-rev-a', assessment_revision_id: 'assessment-rev-a2', question_id: 'question-a', question_revision_id: 'question-rev-a', dimension: 'answer', dimension_label: '答案', sources: [] },
      { attempt_id: 'attempt-older', attempt_revision_id: 'attempt-rev-old', assessment_revision_id: 'assessment-rev-old', question_id: 'question-old', question_revision_id: 'question-rev-old', dimension: 'process', dimension_label: '旧事件的解题过程', sources: [] },
    ]
    response.findings.insufficient_evidence = [
      { attempt_id: 'attempt-date-a', assessment_revision_id: 'assessment-rev-a1', dimension: 'calculation', dimension_label: '计算', judgment: 'unknown', basis: 'undetermined', judgment_label: '尚未核实', basis_label: '依据不足', reason: '过程尚未记录', sources: [] },
      { attempt_id: 'attempt-date-a', assessment_revision_id: 'assessment-rev-a1', dimension: 'notation', dimension_label: '符号表达', judgment: 'unknown', basis: 'undetermined', judgment_label: '尚未核实', basis_label: '依据不足', reason: '符号需要对照原图', sources: [] },
      { attempt_id: 'attempt-date-a', assessment_revision_id: 'assessment-rev-a2', dimension: 'overall', dimension_label: '整体证据', judgment: 'unknown', basis: 'undetermined', judgment_label: '尚未核实', basis_label: '依据不足', reason: '另一评价版本的原始原因', sources: [] },
      { attempt_id: 'attempt-older', assessment_revision_id: 'assessment-rev-old', dimension: 'method', dimension_label: '旧事件的方法', judgment: 'unknown', basis: 'undetermined', judgment_label: '尚未核实', basis_label: '依据不足', reason: '旧事件保留的原因', sources: [] },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(response)))
    render(<EvidenceWorkspace householdId='home-1' learner={learner('learner-1')} activePage='overview' onUnauthorized={vi.fn()} />)

    const recent = await screen.findByRole('heading', { name: '近期作答记录' })
    const recentText = recent.parentElement?.parentElement?.textContent || ''
    expect(recentText.indexOf('最近题目 A')).toBeLessThan(recentText.indexOf('最近题目 B'))
    expect(recentText.indexOf('最近题目 B')).toBeLessThan(recentText.indexOf('日期未知题目'))
    expect(recentText).toContain('实际作答日期未知')

    await user.click(screen.getByText('家长关注 · 过程观察与待核实证据'))
    const groups = await screen.findByRole('heading', { name: '尚未充分核实' })
    const unconfirmedSection = groups.closest('section')
    const eventList = unconfirmedSection?.querySelector('ul')
    expect(eventList?.querySelectorAll(':scope > li')).toHaveLength(2)
    expect(within(unconfirmedSection as HTMLElement).getByText('较早但可辨认的题目')).toBeTruthy()
    expect(within(unconfirmedSection as HTMLElement).getAllByRole('link', { name: '查看本次作答' }).some((link) => link.getAttribute('href') === '/web/attempts/older/')).toBe(true)
    await user.click(screen.getByText(/查看 3 项维度、评价修订和原图来源/))
    expect(within(unconfirmedSection as HTMLElement).getAllByText('已记录评价修订')).toHaveLength(3)
    expect(within(unconfirmedSection as HTMLElement).getAllByText('过程尚未记录')).toHaveLength(1)
    expect(screen.getByText('符号需要对照原图')).toBeTruthy()
    expect(screen.getByText('另一评价版本的原始原因')).toBeTruthy()
    const sectionFlow = unconfirmedSection?.parentElement?.parentElement
    expect(sectionFlow?.className).toContain('space-y-8')
    expect(sectionFlow?.className).not.toContain('grid')
    const correctSection = screen.getByRole('heading', { name: '已观察到的正确方法与过程' }).closest('section')
    expect(within(correctSection as HTMLElement).getByText('较早但可辨认的题目')).toBeTruthy()
    expect(within(correctSection as HTMLElement).getAllByRole('link', { name: '查看本次作答' }).some((link) => link.getAttribute('href') === '/web/attempts/older/')).toBe(true)
  })

  it('keeps filters visible and preserves them while switching between summary and attempt history', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      return url.pathname.endsWith('/overview/')
        ? Response.json(emptyOverview())
        : Response.json(attempts('单独保留的这次作答'))
    })
    const onTabChange = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const props = { householdId: 'home-1', learner: learner('learner-1'), activePage: 'overview' as const, onTabChange, onUnauthorized: vi.fn() }
    const view = render(<EvidenceWorkspace {...props} initialTab='overview' />)

    expect(await screen.findByRole('heading', { name: '学习概况' })).toBeTruthy()
    const dateFrom = screen.getByLabelText('实际作答日期起') as HTMLInputElement
    fireEvent.change(dateFrom, { target: { value: '2026-10-02' } })
    await user.click(screen.getByRole('tab', { name: '作答记录' }))

    expect((await screen.findAllByText('单独保留的这次作答')).length).toBeGreaterThan(0)
    expect((screen.getByLabelText('实际作答日期起') as HTMLInputElement).value).toBe('2026-10-02')
    expect(onTabChange).toHaveBeenCalledWith('attempts')
    view.rerender(<EvidenceWorkspace {...props} initialTab='attempts' />)
    expect(screen.getByRole('tab', { name: '作答记录' }).getAttribute('aria-selected')).toBe('true')
    view.rerender(<EvidenceWorkspace {...props} initialTab='overview' />)
    expect(await screen.findByRole('heading', { name: '学习概况' })).toBeTruthy()
    expect((screen.getByLabelText('实际作答日期起') as HTMLInputElement).value).toBe('2026-10-02')
    const requestUrls = fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin))
    expect(requestUrls.some((url) => url.pathname.endsWith('/attempts/') && url.searchParams.get('date_from') === '2026-10-02')).toBe(true)
  })

  it('shows an available original photo beside its unknown assessment and explains a missing photo', async () => {
    const user = userEvent.setup()
    const longQuestion = '需要对照来源的作答。'.repeat(20)
    const response = attempts(longQuestion)
    response.items[0].sources = [
      { image_id: 'private-image', region_id: 'private-region', region_revision_id: 'private-region-revision', purpose: 'handwriting', label: '作业照片', page_url: '/web/pages/original/', preview_url: '/web/pages/preview/', region_style: 'left:12.0000%;top:20.0000%;width:30.0000%;height:18.0000%;', missing: false },
      { image_id: 'missing-image', region_id: 'missing-region', region_revision_id: 'missing-region-revision', purpose: 'other', label: '旧照片', page_url: null, preview_url: null, region_style: '', missing: true },
    ]
    response.items[0].assessments = [{
      assessment_id: 'private-assessment', assessment_revision_id: 'private-assessment-revision', attempt_revision_id: 'revision-private',
      review_state: 'draft', current: false, review_state_label: '待核对', published: false, reviewer_id: null,
      dimensions: [{ dimension: 'accuracy', judgment: 'unknown', basis: 'undetermined', dimension_label: '答案正确性', judgment_label: '尚未核实', basis_label: '依据不足', rationale: '', unknown_reason: '照片看不清', sources: [] }],
    }]
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(response)))
    render(<EvidenceWorkspace householdId='home-1' learner={learner('learner-1')} activePage='attempts' onUnauthorized={vi.fn()} />)

    const questionText = await screen.findAllByText(longQuestion)
    expect(questionText.length).toBeGreaterThan(0)
    expect(questionText[0].className).toContain('whitespace-pre-wrap')
    const original = screen.getByRole('img', { name: '作业照片，原图' })
    expect(original).toBeTruthy()
    const selectedDetails = screen.getByRole('region', { name: '所选作答详情' })
    const columns = selectedDetails.parentElement
    expect(columns?.className).toContain('xl:grid-cols-')
    expect(columns?.querySelector('[aria-labelledby="attempt-list-heading"]')).toBeTruthy()
    expect(Array.from(columns?.querySelectorAll('div') || []).some((element) => element.className.includes('xl:max-h-[70vh]'))).toBe(true)
    expect(screen.getByText('选择作答，核对原图与评价。')).toBeTruthy()
    const imageFrame = original.parentElement
    expect(imageFrame?.className).toContain('inline-block')
    expect(original.className).toContain('w-auto')
    expect(original.className).toContain('max-h-96')
    expect(original.className).not.toContain('object-contain')
    const selection = imageFrame?.querySelector('.border-amber-600')
    expect(selection).toBeTruthy()
    expect(selection?.parentElement).toBe(imageFrame)
    await user.click(screen.getByRole('button', { name: '查看详情' }))
    expect(screen.getByText('原图暂不可用')).toBeTruthy()
    expect(screen.getByText('尚未核实 · 依据不足')).toBeTruthy()
    expect(screen.getByText('未确定原因：照片看不清')).toBeTruthy()
    expect(screen.queryByText('private-image')).toBeNull()
    expect(screen.queryByText('private-assessment-revision')).toBeNull()
  })

  it('aborts and ignores a stale learner response after selection changes', async () => {
    let resolveFirst: (response: Response) => void = () => undefined
    const firstSignal: { current: AbortSignal | null } = { current: null }
    const firstResponse = new Promise<Response>((resolve) => { resolveFirst = resolve })
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/old-learner/')) {
        firstSignal.current = init?.signal || null
        return firstResponse
      }
      return Promise.resolve(Response.json(attempts('new learner record')))
    })
    vi.stubGlobal('fetch', fetchMock)
    const props = { householdId: 'home-1', activePage: 'attempts' as const, onUnauthorized: vi.fn() }
    const view = render(<EvidenceWorkspace {...props} learner={learner('old-learner')} />)
    view.rerender(<EvidenceWorkspace {...props} learner={learner('new-learner')} />)
    expect((await screen.findAllByText('new learner record')).length).toBeGreaterThan(0)
    expect(firstSignal.current?.aborted).toBe(true)
    await act(async () => { resolveFirst(Response.json(attempts('stale learner record'))) })
    expect(screen.queryByText('stale learner record')).toBeNull()
  })
})
