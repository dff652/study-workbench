import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import type { Filters, Learner, OverviewResponse, AttemptResponse } from '../../types'
import { errorText, INITIAL_FILTERS, type Remote } from '../../components/shared'
import { WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import { FilterBar } from './filter-bar'
import { Overview } from './overview'
import { Attempts } from './attempts'

export type EvidencePage = 'overview' | 'attempts'

export function EvidenceWorkspace({
  householdId,
  learner,
  activePage,
  initialTab,
  initialFilters = INITIAL_FILTERS,
  onTabChange,
  onFiltersChange,
  onUnauthorized,
}: {
  householdId: string
  learner: Learner
  activePage: EvidencePage
  initialTab?: string
  initialFilters?: Filters
  onTabChange?: (value: string) => void
  onFiltersChange?: (filters: Filters) => void
  onUnauthorized: () => void
}) {
  const [tab, setTab] = useState<EvidencePage>(() => normalizePage(initialTab, activePage))
  const [filters, setFilters] = useState<Filters>(() => ({ ...initialFilters }))
  const [page, setPage] = useState(1)
  const [overview, setOverview] = useState<Remote<OverviewResponse>>({ status: 'loading' })
  const [attempts, setAttempts] = useState<Remote<AttemptResponse>>({ status: 'loading' })
  const [overviewRetry, setOverviewRetry] = useState(0)
  const [attemptsRetry, setAttemptsRetry] = useState(0)

  useEffect(() => {
    setTab(normalizePage(initialTab, activePage))
  }, [activePage, initialTab])

  useEffect(() => {
    const next = normalizeFilters(initialFilters)
    setFilters((current) => filtersEqual(current, next) ? current : next)
    setPage(1)
  }, [initialFilters.dateFrom, initialFilters.dateTo, initialFilters.sourceKind])

  useEffect(() => {
    if (tab !== 'overview') return
    const controller = new AbortController()
    let active = true
    setOverview({ status: 'loading' })
    api.overview(learner.id, householdId, filters, controller.signal).then((data) => {
      if (active) setOverview({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      setOverview({ status: 'error', message: errorText(error) })
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [tab, householdId, learner.id, filters, overviewRetry, onUnauthorized])

  useEffect(() => {
    if (tab !== 'attempts') return
    const controller = new AbortController()
    let active = true
    setAttempts({ status: 'loading' })
    api.attempts(learner.id, householdId, filters, page, controller.signal).then((data) => {
      if (active) setAttempts({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      setAttempts({ status: 'error', message: errorText(error) })
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [tab, householdId, learner.id, filters, page, attemptsRetry, onUnauthorized])

  const updateFilters = (next: Filters) => {
    const normalized = normalizeFilters(next)
    setFilters(normalized)
    setPage(1)
    setOverview({ status: 'loading' })
    setAttempts({ status: 'loading' })
    onFiltersChange?.(normalized)
  }

  const clearFilters = () => updateFilters(INITIAL_FILTERS)

  return (
    <div className='space-y-5'>
      <WorkspaceTabs
        id='evidence'
        label='学习档案视图'
        tabs={[{ value: 'overview', label: '学习概况' }, { value: 'attempts', label: '作答记录' }]}
        value={tab}
        onChange={(value) => {
          if (value !== 'overview' && value !== 'attempts') return
          setTab(value)
          onTabChange?.(value)
        }}
      />
      <details open={Boolean(filters.dateFrom || filters.dateTo || filters.sourceKind)} className='rounded-md border p-3'><summary className='cursor-pointer text-sm font-medium'>筛选作答分析</summary><div className='mt-3'><FilterBar filters={filters} onChange={updateFilters} /></div></details>
      <WorkspacePanel id='evidence' value='overview' active={tab}>
        <div className='space-y-4'>
          <div>
            <h2 className='text-lg font-semibold'>学习概况</h2>
            <p className='mt-1 text-sm text-muted-foreground'>按当前筛选查看真实作答和待核对证据。</p>
          </div>
          <Overview
            remote={overview}
            learnerName={learner.display_name}
            filters={filters}
            onClearFilters={clearFilters}
            onRetry={() => setOverviewRetry((count) => count + 1)}
          />
        </div>
      </WorkspacePanel>
      <WorkspacePanel id='evidence' value='attempts' active={tab}>
        <Attempts
          remote={attempts}
          page={page}
          filters={filters}
          recordAttemptUrl={`${learner.profile_url.replace(/\/$/, '')}/attempt/new/`}
          onClearFilters={clearFilters}
          onRetry={() => setAttemptsRetry((count) => count + 1)}
          onPageChange={(nextPage) => {
            setPage(nextPage)
            setAttempts({ status: 'loading' })
          }}
        />
      </WorkspacePanel>
    </div>
  )
}

function normalizeFilters(filters: Filters): Filters {
  return {
    dateFrom: filters.dateFrom || '',
    dateTo: filters.dateTo || '',
    sourceKind: filters.sourceKind || '',
  }
}

function filtersEqual(left: Filters, right: Filters) {
  return left.dateFrom === right.dateFrom
    && left.dateTo === right.dateTo
    && left.sourceKind === right.sourceKind
}

function normalizePage(value: string | undefined, fallback: EvidencePage): EvidencePage {
  return value === 'overview' || value === 'attempts' ? value : fallback
}
