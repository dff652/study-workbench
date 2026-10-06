import { useEffect, useState } from 'react'
import { useLearningUpdates } from '../lib/learning-updates'
import { api } from '../api'
import type { ProgressResponse, SchedulesResponse } from '../types'
import { ApiLink, errorText, isUnauthorized, type Remote } from './shared'
import { Button } from './ui/button'

export function LearningTasks({ householdId, learnerId, studentMode = false, onUnauthorized }: {
  householdId: string; learnerId: string; studentMode?: boolean; onUnauthorized: () => void
}) {
  const [plans, setPlans] = useState<Remote<SchedulesResponse>>({ status: 'loading' })
  const [materials, setMaterials] = useState<Remote<ProgressResponse>>({ status: 'loading' })
  const updateVersion = useLearningUpdates(householdId, learnerId)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setPlans({ status: 'loading' }); setMaterials({ status: 'loading' })
    const failed = (error: unknown) => {
      if (isUnauthorized(error)) onUnauthorized()
      return { status: 'error' as const, message: errorText(error) }
    }
    if (learnerId) void api.schedules(learnerId, householdId, controller.signal).then((data) => {
      if (!controller.signal.aborted) setPlans({ status: 'loaded', data })
    }).catch((error: unknown) => { if (!controller.signal.aborted) setPlans(failed(error)) })
    void api.progress(householdId, controller.signal).then((data) => {
      if (!controller.signal.aborted) setMaterials({ status: 'loaded', data })
    }).catch((error: unknown) => { if (!controller.signal.aborted) setMaterials(failed(error)) })
    return () => controller.abort()
  }, [householdId, learnerId, onUnauthorized, retry, updateVersion])
  const nextPlans = plans.status === 'loaded' ? plans.data.items.filter((item) => item.state === 'planned' || item.state === 'rescheduled').sort((a, b) => a.due_date.localeCompare(b.due_date)).slice(0, 3) : []
  const today = plans.status === 'loaded' ? plans.data.scope.as_of || new Date().toLocaleDateString('sv-SE') : new Date().toLocaleDateString('sv-SE')
  const pending = materials.status === 'loaded' ? materials.data.materials.filter((item) => item.pages_unread || item.pages_need_retake || item.questions_pending).slice(0, 2) : []
  return <section aria-labelledby='learning-tasks-title' className='space-y-3 rounded-lg border p-4'>
    <div><h2 id='learning-tasks-title' className='text-lg font-semibold'>接下来做什么</h2><p className='mt-1 text-xs text-muted-foreground'>当前学习者的复测计划与家庭整理待办，不受下方作答日期筛选影响。</p></div>
    <div className={`grid items-start gap-5 ${studentMode ? '' : 'lg:grid-cols-2'}`}>
      <div><h3 className='sr-only'>近期复测</h3>
        {!learnerId ? <p className='text-sm text-muted-foreground'>选择学习者后查看复测计划。</p> : plans.status === 'loading' ? <p role='status' className='text-sm'>正在读取计划…</p> : plans.status === 'error' ? <p role='alert' className='text-sm'>{plans.message}</p> : nextPlans.length ? <ul className='space-y-2'>{nextPlans.map((plan) => <li key={plan.id} className='text-sm'><ApiLink href={plan.detail_url}>{plan.overdue || plan.due_date < today ? '逾期' : plan.due_date === today ? '今天' : '近期'} · {plan.due_date} · {plan.question_text || '查看目标题目'}</ApiLink><p className='mt-1 text-xs text-muted-foreground'>目标：{plan.goal || '未记录'}；安排依据：{plan.history.reduce((latest, entry) => entry.revision_no > latest.revision_no ? entry : latest, plan.history[0])?.reason || '未记录'}</p></li>)}</ul> : <p className='text-sm text-muted-foreground'>暂无待复测计划。已有作答仍可在学习档案回看。</p>}
      </div>
      <details open={!studentMode} className='space-y-2'><summary className='cursor-pointer font-medium'>家长待办 · 继续整理</summary>
        {materials.status === 'loading' ? <p role='status' className='text-sm'>正在读取家庭资料…</p> : materials.status === 'error' ? <p role='alert' className='text-sm'>{materials.message}</p> : pending.length ? <ul className='space-y-2'>{pending.map((item) => <li key={item.id} className='text-sm'><ApiLink href={`/app/?view=materials&household=${encodeURIComponent(householdId)}&material=${encodeURIComponent(item.id)}&tab=content`}>{item.title || '未命名资料'}</ApiLink><p className='mt-1 text-xs text-muted-foreground'>待整理 {item.pages_unread} 页 · 待重拍 {item.pages_need_retake} 页 · 待核对 {item.questions_pending} 道题</p></li>)}</ul> : <p className='text-sm text-muted-foreground'>{materials.data.total ? '已读取的资料没有已登记整理待办；可在处理进度查看全部范围。' : '还没有资料，可从下方整理学习资料开始。'}</p>}
      </details>
    </div>
    {plans.status === 'error' || materials.status === 'error' ? <Button type='button' variant='outline' size='sm' onClick={() => setRetry((value) => value + 1)}>重试待办</Button> : null}
  </section>
}
