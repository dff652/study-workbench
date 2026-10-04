import { useEffect, useRef, useState } from 'react'
import { AlertCircle, ArrowDownToLine, CheckCheck, CircleCheck, RefreshCw } from 'lucide-react'
import { api, ApiError, getErrorMessage } from '../../api'
import { ApiLink, isUnauthorized, LoadingState, RetryState, sameOriginHref } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { MaterialPage, Readiness, SkillImportRecord, WorkflowDetailResponse, WorkflowJob } from '../../types'
import { requestKeyFor, type RequestKeyState } from './request-keys'
import { localDateTime, workflowActionLabel, workflowStateLabel } from './workflow-labels'
import { WorkflowPreparationPanel } from './preparation-panel'
import { ImageBoxPicker } from '../content/image-box-picker'
import { FormulaReview } from '../../components/formula-preview'

const RECORD_LABELS: Record<SkillImportRecord['kind'], string> = {
  question: '题目',
  knowledge: '知识条目',
  method: '方法',
  question_type: '题型',
  answer: '家长答案',
  link: '双向关联',
  observation: '原图笔迹观察',
  diagram: '教学图示',
}

const FIELD_LABELS: Record<string, string> = {
  printed_text: '题干', original_number: '原题号', display_markup: '展示格式', image_print_confirmed: '图片打印已确认',
  definition: '定义', conditions: '适用条件', common_errors: '常见错误', name: '名称', steps: '步骤', notes: '说明',
  structural_features: '结构特征', body: '答案内容', basis: '答案依据', formulas: '公式', role: '关系类型',
  legibility: '辨识情况',
  placement: '放置位置', png_asset: '教学图预览', vector_asset: '矢量图文件', alt: '图示说明',
  width_points: '排版宽度（pt）', min_label_points: '最小标签字号（pt）', independent_safe: '题面无提示确认',
}

const ROLE_LABELS: Record<string, string> = {
  applies: '适用知识', primary: '主要方法', auxiliary: '辅助方法', belongs: '所属题型',
}

export function WorkflowPanel({
  jobId,
  csrfToken,
  canWrite,
  pages,
  onUnauthorized,
  onJobUpdated,
  onBusyChange,
  onOpenContent,
}: {
  jobId: string
  csrfToken: string
  canWrite: boolean
  pages: MaterialPage[]
  onUnauthorized: () => void
  onJobUpdated: (job: WorkflowJob, readiness?: Readiness) => void
  onBusyChange: (busy: boolean) => void
  onOpenContent: () => void
}) {
  const [remote, setRemote] = useState<{ status: 'loading' } | { status: 'loaded'; data: WorkflowDetailResponse } | { status: 'error'; message: string }>({ status: 'loading' })
  const [refreshCount, setRefreshCount] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reviewReason, setReviewReason] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [outputReason, setOutputReason] = useState('')
  const [checks, setChecks] = useState({ pdf: false, docx: false, purposes: false })
  const requestKeyRef = useRef<RequestKeyState>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.workflow(jobId, controller.signal).then((data) => {
      if (!active) return
      setRemote({ status: 'loaded', data })
      onJobUpdated(data.job, data.readiness)
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [jobId, refreshCount, onJobUpdated, onUnauthorized])

  const refresh = () => {
    setError('')
    setRefreshCount((count) => count + 1)
  }

  const runAction = async (action: string, reason?: string, outputChecks?: typeof checks) => {
    if (remote.status !== 'loaded' || busy) return
    const job = remote.data.job
    const signature = JSON.stringify({ job: job.id, context: job.context, action, reason: reason || '', checks: outputChecks || null })
    let key: string
    try {
      key = requestKeyFor(requestKeyRef, signature)
    } catch (cause) {
      setError(getErrorMessage(cause))
      return
    }
    setBusy(true)
    onBusyChange(true)
    setError('')
    try {
      const response = await api.workflowAction(jobId, {
        action,
        expected: job.context,
        request_key: key,
        ...(reason ? { reason } : {}),
        ...(outputChecks ? { checks: outputChecks } : {}),
      }, csrfToken)
      requestKeyRef.current = null
      onJobUpdated(response.job)
      setRefreshCount((count) => count + 1)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(`${cause instanceof ApiError && cause.status === 409 ? '任务内容已变化。请刷新并重新核对。' : ''}${cause instanceof ApiError && cause.status === 409 ? ' ' : ''}${getErrorMessage(cause)}`)
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  if (remote.status === 'loading') return <LoadingState label='正在读取任务阶段、内容与历史…' />
  if (remote.status === 'error') return <RetryState message={remote.message} onRetry={refresh} title='无法读取资料任务' />
  const { job, records, sources, links, events } = remote.data
  const sourcePages = new Map(sources.map((source) => [source.id, pages.find((page) => page.id === source.page_id)]))

  return (
    <div className='space-y-5'>
      <Card>
        <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b pb-4'>
          <div>
            <CardTitle className='flex items-center gap-2 text-base'>资料整理任务 <Badge variant={job.state === 'complete' ? 'secondary' : 'outline'}>{workflowStateLabel(job.state)}</Badge></CardTitle>
            <CardDescription className='mt-1'>最近更新：{localDateTime(job.updated_at)} · {job.record_count} 项结构化记录</CardDescription>
          </div>
          <Button type='button' variant='outline' size='sm' onClick={refresh} disabled={busy}><RefreshCw className='size-4' aria-hidden='true' />刷新任务</Button>
        </CardHeader>
        <CardContent className='space-y-4 pt-4'>
          {job.error_code ? <p className='flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-950'><AlertCircle className='size-4 shrink-0' aria-hidden='true' />{workflowErrorMessage(job.error_code)}</p> : null}
          {job.state === 'queued' || job.state === 'running' ? <p role='status' className='rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-950'>任务{job.state === 'queued' ? '正在等待执行' : '正在处理中'}；此页面不会自动刷新，可点击“刷新任务”查看最新状态。</p> : null}
          {error ? <p role='alert' className='rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950'>{error}</p> : null}
          <div className='flex flex-wrap gap-x-5 gap-y-2 text-sm'>
            <ApiLink href={links.material_url}>旧版资料页</ApiLink>
            <ApiLink href={links.prepare_url}>五册准备页</ApiLink>
            <ApiLink href={links.ai_url}>AI 辅助页面</ApiLink>
            {links.preview_url ? <ApiLink href={links.preview_url}>查看五册检查版</ApiLink> : null}
            {links.download_url ? <ApiLink href={links.download_url}>下载完整五册 ZIP</ApiLink> : null}
          </div>
          {!canWrite ? <p className='text-sm text-muted-foreground'>当前成员只读；确认和处理由家庭所有者或审核成员操作。</p> : null}
          <fieldset disabled={!canWrite} className='space-y-4'>
          {job.state === 'needs_review' ? (
            <section className='space-y-4 rounded-lg border border-amber-300/70 bg-amber-50/40 p-4'>
              <div>
                <h3 className='font-semibold'>逐项核对本任务的全部内容</h3>
                <p className='mt-1 text-sm leading-6 text-muted-foreground'>确认会一次保存并确认整包记录。请检查题目、知识、方法、题型、答案、关联和原图观察；确认原因会写入审计记录。</p>
              </div>
              <RecordReview records={records} sourcePages={sourcePages} assets={remote.data.assets || {}} />
              <label className='flex items-start gap-2 text-sm leading-5'><input className='mt-1' type='checkbox' checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />我已查看并核对上方列出的全部记录类型。</label>
              <label className='block text-sm font-medium'>确认原因
                <textarea className='mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2 font-normal' value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} placeholder='说明本次整包确认的依据' />
              </label>
              <Button type='button' onClick={() => void runAction('confirm', reviewReason.trim())} disabled={busy || !reviewed || reviewReason.trim().length === 0}><CheckCheck className='size-4' aria-hidden='true' />确认整包内容</Button>
            </section>
          ) : null}
          {job.state === 'ready' ? <div className='flex flex-wrap items-center gap-3 rounded-lg border bg-muted/20 p-4'><p className='mr-auto text-sm'>内容已确认，可以明确加入处理队列。</p><Button type='button' onClick={() => void runAction('queue')} disabled={busy}>加入处理队列</Button></div> : null}
          {job.state === 'output_check' ? (
            <section className='space-y-4 rounded-lg border border-primary/30 bg-primary/[0.03] p-4'>
              <div><h3 className='font-semibold'>输出检查</h3><p className='mt-1 text-sm text-muted-foreground'>打开五册检查版，并逐项确认可读性与用途覆盖，再完成任务。</p></div>
              {links.preview_url ? <ApiLink href={links.preview_url}>打开五册检查版</ApiLink> : <p className='text-sm text-muted-foreground'>服务尚未提供检查版链接。</p>}
              <fieldset className='grid gap-2 sm:grid-cols-3'>
                <legend className='mb-2 text-sm font-medium'>检查项目（必须全部通过）</legend>
                <CheckField label='PDF 可以阅读' checked={checks.pdf} onChange={(checked) => setChecks((value) => ({ ...value, pdf: checked }))} />
                <CheckField label='Word 文档可以阅读' checked={checks.docx} onChange={(checked) => setChecks((value) => ({ ...value, docx: checked }))} />
                <CheckField label='五册用途均正确' checked={checks.purposes} onChange={(checked) => setChecks((value) => ({ ...value, purposes: checked }))} />
              </fieldset>
              <label className='block text-sm font-medium'>输出检查原因
                <textarea className='mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2 font-normal' value={outputReason} onChange={(event) => setOutputReason(event.target.value)} placeholder='记录检查结果和依据' />
              </label>
              <Button type='button' onClick={() => void runAction('check_output', outputReason.trim(), checks)} disabled={busy || !checks.pdf || !checks.docx || !checks.purposes || outputReason.trim().length === 0}><CircleCheck className='size-4' aria-hidden='true' />确认输出检查</Button>
            </section>
          ) : null}
          {job.state === 'complete' ? <div className='flex flex-wrap items-center gap-3 rounded-lg bg-emerald-50 p-4 text-emerald-950'><CircleCheck className='size-5' aria-hidden='true' /><p className='mr-auto font-medium'>五册输出检查已完成。</p>{links.download_url ? <Button asChild><a href={links.download_url}><ArrowDownToLine className='size-4' aria-hidden='true' />下载完整五册 ZIP</a></Button> : null}</div> : null}
          {job.state === 'failed' ? <Button type='button' variant='outline' onClick={() => void runAction('resume')} disabled={busy}>恢复处理</Button> : null}
          {!['complete', 'failed', 'cancelled'].includes(job.state) ? <Button type='button' variant='ghost' size='sm' className='text-destructive' onClick={() => void runAction('cancel')} disabled={busy}>取消任务</Button> : null}
          </fieldset>
        </CardContent>
      </Card>

      <WorkflowPreparationPanel
        jobId={jobId}
        workflowJob={job}
        pages={pages}
        canWrite={canWrite}
        hasUnreviewedSourcePackage={job.state === 'needs_review' && records.length > 0}
        csrfToken={csrfToken}
        onUnauthorized={onUnauthorized}
        onJobUpdated={(updatedJob) => {
          onJobUpdated(updatedJob)
          setRefreshCount((count) => count + 1)
        }}
        onBusyChange={onBusyChange}
        onOpenContent={onOpenContent}
      />

      <Card>
        <CardHeader className='border-b pb-4'><CardTitle className='text-base'>任务事件</CardTitle><CardDescription>保留任务的阶段变化和核对原因。</CardDescription></CardHeader>
        <CardContent className='pt-4'>
          {events.length === 0 ? <p className='text-sm text-muted-foreground'>暂无任务事件。</p> : <ol className='space-y-3'>{events.map((event) => (
            <li key={event.version} className='border-l-2 border-primary/30 pl-4'>
              <p className='font-medium'>{workflowActionLabel(event.action)}</p>
              <p className='mt-0.5 text-xs text-muted-foreground'>{localDateTime(event.created_at)} · 第 {event.version} 次更新</p>
              {typeof event.details.reason === 'string' && event.details.reason ? <p className='mt-2 whitespace-pre-wrap text-sm'>{event.details.reason}</p> : null}
            </li>
          ))}</ol>}
        </CardContent>
      </Card>
    </div>
  )
}

function RecordReview({ records, sourcePages, assets }: {
  records: SkillImportRecord[]
  sourcePages: Map<string, MaterialPage | undefined>
  assets: NonNullable<WorkflowDetailResponse['assets']>
}) {
  const labels = new Map(records.map((record, index) => [record.id, `${RECORD_LABELS[record.kind]} ${index + 1}`]))
  if (records.length === 0) return <p className='rounded-md border border-dashed bg-background p-4 text-sm text-muted-foreground'>此任务没有结构化记录；任务只会整理已有的已确认资料。</p>
  return <ol className='max-h-[40rem] space-y-3 overflow-y-auto pr-1'>{records.map((record, index) => (
    <li key={`${record.kind}-${index}`} className='rounded-lg border bg-background p-4'>
      <div className='flex flex-wrap items-center gap-2'><Badge variant='outline'>{RECORD_LABELS[record.kind]}</Badge><span className='text-sm font-semibold'>第 {index + 1} 项</span></div>
      <dl className='mt-3 grid gap-2 sm:grid-cols-[9rem_minmax(0,1fr)]'>
        {Object.entries(record.data).map(([field, value]) => {
          if (field === 'sources' || field === 'source') return <div key={field} className='contents'><dt className='text-sm text-muted-foreground'>{record.kind === 'diagram' ? '教学图来源' : '原图来源'}</dt><dd><SourceEvidence value={value} sourcePages={sourcePages} /></dd></div>
          if (field === 'question' || field === 'node') return <div key={field} className='contents'><dt className='text-sm text-muted-foreground'>{field === 'question' ? '关联题目' : '关联节点'}</dt><dd className='text-sm'>{labels.get(String(value)) || '关联对象无法识别'}</dd></div>
          if (field === 'role') value = ROLE_LABELS[String(value)] || String(value)
          if (field === 'formulas') return <div key={field} className='contents'><dt className='text-sm text-muted-foreground'>公式</dt><dd><FormulaReview value={value} /></dd></div>
          if (field === 'png_asset') return <div key={field} className='contents'><dt className='text-sm text-muted-foreground'>教学图预览</dt><dd><DiagramAssetPreview asset={typeof value === 'string' ? assets[value] : undefined} filename={typeof value === 'string' ? value : ''} /></dd></div>
          if (field === 'vector_asset') return <div key={field} className='contents'><dt className='text-sm text-muted-foreground'>矢量图源</dt><dd className='text-sm'>{typeof value === 'string' ? value : '未记录'}<span className='ml-2 text-xs text-muted-foreground'>（用于保留可缩放图源）</span></dd></div>
          return <div key={field} className='contents'><dt className='text-sm text-muted-foreground'>{FIELD_LABELS[field] || field}</dt><dd className='whitespace-pre-wrap break-words text-sm'>{formatValue(value)}</dd></div>
        })}
      </dl>
    </li>
  ))}</ol>
}

function formatValue(value: unknown) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return value || '未记录'
  if (Array.isArray(value)) return value.map((item) => typeof item === 'string' ? item : JSON.stringify(item)).join('；') || '未记录'
  if (value === null || value === undefined) return '未记录'
  return JSON.stringify(value)
}

function SourceEvidence({ value, sourcePages }: { value: unknown; sourcePages: Map<string, MaterialPage | undefined> }) {
  const references = Array.isArray(value) ? value : value && typeof value === 'object' ? [value] : []
  if (!references.length) return <span className='text-sm text-muted-foreground'>未记录</span>
  return <div className='space-y-3'>
    {references.map((reference, index) => {
      if (!reference || typeof reference !== 'object' || !('source_id' in reference) || !Array.isArray(reference.bbox)) {
        return <p key={index} className='text-sm text-amber-900'>第 {index + 1} 个来源区域格式待核对。</p>
      }
      const page = sourcePages.get(String(reference.source_id))
      const bbox = reference.bbox as number[]
      return <section key={index} className='space-y-1 rounded-md border p-2'>
        <p className='text-xs text-muted-foreground'>资料页 {page?.position ?? '未映射'} · 原图像素区域：{bbox.join(', ')}</p>
        {page ? <ImageBoxPicker page={page} boxes={[{ bbox: bbox as [number, number, number, number], label: `来源区域 ${index + 1}` }]} onAdd={() => undefined} disabled /> : <p className='text-sm text-amber-900'>找不到该来源对应的原图页。</p>}
      </section>
    })}
  </div>
}

function DiagramAssetPreview({ asset, filename }: { asset: NonNullable<WorkflowDetailResponse['assets']>[string] | undefined; filename: string }) {
  const src = asset?.media_type === 'image/png' ? sameOriginHref(asset.preview_url) : null
  return src ? <figure className='space-y-1'>
    <img src={src} alt='待核对教学图' className='max-h-72 max-w-full rounded-md border bg-white object-contain' />
    <figcaption className='text-xs text-muted-foreground'>导入图像：{filename || '教学图'}</figcaption>
  </figure> : <div className='rounded-md border border-dashed px-3 py-2 text-sm text-amber-900'>教学图预览暂不可用：{filename || '未记录图像文件'}。</div>
}

function CheckField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className='flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm'><input type='checkbox' checked={checked} onChange={(event) => onChange(event.target.checked)} />{label}</label>
}

function workflowErrorMessage(code: string) {
  const messages: Record<string, string> = {
    source_changed: '来源资料或关联版本已经更新，历史任务已保留；请刷新并建立新任务。',
    interrupted: '任务处理已中断，输入和历史已保留；可以手动刷新状态或恢复处理。',
    permission_changed: '家庭访问权限已变化，任务未继续执行；请确认当前权限后联系家庭所有者。',
    render_failed: '五册生成失败，输入和任务历史已保留；请检查资料后再恢复处理。',
  }
  return messages[code] || `任务遇到未识别的问题。联系支持时可提供代码：${code}`
}
