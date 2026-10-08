import { useEffect, useRef, useState, type FormEvent } from 'react'
import { CircleHelp, RefreshCw } from 'lucide-react'
import { api, ApiError, getErrorMessage } from '../../api'
import { errorText, isUnauthorized, LoadingState, RetryState } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { ContentSource, MaterialPage, PreparationStage, QueuePreparationInput, WorkflowJob, WorkflowPreparationResponse } from '../../types'
import { requestKeyFor, type RequestKeyState } from './request-keys'
import { PreparationStageCard, type PreparationReview } from './preparation-stage'
import { ImageBoxPicker } from '../content/image-box-picker'

type Remote<T> = { status: 'loading' } | { status: 'loaded'; data: T } | { status: 'error'; message: string }
type StageAction = { id: string; action: 'confirm' | 'cancel' } | null

export function WorkflowPreparationPanel({
  jobId,
  workflowJob,
  pages,
  canWrite,
  hasUnreviewedSourcePackage,
  csrfToken,
  onUnauthorized,
  onJobUpdated,
  onBusyChange,
  onOpenContent,
}: {
  jobId: string
  workflowJob: WorkflowJob
  pages: MaterialPage[]
  canWrite: boolean
  hasUnreviewedSourcePackage: boolean
  csrfToken: string
  onUnauthorized: () => void
  onJobUpdated: (job: WorkflowJob) => void
  onBusyChange: (busy: boolean) => void
  onOpenContent: () => void
}) {
  const [remote, setRemote] = useState<Remote<WorkflowPreparationResponse>>({ status: 'loading' })
  const [refreshCount, setRefreshCount] = useState(0)
  const [action, setAction] = useState<StageAction>(null)
  const [queueBusy, setQueueBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedPageId, setSelectedPageId] = useState(pages[0]?.id || '')
  const [sources, setSources] = useState<ContentSource[]>([])
  const [reason, setReason] = useState('')
  const [sendConfirmed, setSendConfirmed] = useState(false)
  const [redoQuestionId, setRedoQuestionId] = useState<string | null>(null)
  const queueKey = useRef<RequestKeyState>(null)
  const stageKeys = useRef(new Map<string, { current: RequestKeyState }>())

  useEffect(() => {
    if (!pages.some((page) => page.id === selectedPageId)) setSelectedPageId(pages[0]?.id || '')
  }, [pages, selectedPageId])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.workflowPreparation(jobId, controller.signal).then((data) => {
      if (active) setRemote({ status: 'loaded', data })
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [jobId, refreshCount, onUnauthorized])

  const refresh = () => {
    setError('')
    setNotice('')
    setRefreshCount((value) => value + 1)
  }

  const selectedPage = pages.find((page) => page.id === selectedPageId)
  const busy = queueBusy || action !== null
  const configured = remote.status === 'loaded' && remote.data.config.enabled && remote.data.config.outbound_scope === 'selected_regions'
  const stageJobCanPrepare = ['ready', 'needs_review'].includes(workflowJob.state)
  const packageCanPrepare = !hasUnreviewedSourcePackage
  const remainingRequest = remote.status === 'loaded' && remote.data.limits.used_requests < remote.data.limits.max_requests
  const canStartPreparation = canWrite && !busy && remote.status === 'loaded' && configured && stageJobCanPrepare
    && packageCanPrepare && remainingRequest && sources.length > 0 && Boolean(reason.trim()) && sendConfirmed
    && sources.length <= 20

  const updatePreparationData = (update: (data: WorkflowPreparationResponse) => WorkflowPreparationResponse) => {
    setRemote((current) => current.status === 'loaded' ? { status: 'loaded', data: update(current.data) } : current)
  }

  const startPreparation = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canStartPreparation) return
    const payload: Omit<QueuePreparationInput, 'request_key'> = {
      expected: workflowJob.context,
      sources,
      ...(redoQuestionId ? { question_id: redoQuestionId } : {}),
      reason: reason.trim(),
    }
    let requestKey: string
    try {
      requestKey = requestKeyFor(queueKey, JSON.stringify([jobId, workflowJob.context, payload]))
    } catch (cause) {
      setError(getErrorMessage(cause))
      return
    }
    setQueueBusy(true)
    onBusyChange(true)
    setError('')
    setNotice('')
    try {
      const response = await api.queueWorkflowPreparation(jobId, { ...payload, request_key: requestKey }, csrfToken)
      queueKey.current = null
      onJobUpdated(response.job)
      setNotice('准备请求已提交。页面不会自动刷新或重试；点击“刷新准备阶段”查看结果。')
      setSources([])
      setReason('')
      setSendConfirmed(false)
      setRedoQuestionId(null)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(preparationActionError(cause))
    } finally {
      setQueueBusy(false)
      onBusyChange(false)
    }
  }

  const runStageAction = async (stage: PreparationStage, kind: 'confirm' | 'cancel', review?: PreparationReview, cancelReason?: string) => {
    if (!canWrite || busy) return
    const stageKey = stageKeys.current.get(stage.id) || { current: null }
    stageKeys.current.set(stage.id, stageKey)
    let requestKey: string
    const requestPayload = kind === 'confirm' ? review : { reason: cancelReason }
    try {
      requestKey = requestKeyFor(stageKey, JSON.stringify([jobId, stage.id, kind, stage.expected, requestPayload]))
    } catch (cause) {
      setError(getErrorMessage(cause))
      return
    }
    setAction({ id: stage.id, action: kind })
    onBusyChange(true)
    setError('')
    setNotice('')
    try {
      if (kind === 'confirm' && review) {
        const response = await api.confirmWorkflowPreparation(jobId, stage.id, {
          expected: stage.expected,
          request_key: requestKey,
          reason: review.reason,
          checked: true,
          printed_text: review.printed_text,
          original_number: review.original_number,
          sources: stage.sources,
          ...(review.answer ? { answer: review.answer } : {}),
          ...(review.nodes.length ? { nodes: review.nodes } : {}),
        }, csrfToken)
        stageKey.current = null
        updatePreparationData((data) => ({
          ...data,
          job: response.job,
          stages: data.stages.map((item) => item.id === stage.id ? {
            ...item, state: 'applied', can_confirm: false,
            proposal: item.proposal ? {
              ...item.proposal, printed_text: review.printed_text,
              nodes: review.nodes, answer: review.answer || null,
            } : item.proposal,
          } : item),
        }))
        setNotice('本阶段已确认并保存；点击“刷新准备阶段”可核对完整历史。')
        onJobUpdated(response.job)
      } else if (kind === 'cancel' && cancelReason) {
        const response = await api.cancelWorkflowPreparation(jobId, stage.id, {
          expected: stage.expected,
          request_key: requestKey,
          reason: cancelReason,
        }, csrfToken)
        stageKey.current = null
        updatePreparationData((data) => ({
          ...data, job: response.job,
          stages: data.stages.map((item) => item.id === stage.id ? { ...item, state: 'cancelled', can_confirm: false } : item),
        }))
        setNotice('本模型阶段已取消；其他阶段和历史仍保留。')
        onJobUpdated(response.job)
      }
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(preparationActionError(cause))
    } finally {
      setAction(null)
      onBusyChange(false)
    }
  }

  const beginRedo = (stage: PreparationStage) => {
    setRedoQuestionId(stage.question_id)
    setSources(stage.sources.map((source) => ({ page_id: source.page_id, bbox: [...source.bbox] as ContentSource['bbox'] })))
    setSelectedPageId(stage.sources[0]?.page_id || pages[0]?.id || '')
    setReason('')
    setSendConfirmed(false)
    setNotice('已载入该阶段的固定原图来源；确认后会作为一次新的批次请求。')
    setError('')
  }

  const resetToNewQuestion = () => {
    setRedoQuestionId(null)
    setSources([])
    setReason('')
    setSendConfirmed(false)
    setNotice('')
    queueKey.current = null
  }

  const currentSources = selectedPage ? sources.filter((source) => source.page_id === selectedPage.id) : []
  const latestStageByQuestion = new Map<string, string>()
  if (remote.status === 'loaded') {
    for (const stage of remote.data.stages) latestStageByQuestion.set(stage.question_id, stage.id)
  }

  return (
    <Card className='gap-0 border-primary/20 py-0 shadow-sm'>
      <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b py-4'>
        <div>
          <CardTitle className='text-base'>按原图准备题目草稿</CardTitle>
          <CardDescription className='mt-1'>先明确选择原图区域，再发送一次准备请求；模型只返回待核对草稿，不创建作答或评价。</CardDescription>
        </div>
        <Button type='button' variant='outline' size='sm' onClick={refresh} disabled={busy}><RefreshCw className='size-4' aria-hidden='true' />刷新准备阶段</Button>
      </CardHeader>
      <CardContent className='space-y-5 px-5 py-5'>
        {remote.status === 'loading' ? <LoadingState label='正在读取准备配置与阶段历史…' /> : null}
        {remote.status === 'error' ? <RetryState message={remote.message} onRetry={refresh} title='无法读取准备阶段' /> : null}
        {error ? <p role='alert' className='workspace-notice workspace-notice--danger'>{error}</p> : null}
        {notice ? <p role='status' className='workspace-notice workspace-notice--success'>{notice}</p> : null}
        {remote.status === 'loaded' ? (
          <>
            <section className='space-y-2 rounded-lg border bg-muted/15 p-4' aria-label='当前模型配置和准备限额'>
              <div className='flex flex-wrap items-center gap-2'><Badge variant={remote.data.config.enabled ? 'secondary' : 'outline'}>{remote.data.config.enabled ? '模型准备已启用' : '模型准备未启用'}</Badge><span className='text-sm'>外发范围：{scopeLabel(remote.data.config.outbound_scope)}</span></div>
              <p className='text-xs leading-5 text-muted-foreground'>本批累计请求 {remote.data.limits.used_requests} / {remote.data.limits.max_requests} 次 · 最长 {remote.data.limits.max_seconds} 秒{remote.data.config.budget_usd ? ` · 预算上限 ${remote.data.config.budget_usd} USD` : ''}。来源区域由你明确选择。</p>
              {!remote.data.config.enabled || remote.data.config.outbound_scope !== 'selected_regions' ? <div className='workspace-notice workspace-notice--warning flex flex-wrap items-center gap-3'><CircleHelp className='size-4 shrink-0' aria-hidden='true' /><span>当前配置不能准备图像区域；模型关闭时仍可人工核对和保存待补内容。</span><Button type='button' variant='outline' size='sm' onClick={onOpenContent}>打开同页人工核对</Button></div> : null}
              {!packageCanPrepare ? <p className='workspace-notice workspace-notice--warning'>请先完成上方原始来源包的逐项核对，再开始新的准备阶段。</p> : null}
              {!stageJobCanPrepare ? <p className='text-sm text-muted-foreground'>当前任务已进入交付阶段，不能新增模型准备；现有阶段历史仍可查看。</p> : null}
              {!remainingRequest ? <p className='text-sm workspace-inline-state--warning'>本批请求次数已达上限；可以继续查看或核对已有阶段。</p> : null}
            </section>

            {canWrite && configured && stageJobCanPrepare && packageCanPrepare && remainingRequest ? (
              <form className='space-y-4 rounded-lg border border-primary/25 p-4' onSubmit={(event) => void startPreparation(event)}>
                <div className='flex flex-wrap items-start justify-between gap-3'>
                  <div><h3 className='font-semibold'>{redoQuestionId ? '按固定来源重做已有阶段' : '选择新的题目来源区域'}</h3><p className='mt-1 text-sm leading-5 text-muted-foreground'>框选按原图像素记录；发送后不会自动重试，请手动刷新查看结果。</p></div>
                  {redoQuestionId ? <Button type='button' variant='outline' size='sm' disabled={busy} onClick={resetToNewQuestion}>改用新题目区域</Button> : null}
                </div>
                {pages.length && selectedPage ? <>
                  <label className='block max-w-sm text-sm font-medium'>来源页<select className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={selectedPageId} onChange={(event) => setSelectedPageId(event.target.value)} disabled={busy || Boolean(redoQuestionId)}>
                    {pages.map((page) => <option key={page.id} value={page.id}>资料页 {page.position}</option>)}
                  </select></label>
                  <ImageBoxPicker page={selectedPage} boxes={currentSources.map((source, index) => ({ bbox: source.bbox, label: `已选准备来源区域 ${index + 1}` }))} onAdd={(bbox) => setSources((current) => [...current, { page_id: selectedPage.id, bbox }])} disabled={busy || Boolean(redoQuestionId)} addLabel='确认添加准备来源' />
                  {sources.length ? <ul className='space-y-2'>{sources.map((source, index) => {
                    const sourcePage = pages.find((page) => page.id === source.page_id)
                    return <li key={`${source.page_id}:${index}`} className='flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm'><span>资料页 {sourcePage?.position ?? '未知'} · 原图区域 [{source.bbox.join(', ')}] px</span>{!redoQuestionId ? <button type='button' className='text-destructive underline' onClick={() => setSources((current) => current.filter((_, sourceIndex) => sourceIndex !== index))} disabled={busy}>移除准备来源</button> : <span className='text-xs text-muted-foreground'>重做阶段会固定沿用原来源</span>}</li>
                  })}</ul> : <p className='workspace-notice workspace-notice--warning border-dashed'>请至少选定一个原图区域。看不清的题干可以在模型结果或人工核对中保持未知。</p>}
                </> : <p className='rounded-md border border-dashed p-3 text-sm text-muted-foreground'>当前资料没有可选原图页。请在资料中先上传原图。</p>}
                <label className='block text-sm font-medium'>准备原因（必填）<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy} required /></label>
                <label className='workspace-notice workspace-notice--warning flex items-start gap-2 text-sm leading-5'><input type='checkbox' className='mt-1' checked={sendConfirmed} onChange={(event) => setSendConfirmed(event.target.checked)} disabled={busy} />我已对照原图并明确选定这些区域，同意按上方显示的模型外发范围发送本次准备请求。</label>
                <Button type='submit' disabled={!canStartPreparation}>{queueBusy ? '正在提交准备请求…' : '明确发送准备请求'}</Button>
              </form>
            ) : null}

            <section className='space-y-3'>
              <div className='flex flex-wrap items-end justify-between gap-2'><div><h3 className='font-semibold'>准备阶段历史</h3><p className='mt-1 text-sm text-muted-foreground'>每次准备、重做、取消和确认都保留；不会因刷新而删除旧阶段。</p></div><span className='text-xs text-muted-foreground'>{remote.data.stages.length} 个阶段</span></div>
              {remote.data.stages.length ? <div className='space-y-4'>{remote.data.stages.map((stage) => <PreparationStageCard
                key={stage.id}
                stage={stage}
                pages={pages}
                canWrite={canWrite}
                busy={busy}
                isLatest={latestStageByQuestion.get(stage.question_id) === stage.id}
                canRedoAgain={Boolean(configured && stageJobCanPrepare && packageCanPrepare && remainingRequest)}
                onConfirm={(review) => void runStageAction(stage, 'confirm', review)}
                onCancel={(cancelReason) => void runStageAction(stage, 'cancel', undefined, cancelReason)}
                onRedo={() => beginRedo(stage)}
              />)}</div> : <p className='rounded-md border border-dashed p-4 text-sm text-muted-foreground'>还没有准备阶段。模型准备关闭时可使用同页人工核对入口。</p>}
            </section>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function scopeLabel(scope: string | null) {
  return scope === 'selected_regions' ? '仅包含明确选择的图像区域' : scope === 'reviewed_text' ? '仅已核对文本' : '未配置'
}

function preparationActionError(cause: unknown) {
  if (cause instanceof ApiError) {
    const messages: Record<string, string> = {
      model_disabled: '模型未启用；仍可使用同页人工核对入口。',
      model_scope: '当前模型配置不允许发送所选图像区域。',
      source_changed: '资料来源已变化，请刷新任务并建立新任务。',
      stale_context: '准备任务或阶段内容已变化，请刷新后重新核对。',
      batch_call_limit: '本批次已达到请求上限。',
      batch_expired: '本批次已超过有效时限，请建立新任务。',
      budget_exceeded: '本批预算已用尽，未发送本次请求。',
      invalid_state: '任务状态已变化，不能继续这个操作。',
    }
    return messages[cause.code] || getErrorMessage(cause)
  }
  return getErrorMessage(cause)
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
