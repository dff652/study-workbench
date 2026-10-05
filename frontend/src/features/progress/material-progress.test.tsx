import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProgressResponse } from '../../types'
import { MaterialProgress } from './material-progress'

const data: ProgressResponse = {
  schema_version: 'swb.api.v1',
  scope: { household_id: 'family-1', metric_version: 'progress.v1', as_of: '2026-10-06' },
  counts: {
    material_count: 2, page_count: 8, pages_complete: 3, pages_unread: 4, pages_need_retake: 1,
    questions_confirmed: 5, questions_pending: 2, open_workflows: 1, completed_workflows: 3,
  },
  materials: [{
    id: 'material-1', title: '分数练习', page_count: 4, pages_complete: 2, pages_unread: 1,
    pages_need_retake: 1, questions_confirmed: 3, questions_pending: 1, material_url: '/materials/1/',
  }],
  total: 2,
}

describe('MaterialProgress', () => {
  afterEach(cleanup)

  it('keeps all nine actual counts in compact groups with explicit units and no invented rates', () => {
    render(<MaterialProgress remote={{ status: 'loaded', data }} onRetry={vi.fn()} />)

    expect(screen.getByText('资料与页面')).toBeTruthy()
    expect(screen.getByText('题目')).toBeTruthy()
    expect(screen.getByText('整理任务')).toBeTruthy()
    expect(screen.getByText('待重拍')).toBeTruthy()
    expect(screen.getByText('已确认')).toBeTruthy()
    expect(screen.getByText('进行中')).toBeTruthy()
    const metricText = (value: string) => (_content: string, element: Element | null) => element?.textContent?.trim() === value
    expect(screen.getByText(metricText('8 页'))).toBeTruthy()
    expect(screen.getByText(metricText('5 道'))).toBeTruthy()
    expect(screen.getByText(metricText('3 项'))).toBeTruthy()
    expect(screen.getByRole('link', { name: '分数练习' }).getAttribute('href')).toBe('/materials/1/')
    expect(screen.queryByText(/百分比|完成率|进度条/)).toBeNull()
  })
})
