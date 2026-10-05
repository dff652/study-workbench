import { useEffect, useState } from 'react'
import { api } from '../../api'
import { errorText, isUnauthorized, type Remote } from '../../components/shared'
import { Button } from '../../components/ui/button'
import type { ProgressResponse } from '../../types'
import { MaterialProgress } from '../progress/material-progress'

/** Household processing is independent of the selected learner. */
export function MaterialProcessing({ householdId, onUnauthorized, onReturn }: {
  householdId: string; onUnauthorized: () => void; onReturn: () => void
}) {
  const [remote, setRemote] = useState<Remote<ProgressResponse>>({ status: 'loading' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setRemote({ status: 'loading' })
    api.progress(householdId, controller.signal).then((data) => {
      if (!controller.signal.aborted) setRemote({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      if (isUnauthorized(error)) onUnauthorized()
      setRemote({ status: 'error', message: errorText(error) })
    })
    return () => controller.abort()
  }, [householdId, retry, onUnauthorized])
  return <div className='space-y-5'>
    <div className='flex flex-wrap items-center justify-between gap-3'><p className='text-sm text-muted-foreground'>当前家庭的资料处理情况，分别统计页面、题目与整理任务。</p><Button type='button' variant='outline' onClick={onReturn}>返回资料整理</Button></div>
    <MaterialProgress remote={remote} onRetry={() => setRetry((value) => value + 1)} />
  </div>
}
