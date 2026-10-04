import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../../api'
import { errorText, isUnauthorized, type Remote } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Card, CardContent } from '../../components/ui/card'
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
}: {
  householdId: string
  learner: Learner
  csrfToken: string
  canWrite: boolean
  onUnauthorized: () => void
}) {
  const [progress, setProgress] = useState<Remote<ProgressResponse>>({ status: 'loading' })
  const [learnerProgress, setLearnerProgress] = useState<Remote<LearnerProgressResponse>>({ status: 'loading' })
  const [schedules, setSchedules] = useState<Remote<SchedulesResponse>>({ status: 'loading' })
  const [refresh, setRefresh] = useState(0)

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

  const refreshAll = () => setRefresh((value) => value + 1)

  return (
    <div className='space-y-8'>
      <Card className='gap-0 py-0 shadow-sm'>
        <CardContent className='flex flex-wrap items-center justify-between gap-3 px-5 py-4'>
          <div>
            <p className='text-sm font-semibold'>当前学习者：{learner.display_name}</p>
            <p className='mt-1 text-xs text-muted-foreground'>页面数据按所选家庭和学习者读取，切换范围会取消旧请求。</p>
          </div>
          <Button type='button' variant='outline' size='sm' onClick={refreshAll}><RefreshCw aria-hidden='true' />刷新全部</Button>
        </CardContent>
      </Card>

      <MaterialProgress remote={progress} onRetry={refreshAll} />
      <LearnerProgress remote={learnerProgress} onRetry={refreshAll} />
      <Schedules
        remote={schedules}
        householdId={householdId}
        learnerId={learner.id}
        csrfToken={csrfToken}
        canWrite={canWrite}
        onChanged={refreshAll}
        onUnauthorized={onUnauthorized}
        onRefresh={refreshAll}
      />
    </div>
  )
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
