import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Attempt, LearnerProgressResponse } from '../../types'
import { LearnerProgress } from './learner-progress'

const recentAttempt: Attempt = {
  attempt_id: 'attempt-1', attempt_revision_id: 'attempt-revision-1', attempt_kind: 'retest', attempt_kind_label: '复测',
  source_kind: 'independent_answer', source_kind_label: '独立作答', independence: 'unknown', independence_label: '独立性未知',
  prompt_status: 'unknown', prompt_status_label: '提示情况未知', prompts: [], actual_date_state: 'unknown', actual_date: null,
  legibility: 'unknown', legibility_label: '清晰度未知', answer_text: '', state: 'active', state_label: '有效',
  question_id: 'question-1', question_revision_id: 'question-revision-1', question_text: '分数加法练习', independent_success: false,
  sources: [], assessments: [{
    assessment_id: 'assessment-1', assessment_revision_id: 'assessment-revision-1', attempt_revision_id: 'attempt-revision-1',
    review_state: 'accepted', current: true, review_state_label: '已接受', published: true, reviewer_id: 'reviewer-1', dimensions: [{
      dimension: 'answer', judgment: 'unknown', basis: 'undetermined', dimension_label: '答案', judgment_label: '未确定',
      basis_label: '依据未确定', rationale: '', unknown_reason: '原图不清楚', sources: [],
    }],
  }],
  attempt_url: '/learning/attempts/1/', question_url: '/knowledge/questions/1/', previous_attempt_id: null,
}

function response(groups: LearnerProgressResponse['groups']): LearnerProgressResponse {
  return {
    schema_version: 'swb.api.v1',
    scope: { household_id: 'family 1', learner_id: 'learner-1', metric_version: 'progress.v1', as_of: '2026-10-06' },
    groups,
  }
}

describe('LearnerProgress', () => {
  afterEach(cleanup)

  it('gives an actionable destination when there are no confirmed associations', () => {
    render(<LearnerProgress remote={{ status: 'loaded', data: response([]) }} onRetry={vi.fn()} />)

    expect(screen.getByText('还没有已确认的学习关联')).toBeTruthy()
    expect(screen.getByRole('link', { name: '前往知识与题库检查题目关联' }).getAttribute('href'))
      .toBe('/knowledge/?household_id=family%201&mode=learn#question-index')
    expect(screen.queryByText(/正确率|掌握率|连续天数/)).toBeNull()
  })

  it('expands real attempt evidence while keeping an unknown date and assessment unknown', async () => {
    const user = userEvent.setup()
    render(<LearnerProgress remote={{ status: 'loaded', data: response([{
      id: 'knowledge-1', kind: 'knowledge', label: '分数运算', question_count: 1, attempt_count: 1,
      independent_success_count: 0, unknown_evidence_count: 1, source_counts: { independent_answer: 1 },
      node_url: '/knowledge/1/', recent_attempts: [recentAttempt],
    }]) }} onRetry={vi.fn()} />)

    expect(screen.getByText('未知或待核实')).toBeTruthy()
    await user.click(screen.getByText('分数加法练习'))
    expect(screen.getByText(/实际作答日期未知/)).toBeTruthy()
    expect(screen.getByText('独立性未知')).toBeTruthy()
    expect(screen.getByText('提示情况未知')).toBeTruthy()
    expect(screen.getByText('答案')).toBeTruthy()
    expect(screen.getByText('未确定 · 依据未确定')).toBeTruthy()
    expect(screen.getByText('未确定原因：原图不清楚')).toBeTruthy()
    expect(screen.getByRole('link', { name: '查看本次作答' }).getAttribute('href')).toBe('/learning/attempts/1/')
    expect(screen.queryByText(/记录时间|掌握率|正确率|连续天数/)).toBeNull()
  })

  it('distinguishes an unassociated node from an associated but unmeasured node', () => {
    render(<LearnerProgress remote={{ status: 'loaded', data: response([{
      id: 'method-1', kind: 'method', label: '通分', question_count: 0, attempt_count: 0,
      independent_success_count: 0, unknown_evidence_count: 0, source_counts: {}, node_url: null,
    }]) }} onRetry={vi.fn()} />)

    expect(screen.getByText('当前没有关联的已确认题目')).toBeTruthy()
    expect(screen.getByRole('link', { name: '前往检查题目关联' })).toBeTruthy()
    expect(screen.queryByText(/尚无有效作答记录/)).toBeNull()
  })
})
