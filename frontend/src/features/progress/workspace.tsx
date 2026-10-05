import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../../api'
import { errorText, isUnauthorized, type Remote } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import type { Learner, LearnerProgressResponse, ProgressResponse, SchedulesResponse } from '../../types'
import { LearnerProgress } from './learner-progress'
import { MaterialProgress } from './material-progress'
import { Schedules } from './schedules'

export function ProgressWorkspace({
  householdId,
  learner,
  csrfToken,
  canWrite,
  onUnauthorized,
  initialTab,
  onTabChange,
  onUnsavedChange,
}: {
  householdId: string
  learner: Learner
  csrfToken: string
  canWrite: boolean
  onUnauthorized: () => void
  initialTab?: string
  onTabChange?: (value: string) => void
  onUnsavedChange?: (dirty: boolean) => void
}) {
  const [progress, setProgress] = useState<Remote<ProgressResponse>>({ status: 'loading' })
  const [learnerProgress, setLearnerProgress] = useState<Remote<LearnerProgressResponse>>({ status: 'loading' })
  const [schedules, setSchedules] = useState<Remote<SchedulesResponse>>({ status: 'loading' })
  const [refresh, setRefresh] = useState(0)
  const [tab, setTab] = useState(() => progressTab(initialTab))
  const [scheduleDraftVersion, setScheduleDraftVersion] = useState(0)
  const scheduleDirtyRef = useRef(false)
  const pendingScheduleRefreshRef = useRef(false)
  const mountedRef = useRef(false)

  useLayoutEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => { setTab(progressTab(initialTab)) }, [initialTab])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setProgress({ status: 'loading' })
    api.progress(householdId, controller.signal).then((data) => {
      if (active) setProgress({ status: 'loaded', data })
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setProgress({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, refresh, onUnauthorized])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLearnerProgress({ status: 'loading' })
    api.learnerProgress(learner.id, householdId, controller.signal).then((data) => {
      if (active) setLearnerProgress({ status: 'loaded', data })
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setLearnerProgress({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, learner.id, refresh, onUnauthorized])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setSchedules({ status: 'loading' })
    api.schedules(learner.id, householdId, controller.signal).then((data) => {
      if (active) setSchedules({ status: 'loaded', data })
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setSchedules({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, learner.id, refresh, onUnauthorized])

  const reportScheduleDirty = useCallback((dirty: boolean) => {
    if (!mountedRef.current) return
    scheduleDirtyRef.current = dirty
    onUnsavedChange?.(dirty)
    if (!dirty && pendingScheduleRefreshRef.current) {
      pendingScheduleRefreshRef.current = false
      setRefresh((value) => value + 1)
    }
  }, [onUnsavedChange])

  const refreshAfterScheduleChange = () => {
    if (scheduleDirtyRef.current) {
      pendingScheduleRefreshRef.current = true
      return
    }
    setRefresh((value) => value + 1)
  }

  const refreshAll = () => {
    if (scheduleDirtyRef.current) {
      if (!window.confirm('有尚未保存的复测计划输入。刷新会放弃这些内容，确定继续吗？')) return
      scheduleDirtyRef.current = false
      pendingScheduleRefreshRef.current = false
      onUnsavedChange?.(false)
      setScheduleDraftVersion((value) => value + 1)
    }
    setRefresh((value) => value + 1)
  }
  const selectTab = (value: string) => {
    if (!isProgressTab(value)) return
    setTab(value)
    onTabChange?.(value)
  }

  return (
    <div className='min-w-0 space-y-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <WorkspaceTabs
          id='progress-workspace'
          label='进度模块'
          tabs={[
            { value: 'plans', label: '复测计划' },
            { value: 'evidence', label: '学习证据' },
            { value: 'materials', label: '资料进度' },
          ]}
          value={tab}
          onChange={selectTab}
        />
        <Button type='button' variant='outline' size='sm' onClick={refreshAll}><RefreshCw aria-hidden='true' />刷新全部</Button>
      </div>

      <WorkspacePanel id='progress-workspace' value='plans' active={tab}>
        <Schedules
          key={scheduleDraftVersion}
          remote={schedules}
          householdId={householdId}
          learnerId={learner.id}
          csrfToken={csrfToken}
          canWrite={canWrite}
          onChanged={refreshAfterScheduleChange}
          onUnauthorized={onUnauthorized}
          onRefresh={refreshAll}
          onUnsavedChange={reportScheduleDirty}
        />
      </WorkspacePanel>
      <WorkspacePanel id='progress-workspace' value='evidence' active={tab}>
        <LearnerProgress remote={learnerProgress} onRetry={refreshAll} />
      </WorkspacePanel>
      <WorkspacePanel id='progress-workspace' value='materials' active={tab}>
        <MaterialProgress remote={progress} onRetry={refreshAll} />
      </WorkspacePanel>
    </div>
  )
}

const PROGRESS_TABS = ['plans', 'evidence', 'materials'] as const

function isProgressTab(value: string): value is typeof PROGRESS_TABS[number] {
  return (PROGRESS_TABS as readonly string[]).includes(value)
}

function progressTab(value: string | undefined) {
  return value && isProgressTab(value) ? value : 'plans'
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
