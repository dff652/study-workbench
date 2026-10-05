import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EvidenceWorkspace } from './workspace'
import type { AttemptResponse, Learner, OverviewResponse } from '../../types'

const learner = (id: string): Learner => ({ id, display_name: id, grade: null, profile_url: '/profile/', report_url: '/report/' })

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
    scope: { household_id: 'home-1', learner_id: 'learner-1', date_from: null, date_to: null, source_kind: null, metric_version: 'evidence.v1' },
    metrics: { attempt_count: 0, question_count: 0, source_counts: {}, unknown_date_count: 0, independent_success_count: 0, independent_success_rate: null, rate_state: 'not_provided', repeated_error_count: 0, insufficient_evidence_count: 0 },
    findings: { observed_correct_methods: [], insufficient_evidence: [], repeated_errors: [], known_actual_date_intervals: [] },
    links: { profile_url: null, report_url: null, schedule_url: null },
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
    expect((await screen.findByText('还没有符合条件的记录')).textContent).toContain('还没有符合条件的记录')
    expect(calls).toBe(2)
  })

  it('uses a plain Chinese note instead of showing a raw success-rate state', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(emptyOverview())))
    render(<EvidenceWorkspace householdId='home-1' learner={learner('learner-1')} activePage='overview' onUnauthorized={vi.fn()} />)
    expect((await screen.findByText(/目前只展示已经核对的记录数量/)).textContent).toContain('没有记录的部分仍保留未知')
    expect(screen.queryByText('not_provided')).toBeNull()
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
