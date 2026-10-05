import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import type { Filters, Learner, OverviewResponse, AttemptResponse } from '../../types'
import { INITIAL_FILTERS, type Remote } from '../../components/shared'
import { FilterBar } from './filter-bar'
import { Overview } from './overview'
import { Attempts } from './attempts'
import { Disclosure } from '../../components/disclosure'

export type EvidencePage = 'overview' | 'attempts'

export function EvidenceWorkspace({
  householdId,
  learner,
  activePage,
  onUnauthorized,
}: {
  householdId: string
  learner: Learner
  activePage: EvidencePage
  onUnauthorized: () => void
}) {
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS)
  const [page, setPage] = useState(1)
  const [overview, setOverview] = useState<Remote<OverviewResponse>>({ status: 'loading' })
  const [attempts, setAttempts] = useState<Remote<AttemptResponse>>({ status: 'loading' })
  const [overviewRetry, setOverviewRetry] = useState(0)
  const [attemptsRetry, setAttemptsRetry] = useState(0)

  useEffect(() => {
    if (activePage !== 'overview') return
    const controller = new AbortController()
    let active = true
    setOverview({ status: 'loading' })
    api.overview(learner.id, householdId, filters, controller.signal).then((data) => {
      if (active) setOverview({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      setOverview({ status: 'error', message: messageFor(error) })
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [activePage, householdId, learner.id, filters, overviewRetry, onUnauthorized])

  useEffect(() => {
    if (activePage !== 'attempts') return
    const controller = new AbortController()
    let active = true
    setAttempts({ status: 'loading' })
    api.attempts(learner.id, householdId, filters, page, controller.signal).then((data) => {
      if (active) setAttempts({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      setAttempts({ status: 'error', message: messageFor(error) })
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [activePage, householdId, learner.id, filters, page, attemptsRetry, onUnauthorized])

  const updateFilters = (next: Filters) => {
    setFilters(next)
    setPage(1)
    setOverview({ status: 'loading' })
    setAttempts({ status: 'loading' })
  }

  if (activePage === 'overview') {
    return (
      <div className='space-y-6'>
        <Disclosure title='查看学习记录与待核对项' description='需要回看时，展开记录概要，再查看具体证据。'>
          <div className='space-y-5'><Disclosure title='筛选要看的记录' description='按实际作答日期和来源缩小范围。'><FilterBar filters={filters} onChange={updateFilters} /></Disclosure>
            <Overview remote={overview} onRetry={() => setOverviewRetry((count) => count + 1)} />
          </div>
        </Disclosure>
      </div>
    )
  }

  return (
    <div className='space-y-6'>
      <Disclosure title='筛选作答记录' description='按实际作答日期和来源查找。'><FilterBar filters={filters} onChange={updateFilters} /></Disclosure>
      <Attempts
        remote={attempts}
        page={page}
        onRetry={() => setAttemptsRetry((count) => count + 1)}
        onPageChange={(nextPage) => {
          setPage(nextPage)
          setAttempts({ status: 'loading' })
        }}
      />
    </div>
  )
}

function messageFor(error: unknown) {
  if (error instanceof Error) return error.message
  return '连接暂时不可用，请重试。'
}
