import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { CalendarClock, CircleHelp, Plus } from 'lucide-react'
import { api } from '../../api'
import { ApiLink, EmptyState, errorText, formatCount, isUnauthorized, LoadingState, RetryState, SOURCE_LABELS, SourceEvidence, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { WorkspaceHeading } from '../../components/workspace-tabs'
import type { Attempt, Assessment, CreateScheduleInput, ReviewSchedule, ScheduleAction, ScheduleActionInput, ScheduleOptionsResponse, SchedulesResponse } from '../../types'
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
  { value: 'today', label: '今天' },
  { value: 'upcoming', label: '近期（7天内）' },
  { value: 'overdue', label: '逾期' },
  { value: 'completed', label: '已完成' },
  { value: 'later', label: '之后' },
  { value: 'unscheduled', label: '日期未记录' },
  { value: 'cancelled', label: '已取消' },
] as const

type ScheduleView = typeof FILTERS[number]['value']

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
  const [filter, setFilter] = useState<ScheduleView>('today')
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

  const { items } = remote.data
  const today = remote.data.scope.as_of || localDateToday()
  const groups = groupSchedules(items, today)
  const visibleItems = groups[filter]
  return (
    <section className='space-y-4' aria-labelledby='schedules-title'>
      <WorkspaceHeading title={<span id='schedules-title'>复测计划</span>} actions={<>
        {canWrite ? <Button type='button' size='sm' onClick={toggleCreateForm}><Plus aria-hidden='true' />{createOpen ? '收起新计划' : '新增复测计划'}</Button> : null}
      </>} />
      <p className='text-sm text-muted-foreground'>
        {remote.data.scope.as_of ? `按服务端日期 ${today}` : `服务端日期未提供，暂按本地日期 ${today}`} 区分计划时间。计划保留逐次变更；完成时必须选择同一题目版本的已保存作答。
      </p>

      {notice ? <p role='status' className='workspace-notice workspace-notice--success'>{notice}</p> : null}
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
        <EmptyState title='还没有复测计划' detail='有真实复测安排后会按日期显示在这里。可从已确认题目创建计划；不会补造安排或学习记录。' icon={CalendarClock} />
      ) : (
        <div className='space-y-3'>
          <div className='flex flex-wrap gap-2' role='group' aria-label='按计划状态筛选'>
            {FILTERS.map(({ value, label }) => <button
              key={value}
              type='button'
              aria-pressed={filter === value}
              className={filter === value ? 'min-h-9 rounded-md border border-primary bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground' : 'min-h-9 rounded-md border bg-background px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground'}
              onClick={() => setFilter(value)}
            >{label} <span className='ml-1 tabular-nums'>{formatCount(groups[value].length)}</span></button>)}
          </div>
          {visibleItems.length === 0 ? (
            <ScheduleEmptyState
              filter={filter}
              counts={{ today: groups.today.length, upcoming: groups.upcoming.length, overdue: groups.overdue.length }}
              onSelect={setFilter}
            />
          ) : null}
            <div hidden={visibleItems.length === 0} className='workspace-table-wrap max-w-full overflow-x-auto'>
              <table className='w-full min-w-[54rem] border-collapse text-sm'>
                <thead><tr className='border-b text-left text-muted-foreground'>
                  <th scope='col' className='px-2 py-2 font-medium'>题目与最近作答</th>
                  <th scope='col' className='px-2 py-2 font-medium'>复测安排</th>
                  <th scope='col' className='px-2 py-2 font-medium'>状态</th>
                  <th scope='col' className='px-2 py-2 font-medium'>操作</th>
                </tr></thead>
                <tbody className='divide-y'>
                  {items.map((item) => <ScheduleRow
                    key={item.id}
                    item={item}
                    visible={visibleItems.includes(item)}
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

function isScheduleOverdue(item: ReviewSchedule) {
  return item.overdue
}

type ScheduleGroups = Record<ScheduleView, ReviewSchedule[]>

function groupSchedules(items: ReviewSchedule[], asOf: string): ScheduleGroups {
  const active = items.filter((item) => item.state === 'planned' || item.state === 'rescheduled')
  const upcomingEnd = addCalendarDays(asOf, 7)
  return {
    today: active.filter((item) => !item.overdue && item.due_date === asOf),
    upcoming: active.filter((item) => !item.overdue && item.due_date > asOf && item.due_date <= upcomingEnd),
    overdue: active.filter((item) => isScheduleOverdue(item) || (Boolean(item.due_date) && item.due_date < asOf)),
    completed: items.filter((item) => item.state === 'completed'),
    later: active.filter((item) => !item.overdue && item.due_date > upcomingEnd),
    unscheduled: active.filter((item) => !item.due_date),
    cancelled: items.filter((item) => item.state === 'cancelled'),
  }
}

function ScheduleEmptyState({
  filter,
  counts,
  onSelect,
}: {
  filter: ScheduleView
  counts: { today: number; upcoming: number; overdue: number }
  onSelect: (filter: ScheduleView) => void
}) {
  const copy: Record<ScheduleView, { title: string; detail: string }> = {
    today: {
      title: '今天没有安排的复测',
      detail: `近期有 ${formatCount(counts.upcoming)} 项计划，逾期有 ${formatCount(counts.overdue)} 项。计划为空不代表没有待办。`,
    },
    upcoming: { title: '近期没有待到期计划', detail: '之后安排的计划和已逾期计划分别查看；这里不会推测新的复测安排。' },
    overdue: { title: '当前没有逾期计划', detail: '按服务端日期与计划日期判断；其他待复测安排可在“今天”或“近期”查看。' },
    completed: { title: '还没有已完成计划', detail: '完成状态只会在计划绑定真实作答后显示。' },
    later: { title: '暂无更晚安排', detail: '超过近期范围的计划会列在这里。' },
    unscheduled: { title: '没有日期未记录的计划', detail: '日期缺失会单独列出，不会猜测到期时间。' },
    cancelled: { title: '没有已取消计划', detail: '取消的计划和有效待复测计划分开显示。' },
  }
  const actions: Array<{ value: ScheduleView; label: string; count: number }> = [
    { value: 'upcoming', label: '查看近期计划', count: counts.upcoming },
    { value: 'overdue', label: '查看逾期计划', count: counts.overdue },
  ]
  return (
    <div className='space-y-3'>
      <EmptyState title={copy[filter].title} detail={copy[filter].detail} icon={CalendarClock} />
      {filter === 'today' && actions.some((action) => action.count > 0) ? (
        <div className='flex flex-wrap justify-center gap-2'>
          {actions.filter((action) => action.count > 0).map((action) => (
            <Button key={action.value} type='button' variant='outline' onClick={() => onSelect(action.value)}>
              {action.label} · {formatCount(action.count)} 项
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function localDateToday() {
  const date = new Date()
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-')
}

function addCalendarDays(value: string, days: number) {
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  date.setDate(date.getDate() + days)
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-')
}

function latestAttemptSummary(attempt: Attempt) {
  const date = attempt.actual_date_state === 'known' && attempt.actual_date
    ? attempt.actual_date
    : '实际日期未知'
  const source = attempt.source_kind_label || SOURCE_LABELS[attempt.source_kind] || '来源未确定'
  const independence = attempt.independence_label || independenceLabel(attempt.independence)
  const prompt = attempt.prompt_status_label || promptLabel(attempt.prompt_status)
  const accepted = attempt.assessments.filter(isCurrentAcceptedAssessment)
  const result = accepted.flatMap((assessment) => assessment.dimensions)
    .slice(0, 2)
    .map((dimension) => `${dimension.dimension_label || '评价项目'}：${dimension.judgment_label || '判断未提供'}`)
  return [date, source, independence, prompt, result.length ? `评价 ${result.join('；')}` : '当前无已接受评价'].join(' · ')
}

function latestAttemptResult(attempt: Attempt) {
  const accepted = attempt.assessments.filter(isCurrentAcceptedAssessment)
  if (accepted.length === 0) return ['当前没有已接受并发布的评价']
  const dimensions = accepted.flatMap((assessment) => assessment.dimensions)
  if (dimensions.length === 0) return ['已接受评价未记录维度']
  return dimensions.map((dimension) => `${dimension.dimension_label || '评价项目未命名'}：${dimension.judgment_label || '判断未提供'} · ${dimension.basis_label || '依据未提供'}`)
}

function isCurrentAcceptedAssessment(assessment: Assessment) {
  return assessment.current && assessment.published && assessment.review_state === 'accepted'
}

function independenceLabel(value: string) {
  const labels: Record<string, string> = {
    confirmed_independent: '人工确认独立',
    not_independent: '确认非独立',
    unknown: '独立性未知',
  }
  return labels[value] || '独立性未确定'
}

function promptLabel(value: string) {
  const labels: Record<string, string> = {
    none_confirmed: '人工确认无提示',
    given: '有提示',
    unknown: '提示情况未知',
  }
  return labels[value] || '提示情况未确定'
}

function recordedAtLabel(value: string) {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function LatestAttemptDetails({ attempt, attemptCount }: { attempt?: Attempt | null; attemptCount?: number }) {
  if (!attempt) return <p className='mt-2 text-sm text-muted-foreground'>暂无最近作答摘要；未记录不等于没有作答。</p>
  return (
    <div className='mt-3 rounded-md border px-3 py-2'>
      <div className='flex flex-wrap items-baseline justify-between gap-2'>
        <h4 className='text-sm font-semibold'>最近真实作答</h4>
        {attemptCount === undefined ? <span className='text-xs text-muted-foreground'>总次数未提供</span> : <span className='text-xs text-muted-foreground'>此稳定题目历版本 {formatCount(attemptCount)} 次有效作答</span>}
      </div>
      <p className='mt-1 text-sm'>{attempt.question_text || '题目未记录'}</p>
      <p className='mt-1 text-xs leading-5 text-muted-foreground'>{latestAttemptSummary(attempt)}</p>
      {attempt.prompts.length ? <p className='mt-1 text-xs text-muted-foreground'>记录的提示：{attempt.prompts.join('、')}</p> : null}
      <ul className='mt-2 space-y-1 text-sm'>
        {latestAttemptResult(attempt).map((result, index) => <li key={`${index}:${result}`}>{result}</li>)}
      </ul>
      <div className='mt-2 flex flex-wrap gap-x-4 gap-y-1'>
        <ApiLink href={attempt.attempt_url}>查看本次作答</ApiLink>
        <ApiLink href={attempt.question_url}>查看题目</ApiLink>
      </div>
      <details className='mt-2 border-t pt-2'>
        <summary className='cursor-pointer text-xs font-medium text-primary'>展开评价维度与原图来源</summary>
        <div className='mt-2 space-y-3'>
          {attempt.assessments.filter(isCurrentAcceptedAssessment).map((assessment) => (
            <section key={assessment.assessment_revision_id} className='space-y-2'>
              {assessment.dimensions.length ? assessment.dimensions.map((dimension) => (
                <div key={dimension.dimension} className='border-l-2 pl-3 text-sm'>
                  <p className='font-medium'>{dimension.dimension_label || '评价项目未命名'} · {dimension.judgment_label || '判断未提供'} · {dimension.basis_label || '依据未提供'}</p>
                  {dimension.rationale ? <p className='mt-1 whitespace-pre-wrap text-muted-foreground'>{dimension.rationale}</p> : null}
                  <SourceEvidence sources={dimension.sources} />
                </div>
              )) : <p className='text-sm text-muted-foreground'>评价未记录维度。</p>}
            </section>
          ))}
          <div>
            <p className='mb-1 text-xs font-semibold text-muted-foreground'>本次作答来源</p>
            <SourceEvidence sources={attempt.sources} />
          </div>
        </div>
      </details>
    </div>
  )
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
  const currentReason = item.history.filter((entry) => entry.action === 'planned' || entry.action === 'rescheduled').at(-1)?.reason || '安排原因未记录'

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
      <td className='max-w-lg px-2 py-2 align-top'>
        <button type='button' className='min-h-8 h-auto whitespace-normal break-words p-0 text-left font-medium hover:underline' aria-expanded={expanded} aria-controls={`schedule-details-${item.id}`} onClick={() => setExpanded((value) => !value)}>
          {item.question_text || '题干未记录'}
        </button>
        <p className='mt-1 text-xs text-muted-foreground'>
          {item.attempt_count === undefined ? '作答次数未提供' : `此题历版本共 ${formatCount(item.attempt_count)} 次有效作答`}
        </p>
        {item.latest_attempt ? <p className='mt-1 text-xs leading-5 text-muted-foreground'>最近记录：{latestAttemptSummary(item.latest_attempt)}{item.latest_attempt.ordering_basis_label ? ` · ${item.latest_attempt.ordering_basis_label}` : ''}</p> : null}
      </td>
      <td className='max-w-sm px-2 py-2 align-top'>
        <p className='font-medium tabular-nums'>{item.due_date || '计划日期未记录'}</p>
        <p className='mt-1'>{item.goal || '复测目标未记录'}</p>
        <p className='mt-1 text-xs leading-5 text-muted-foreground'>安排原因：{currentReason}</p>
      </td>
      <td className='px-2 py-2 align-top'>
        <div className='flex flex-wrap gap-1'>
          <Badge variant={item.state === 'completed' ? 'secondary' : item.state === 'cancelled' ? 'outline' : 'default'}>{STATE_LABELS[item.state] || '未确定状态'}</Badge>
          {isScheduleOverdue(item) ? <Badge variant='outline'>已逾期</Badge> : null}
        </div>
      </td>
      <td className='px-2 py-2 align-top'>
        <div className='flex min-w-28 flex-col items-start gap-1.5'>
          <ApiLink href={item.question_url}>打开题目</ApiLink>
          {!terminal ? <ApiLink href={item.record_attempt_url}>记录复测</ApiLink> : null}
          <Button type='button' variant='outline' size='sm' aria-expanded={expanded} aria-controls={`schedule-details-${item.id}`} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起' : '详情'}</Button>
        </div>
      </td>
    </tr>
    <tr hidden={!visible || !expanded}>
      <td colSpan={4} className='border-b bg-muted/15 px-3 py-4'>
        <div id={`schedule-details-${item.id}`} className='grid gap-5 xl:grid-cols-2'>
          <section className='space-y-3'>
            <div>
              <h3 className='font-semibold'>复测详情</h3>
              <p className='mt-1 text-sm'><span className='font-medium'>提示安排：</span>{item.prompt_plan || '未记录'}</p>
              <LatestAttemptDetails attempt={item.latest_attempt} attemptCount={item.attempt_count} />
              {item.target_stale ? <p className='mt-2 text-sm workspace-inline-state--warning'>计划保留原题目版本；当前题目内容已更新。</p> : null}
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
                  <p className='mt-1 text-xs text-muted-foreground'>记录时间（本地）：{recordedAtLabel(entry.recorded_at)}</p>
                </li>
              ))}
            </ol> : <p className='mt-2 text-sm text-muted-foreground'>暂无可显示的历史记录。</p>}
          </section>
        </div>
        {notice ? <p role='status' className='mt-3 text-sm workspace-inline-state--success'>{notice}</p> : null}
        {error ? <p role='alert' className='mt-3 text-sm workspace-inline-state--danger'>{error}</p> : null}
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
              {item.attempt_choices.map((choice) => <option key={choice.revision_id} value={String(choice.revision_id)}>{choice.label}</option>)}
            </select>
            {item.attempt_choices.length === 0 ? <p className='mt-2 text-sm workspace-inline-state--warning'>暂无可关联的真实作答。先保存作答记录后再完成计划。</p> : null}
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
              {error ? <p role='alert' className='text-sm workspace-inline-state--danger'>{error}</p> : null}
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
