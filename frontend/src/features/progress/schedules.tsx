import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { CalendarClock, CircleHelp, Plus } from 'lucide-react'
import { api } from '../../api'
import { ApiLink, EmptyState, errorText, formatCount, isUnauthorized, LoadingState, RetryState, SOURCE_LABELS, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { WorkspaceHeading } from '../../components/workspace-tabs'
import type { CreateScheduleInput, ReviewSchedule, ScheduleAction, ScheduleActionInput, ScheduleOptionsResponse, SchedulesResponse } from '../../types'
import { requestKeyFor, type RequestKeyState } from '../materials/request-keys'

const STATE_LABELS = {
  planned: '已计划',
  rescheduled: '已改期',
  completed: '已完成',
  cancelled: '已取消',
} as const

const ACTION_LABELS = {
  planned: '创建计划',
  rescheduled: '改期',
  completed: '记录完成',
  cancelled: '取消计划',
} as const

const FILTERS = [
  { value: 'pending', label: '待复测' },
  { value: 'overdue', label: '逾期' },
  { value: 'completed', label: '完成' },
  { value: 'cancelled', label: '取消' },
] as const

export function Schedules({
  remote,
  householdId,
  learnerId,
  csrfToken,
  canWrite,
  onChanged,
  onUnauthorized,
  onRefresh,
  onUnsavedChange,
}: {
  remote: Remote<SchedulesResponse>
  householdId: string
  learnerId: string
  csrfToken: string
  canWrite: boolean
  onChanged: () => void
  onUnauthorized: () => void
  onRefresh: () => void
  onUnsavedChange?: (dirty: boolean) => void
}) {
  const [createOpen, setCreateOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [filter, setFilter] = useState<typeof FILTERS[number]['value']>('pending')
  const dirtyFormsRef = useRef(new Set<string>())
  const reportedDirtyRef = useRef(false)
  const mountedRef = useRef(false)

  useLayoutEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const reportFormDirty = (formId: string, dirty: boolean) => {
    if (!mountedRef.current) return
    if (dirty) dirtyFormsRef.current.add(formId)
    else dirtyFormsRef.current.delete(formId)
    const anyDirty = dirtyFormsRef.current.size > 0
    if (anyDirty === reportedDirtyRef.current) return
    reportedDirtyRef.current = anyDirty
    onUnsavedChange?.(anyDirty)
  }

  const closeCreateForm = () => {
    if (dirtyFormsRef.current.has('create') && !window.confirm('确定放弃尚未保存的新复测计划输入吗？')) return
    reportFormDirty('create', false)
    setCreateOpen(false)
  }

  const toggleCreateForm = () => {
    setNotice('')
    if (createOpen) closeCreateForm()
    else setCreateOpen(true)
  }

  if (remote.status === 'loading') return <LoadingState label='正在读取复测计划…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={onRefresh} />

  const { counts, items } = remote.data
  const filterLabels = Object.fromEntries(FILTERS.map(({ value, label }) => [value, label])) as Record<typeof filter, string>
  return (
    <section className='space-y-4' aria-labelledby='schedules-title'>
      <WorkspaceHeading title={<span id='schedules-title'>复测计划</span>} actions={<>
        {canWrite ? <Button type='button' size='sm' onClick={toggleCreateForm}><Plus aria-hidden='true' />{createOpen ? '收起新计划' : '新增复测计划'}</Button> : null}
      </>} />
      <p className='text-sm text-muted-foreground'>计划保留逐次变更；完成时必须选择一条已保存的真实作答。</p>

      {notice ? <p role='status' className='rounded-md border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900'>{notice}</p> : null}
      {createOpen ? (
        <CreateScheduleForm
          householdId={householdId}
          learnerId={learnerId}
          csrfToken={csrfToken}
          onDirtyChange={(dirty) => reportFormDirty('create', dirty)}
          onSaved={() => {
            if (!mountedRef.current) return
            reportFormDirty('create', false)
            setCreateOpen(false)
            setNotice('新计划已创建。')
            onChanged()
          }}
          onCancel={closeCreateForm}
          onUnauthorized={onUnauthorized}
        />
      ) : null}

      {items.length === 0 ? (
        <EmptyState title='当前没有复测计划' detail='可从已确认题目创建计划；没有计划时不会补造复测记录。' icon={CalendarClock} />
      ) : (
        <div className='space-y-3'>
          <div className='flex flex-wrap gap-2' role='group' aria-label='按计划状态筛选'>
            {FILTERS.map(({ value, label }) => <button
              key={value}
              type='button'
              aria-pressed={filter === value}
              className={filter === value ? 'min-h-9 rounded-md border border-primary bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground' : 'min-h-9 rounded-md border bg-background px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground'}
              onClick={() => setFilter(value)}
            >{label} <span className='ml-1 tabular-nums'>{formatCount(counts[value])}</span></button>)}
          </div>
          <div className='workspace-table-wrap max-w-full overflow-x-auto'>
            <table className='w-full min-w-[44rem] border-collapse text-sm'>
              <thead><tr className='border-b text-left text-muted-foreground'>
                <th scope='col' className='px-2 py-2 font-medium'>题目</th>
                <th scope='col' className='whitespace-nowrap px-2 py-2 font-medium'>复测日期</th>
                <th scope='col' className='px-2 py-2 font-medium'>目标</th>
                <th scope='col' className='px-2 py-2 font-medium'>状态</th>
                <th scope='col' className='relative px-2 py-2 font-medium'><span className='sr-only'>详情</span></th>
              </tr></thead>
              <tbody className='divide-y'>
                {items.every((item) => !matchesFilter(item, filter)) ? <tr><td colSpan={5} className='px-2 py-4 text-muted-foreground'>暂无{filterLabels[filter]}计划。</td></tr> : null}
                  {items.map((item) => <ScheduleRow
                    key={item.id}
                    item={item}
                    visible={matchesFilter(item, filter)}
                    csrfToken={csrfToken}
                    canWrite={canWrite}
                    onDirtyChange={(dirty) => reportFormDirty(`schedule:${item.id}`, dirty)}
                    onSaved={() => {
                      if (!mountedRef.current) return
                      reportFormDirty(`schedule:${item.id}`, false)
                      setNotice('复测计划已保存，历史记录已更新。')
                      onChanged()
                    }}
                    onUnauthorized={onUnauthorized}
                />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}

function matchesFilter(item: ReviewSchedule, filter: typeof FILTERS[number]['value']) {
  switch (filter) {
    case 'pending': return item.state === 'planned' || item.state === 'rescheduled'
    case 'overdue': return isScheduleOverdue(item)
    case 'completed': return item.state === 'completed'
    case 'cancelled': return item.state === 'cancelled'
  }
}

function isScheduleOverdue(item: ReviewSchedule) {
  return item.overdue
}

function ScheduleRow({
  item,
  visible,
  csrfToken,
  canWrite,
  onDirtyChange,
  onSaved,
  onUnauthorized,
}: {
  item: ReviewSchedule
  visible: boolean
  csrfToken: string
  canWrite: boolean
  onDirtyChange: (dirty: boolean) => void
  onSaved: () => void
  onUnauthorized: () => void
}) {
  const [mode, setMode] = useState<ScheduleAction | null>(null)
  const [dueDate, setDueDate] = useState(item.due_date)
  const [goal, setGoal] = useState(item.goal)
  const [promptPlan, setPromptPlan] = useState(item.prompt_plan)
  const [reason, setReason] = useState('')
  const [attemptId, setAttemptId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [expanded, setExpanded] = useState(false)
  const actionKey = useRef<RequestKeyState>(null)
  const dirtyRef = useRef(false)
  const terminal = item.state === 'completed' || item.state === 'cancelled'

  const markDirty = () => {
    if (dirtyRef.current) return
    dirtyRef.current = true
    onDirtyChange(true)
  }

  const clearDirty = () => {
    if (!dirtyRef.current) return
    dirtyRef.current = false
    onDirtyChange(false)
  }

  const openAction = (action: ScheduleAction) => {
    if (dirtyRef.current && !window.confirm('确定放弃这项尚未保存的复测计划操作吗？')) return
    clearDirty()
    setMode(action)
    setReason('')
    setError('')
    setNotice('')
    setAttemptId('')
    setDueDate(item.due_date)
    setGoal(item.goal)
    setPromptPlan(item.prompt_plan)
    actionKey.current = null
  }

  const submitAction = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!mode || busy || !reason.trim()) return
    if (mode === 'rescheduled' && !dueDate) return
    const choice = mode === 'completed'
      ? item.attempt_choices.find((option) => String(option.revision_id) === attemptId)
      : undefined
    if (mode === 'completed' && !choice) return

    const payload: Omit<ScheduleActionInput, 'request_key'> = mode === 'rescheduled'
      ? { action: mode, expected: item.context, reason: reason.trim(), due_date: dueDate, goal: goal.trim(), prompt_plan: promptPlan.trim() }
      : mode === 'completed'
        ? { action: mode, expected: item.context, reason: reason.trim(), attempt_revision_id: choice!.revision_id }
        : { action: mode, expected: item.context, reason: reason.trim() }

    setBusy(true)
    setError('')
    try {
      const key = requestKeyFor(actionKey, JSON.stringify([item.id, payload]))
      await api.scheduleAction(item.id, { ...payload, request_key: key }, csrfToken)
      actionKey.current = null
      clearDirty()
      setMode(null)
      setNotice('已保存')
      onSaved()
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(errorText(cause))
    } finally {
      setBusy(false)
    }
  }

  return <>
    <tr hidden={!visible}>
      <td className='px-2 py-1.5 align-top'>
        <button type='button' className='min-h-8 h-auto whitespace-normal break-words p-0 text-left font-medium hover:underline' aria-expanded={expanded} aria-controls={`schedule-details-${item.id}`} onClick={() => setExpanded((value) => !value)}>
          {item.question_text || '题干未记录'}
        </button>
      </td>
      <td className='whitespace-nowrap px-2 py-1.5 align-top tabular-nums'>{item.due_date || '未安排'}</td>
      <td className='px-2 py-1.5 align-top'>{item.goal || '未记录'}</td>
      <td className='px-2 py-1.5 align-top'>
        <div className='flex flex-wrap gap-1'>
          <Badge variant={item.state === 'completed' ? 'secondary' : item.state === 'cancelled' ? 'outline' : 'default'}>{STATE_LABELS[item.state] || '未确定状态'}</Badge>
          {isScheduleOverdue(item) ? <Badge variant='outline'>已逾期</Badge> : null}
        </div>
      </td>
      <td className='px-2 py-1.5 align-top'>
        <Button type='button' variant='outline' size='sm' aria-expanded={expanded} aria-controls={`schedule-details-${item.id}`} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起' : '详情'}</Button>
      </td>
    </tr>
    <tr hidden={!visible || !expanded}>
      <td colSpan={5} className='border-b bg-muted/15 px-3 py-4'>
        <div id={`schedule-details-${item.id}`} className='grid gap-5 xl:grid-cols-2'>
          <section className='space-y-3'>
            <div>
              <h3 className='font-semibold'>复测详情</h3>
              <p className='mt-1 text-sm'><span className='font-medium'>提示安排：</span>{item.prompt_plan || '未记录'}</p>
              {item.target_stale ? <p className='mt-2 text-sm text-amber-900'>计划保留原题目版本；当前题目内容已更新。</p> : null}
              <ApiLink href={item.detail_url}>查看复测历史</ApiLink>
            </div>
            {canWrite && !terminal ? (
              <div className='flex flex-wrap gap-2'>
                <Button type='button' variant='outline' size='sm' disabled={busy} onClick={() => openAction('rescheduled')}>改期</Button>
                <Button type='button' variant='outline' size='sm' disabled={busy} onClick={() => openAction('completed')}>记录复测完成</Button>
                <Button type='button' variant='ghost' size='sm' disabled={busy} onClick={() => openAction('cancelled')}>取消计划</Button>
              </div>
            ) : null}
          </section>
          <section>
            <h3 className='font-semibold'>计划与完成历史</h3>
            {item.history.length > 0 ? <ol className='mt-2 space-y-3'>
              {item.history.map((entry) => (
                <li key={entry.revision_no} className='border-l-2 border-muted pl-3 text-sm'>
                  <p className='font-medium'>第 {entry.revision_no} 次 · {ACTION_LABELS[entry.action] || '未确定状态'} · 计划日期 {entry.due_date || '未安排'}</p>
                  {entry.action === 'completed' ? <p className='mt-1 text-muted-foreground'>实际作答日期：{entry.actual_date || '未知'}{entry.attempt_revision_id === null ? ' · 未关联作答版本' : ' · 已关联真实作答'}。</p> : null}
                  <p className='mt-1 text-muted-foreground'>原因：{entry.reason || '未记录'}</p>
                  <p className='mt-1 text-xs text-muted-foreground'>记录时间：{entry.recorded_at || '未记录'}</p>
                </li>
              ))}
            </ol> : <p className='mt-2 text-sm text-muted-foreground'>暂无可显示的历史记录。</p>}
          </section>
        </div>
        {notice ? <p role='status' className='mt-3 text-sm text-emerald-800'>{notice}</p> : null}
        {error ? <p role='alert' className='mt-3 text-sm text-destructive'>{error}</p> : null}
        {mode ? <form className='mt-4 space-y-4 border-t pt-4' onSubmit={submitAction}>
          <div>
            <h3 className='font-semibold'>{mode === 'rescheduled' ? '调整复测计划' : mode === 'completed' ? '记录复测完成' : '取消复测计划'}</h3>
            <p className='mt-1 text-sm text-muted-foreground'>填写原因后保存；保存时会按当前计划版本检查是否过期。</p>
          </div>
          {mode === 'rescheduled' ? <div className='grid gap-3 sm:grid-cols-3'>
            <Field label='新的复测日期' type='date' value={dueDate} onChange={(value) => { setDueDate(value); markDirty() }} required disabled={busy} />
            <Field label='复测目标' value={goal} onChange={(value) => { setGoal(value); markDirty() }} disabled={busy} />
            <Field label='提示安排' value={promptPlan} onChange={(value) => { setPromptPlan(value); markDirty() }} disabled={busy} />
          </div> : null}
          {mode === 'completed' ? <div className='max-w-xl'>
            <label className='mb-1 block text-sm font-medium' htmlFor={`attempt-${item.id}`}>选择这次复测对应的真实作答</label>
            <select id={`attempt-${item.id}`} className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={attemptId} onChange={(event) => { setAttemptId(event.target.value); markDirty() }} required disabled={busy}>
              <option value=''>请选择已保存的作答</option>
              {item.attempt_choices.map((choice) => <option key={choice.revision_id} value={String(choice.revision_id)}>{choice.label} · {choice.actual_date || '实际作答日期未知'} · {SOURCE_LABELS[choice.source_kind] || '来源未知'}</option>)}
            </select>
            {item.attempt_choices.length === 0 ? <p className='mt-2 text-sm text-amber-900'>暂无可关联的真实作答。先保存作答记录后再完成计划。</p> : null}
          </div> : null}
          <Field label='本次操作原因' value={reason} onChange={(value) => { setReason(value); markDirty() }} required disabled={busy} />
          <div className='flex flex-wrap gap-2'>
            <Button type='submit' disabled={busy || !reason.trim() || (mode === 'rescheduled' && !dueDate) || (mode === 'completed' && !attemptId)}>
              {busy ? '正在保存…' : mode === 'rescheduled' ? '保存改期' : mode === 'completed' ? '确认关联作答并完成' : '确认取消计划'}
            </Button>
            <Button type='button' variant='outline' disabled={busy} onClick={() => {
              if (dirtyRef.current && !window.confirm('确定放弃这项尚未保存的复测计划操作吗？')) return
              clearDirty()
              setMode(null)
              setError('')
              actionKey.current = null
            }}>返回</Button>
          </div>
        </form> : null}
      </td>
    </tr>
  </>
}

function Field({
  label,
  value,
  onChange,
  required = false,
  type = 'text',
  disabled = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  required?: boolean
  type?: 'text' | 'date'
  disabled?: boolean
}) {
  const id = `schedule-${useId()}`
  return (
    <div>
      <label className='mb-1 block text-sm font-medium' htmlFor={id}>{label}{required ? '（必填）' : ''}</label>
      <input id={id} className='h-10 w-full rounded-md border bg-background px-3 text-sm' type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} disabled={disabled} />
    </div>
  )
}

function CreateScheduleForm({
  householdId,
  learnerId,
  csrfToken,
  onSaved,
  onDirtyChange,
  onCancel,
  onUnauthorized,
}: {
  householdId: string
  learnerId: string
  csrfToken: string
  onSaved: () => void
  onDirtyChange: (dirty: boolean) => void
  onCancel: () => void
  onUnauthorized: () => void
}) {
  const [options, setOptions] = useState<Remote<ScheduleOptionsResponse>>({ status: 'loading' })
  const [optionsRetry, setOptionsRetry] = useState(0)
  const [questionRevisionId, setQuestionRevisionId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [goal, setGoal] = useState('')
  const [promptPlan, setPromptPlan] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const createKey = useRef<RequestKeyState>(null)
  const dirtyRef = useRef(false)
  const mountedRef = useRef(false)

  useLayoutEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const markDirty = () => {
    if (!mountedRef.current || dirtyRef.current) return
    dirtyRef.current = true
    onDirtyChange(true)
  }

  const clearDirty = () => {
    if (!mountedRef.current || !dirtyRef.current) return
    dirtyRef.current = false
    onDirtyChange(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setOptions({ status: 'loading' })
    api.scheduleOptions(learnerId, householdId, controller.signal).then((data) => {
      if (active) setOptions({ status: 'loaded', data })
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setOptions({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, learnerId, optionsRetry, onUnauthorized])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (options.status !== 'loaded' || busy || !questionRevisionId || !dueDate || !goal.trim() || !reason.trim()) return
    const question = options.data.questions.find((item) => String(item.revision_id) === questionRevisionId)
    if (!question) return
    const payload: Omit<CreateScheduleInput, 'request_key'> = {
      question_revision_id: question.revision_id,
      due_date: dueDate,
      goal: goal.trim(),
      prompt_plan: promptPlan.trim(),
      reason: reason.trim(),
      expected: options.data.context,
    }
    setBusy(true)
    setError('')
    try {
      const key = requestKeyFor(createKey, JSON.stringify([householdId, learnerId, payload]))
      await api.createSchedule(learnerId, householdId, { ...payload, request_key: key }, csrfToken)
      if (!mountedRef.current) return
      createKey.current = null
      clearDirty()
      onSaved()
    } catch (cause) {
      if (!mountedRef.current) return
      if (isUnauthorized(cause)) onUnauthorized()
      setError(errorText(cause))
    } finally {
      if (mountedRef.current) setBusy(false)
    }
  }

  return (
    <Card className='gap-0 border-primary/30 py-0 shadow-sm'>
      <CardHeader className='border-b py-4'>
        <CardTitle className='text-base'>新建复测计划</CardTitle>
        <CardDescription>题目和可选版本来自已保存记录；填写计划日期、目标、提示安排和原因。</CardDescription>
      </CardHeader>
      <CardContent className='px-5 py-4'>
        {options.status === 'loading' ? <LoadingState label='正在读取可创建计划的题目…' /> : null}
        {options.status === 'error' ? <RetryState message={options.message} onRetry={() => setOptionsRetry((value) => value + 1)} /> : null}
        {options.status === 'loaded' ? (
          options.data.questions.length === 0 ? (
            <div className='space-y-3'>
              <EmptyState title='没有可创建计划的题目' detail='需要先有可选题目，再从这里建立复测计划。' icon={CircleHelp} />
              <Button type='button' variant='outline' disabled={busy} onClick={() => setOptionsRetry((value) => value + 1)}>重新读取题目</Button>
            </div>
          ) : (
            <form className='space-y-4' onSubmit={submit}>
              <div className='grid gap-3 sm:grid-cols-2'>
                <div className='sm:col-span-2'>
                  <label className='mb-1 block text-sm font-medium' htmlFor='schedule-question'>题目</label>
                  <select id='schedule-question' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={questionRevisionId} onChange={(event) => { setQuestionRevisionId(event.target.value); markDirty() }} required disabled={busy}>
                    <option value=''>请选择已确认题目</option>
                    {options.data.questions.map((question) => <option key={question.revision_id} value={String(question.revision_id)}>{question.label}</option>)}
                  </select>
                </div>
                <Field label='复测日期' type='date' value={dueDate} onChange={(value) => { setDueDate(value); markDirty() }} required disabled={busy} />
                <Field label='复测目标' value={goal} onChange={(value) => { setGoal(value); markDirty() }} required disabled={busy} />
                <Field label='提示安排（可留空）' value={promptPlan} onChange={(value) => { setPromptPlan(value); markDirty() }} disabled={busy} />
                <Field label='创建原因' value={reason} onChange={(value) => { setReason(value); markDirty() }} required disabled={busy} />
              </div>
              {error ? <p role='alert' className='text-sm text-destructive'>{error}</p> : null}
              <div className='flex flex-wrap gap-2'>
                <Button type='submit' disabled={busy || !questionRevisionId || !dueDate || !goal.trim() || !reason.trim()}>{busy ? '正在保存…' : '创建复测计划'}</Button>
                <Button type='button' variant='outline' disabled={busy} onClick={onCancel}>取消</Button>
                <Button type='button' variant='ghost' disabled={busy} onClick={() => { setOptionsRetry((value) => value + 1); setError(''); createKey.current = null }}>重新读取题目</Button>
              </div>
            </form>
          )
        ) : null}
      </CardContent>
    </Card>
  )
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
