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
    await screen.findByText('题干待核对')
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
    expect((await screen.findByText('new learner record')).textContent).toContain('new learner record')
    expect(firstSignal.current?.aborted).toBe(true)
    await act(async () => { resolveFirst(Response.json(attempts('stale learner record'))) })
    expect(screen.queryByText('stale learner record')).toBeNull()
  })
})
