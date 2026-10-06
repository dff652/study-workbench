import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { LearningTasks } from './learning-tasks'
import { notifyLearningUpdate } from '../lib/learning-updates'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('discards a previous learner response and refreshes only acknowledged matching scope', async () => {
  let first!: (response: Response) => void
  const fetcher = vi.fn((input: RequestInfo | URL) => {
    const path = new URL(String(input), window.location.origin).pathname
    if (path.includes('learner-a/schedules')) return new Promise<Response>((resolve) => { first = resolve })
    if (path.includes('/schedules/')) return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', scope: { as_of: '2026-10-07' }, items: [] }))
    return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', materials: [], total: 0 }))
  })
  vi.stubGlobal('fetch', fetcher)
  const unauthorized = vi.fn()
  const view = render(<LearningTasks householdId='home-a' learnerId='learner-a' onUnauthorized={unauthorized} />)
  view.rerender(<LearningTasks householdId='home-a' learnerId='learner-b' onUnauthorized={unauthorized} />)
  await screen.findByText('暂无待复测计划。已有作答仍可在学习档案回看。')
  await act(async () => first(Response.json({ schema_version: 'swb.api.v1', scope: { as_of: '2026-10-07' }, items: [{ id: 1, state: 'planned', due_date: '2026-10-07', question_text: '旧学习者私有任务', goal: '', history: [], detail_url: '/study/schedule/1/' }] })))
  expect(screen.queryByText(/旧学习者私有任务/)).toBeNull()
  expect(fetcher).toHaveBeenCalledTimes(4)
  await act(async () => notifyLearningUpdate({ householdId: 'home-b', learnerId: 'learner-b' }))
  await act(async () => notifyLearningUpdate({ householdId: 'home-a', learnerId: 'learner-a' }))
  expect(fetcher).toHaveBeenCalledTimes(4)
  await act(async () => notifyLearningUpdate({ householdId: 'home-a', learnerId: 'learner-b' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(6))
})
