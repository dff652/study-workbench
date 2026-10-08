import { useState, type FormEvent } from 'react'
import { ApiLink } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { PreparationNode, PreparationStage, MaterialPage } from '../../types'
import { ImageBoxPicker } from '../content/image-box-picker'
import { localDateTime } from './workflow-labels'

const NODE_FIELDS: Record<PreparationNode['kind'], Array<[string, string]>> = {
  knowledge: [['definition', '知识定义'], ['conditions', '成立条件'], ['common_errors', '常见错误']],
  method: [['name', '方法名称'], ['conditions', '适用条件'], ['steps', '步骤'], ['notes', '注意事项']],
  question_type: [['name', '题型名称'], ['conditions', '适用条件'], ['structural_features', '结构特征']],
}

export type PreparationReview = {
  checked: boolean
  reason: string
  printed_text: string
  original_number: string
  answer?: { body: string; formulas: Record<string, unknown>[]; basis: string }
  nodes: PreparationNode[]
}

export function PreparationStageCard({
  stage,
  pages,
  canWrite,
  busy,
  isLatest,
  canRedoAgain,
  onConfirm,
  onCancel,
  onRedo,
}: {
  stage: PreparationStage
  pages: MaterialPage[]
  canWrite: boolean
  busy: boolean
  isLatest: boolean
  canRedoAgain: boolean
  onConfirm: (review: PreparationReview) => void
  onCancel: (reason: string) => void
  onRedo: () => void
}) {
  const [printedText, setPrintedText] = useState(stage.proposal?.printed_text || '')
  const [originalNumber, setOriginalNumber] = useState('')
  const [answerEnabled, setAnswerEnabled] = useState(Boolean(stage.proposal?.answer))
  const [answerBody, setAnswerBody] = useState(stage.proposal?.answer?.body || '')
  const [answerBasis, setAnswerBasis] = useState(stage.proposal?.answer?.basis || '')
  const [nodes, setNodes] = useState<PreparationNode[]>(() => (stage.proposal?.nodes || []).map((node) => ({ kind: node.kind, data: { ...node.data } })))
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const answerFormulas = stage.proposal?.answer?.formulas || []
  const requiredAnswerFieldsPresent = !answerEnabled || Boolean(answerBody.trim() && answerBasis.trim())
  const normalizedNodes = nodes.flatMap((node) => {
    const data = Object.fromEntries(Object.entries(node.data).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value))
    const requiredKey = node.kind === 'knowledge' ? 'definition' : 'name'
    return data[requiredKey] ? [{ kind: node.kind, data }] : []
  })
  const canConfirm = canWrite && !busy && stage.can_confirm && Boolean(printedText.trim())
    && checked && Boolean(reason.trim()) && requiredAnswerFieldsPresent
    && normalizedNodes.length === nodes.length && normalizedNodes.length <= 3
  const canCancel = canWrite && !busy && ['queued', 'running', 'awaiting_review', 'failed'].includes(stage.state)
  const canRedo = canWrite && !busy && canRedoAgain && isLatest && ['failed', 'cancelled'].includes(stage.state)

  const confirm = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canConfirm) return
    onConfirm({
      checked,
      reason: reason.trim(),
      printed_text: printedText.trim(),
      original_number: originalNumber.trim(),
      ...(answerEnabled ? { answer: { body: answerBody.trim(), formulas: answerFormulas, basis: answerBasis.trim() } } : {}),
      nodes: normalizedNodes,
    })
  }

  const addNode = (kind: PreparationNode['kind']) => {
    if (busy || nodes.length >= 3) return
    setNodes((current) => [...current, { kind, data: {} }])
  }

  return (
    <Card className='gap-0 border-primary/25 py-0 shadow-sm'>
      <CardHeader className='border-b py-4'>
        <div className='flex flex-wrap items-center gap-2'>
          <CardTitle className='text-base'>准备阶段 · {localDateTime(stage.created_at)}</CardTitle>
          <Badge variant={stage.state === 'applied' ? 'secondary' : 'outline'}>{preparationStateLabel(stage.state)}</Badge>
          {stage.record_count > 0 ? <Badge variant='outline'>{stage.record_count} 项待核对内容</Badge> : null}
        </div>
        <CardDescription>阶段保留原始选择的资料页区域；核对时只修改草稿内容，不会替换来源。</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4 px-5 py-4'>
        {stage.error_code ? <p role='alert' className='workspace-notice workspace-notice--danger'>{preparationErrorMessage(stage.error_code)}</p> : null}
        {stage.proposal ? (
          <>
            <section className='space-y-3' aria-label='本阶段固定原图来源'>
              <h4 className='text-sm font-semibold'>本阶段固定原图来源</h4>
              <SourcePreviews sources={stage.sources} pages={pages} />
            </section>
            {stage.proposal.missing_fields.length ? <div className='workspace-notice workspace-notice--warning text-sm'><p className='font-medium'>模型列出的待补项</p><ul className='mt-1 list-inside list-disc'>{stage.proposal.missing_fields.map((field, index) => <li key={`${field}:${index}`}>{missingFieldLabel(field)}</li>)}</ul></div> : null}
            {stage.can_confirm ? (
              <form className='space-y-4' onSubmit={confirm}>
                <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem]'>
                  <TextField label='模型草稿题干' value={printedText} onChange={setPrintedText} disabled={!canWrite || busy} required />
                  <Field label='原题号（可留空）' value={originalNumber} onChange={setOriginalNumber} disabled={!canWrite || busy} />
                </div>
                <div className='rounded-lg border p-4'>
                  <label className='flex items-start gap-2 text-sm font-medium'>
                    <input type='checkbox' className='mt-1' checked={answerEnabled} disabled={!canWrite || busy} onChange={(event) => setAnswerEnabled(event.target.checked)} />
                    可选家长答案
                  </label>
                  {answerEnabled ? <div className='mt-3 space-y-3'>
                    <TextField label='家长核对的答案或解答' value={answerBody} onChange={setAnswerBody} disabled={!canWrite || busy} required />
                    <TextField label='答案依据' value={answerBasis} onChange={setAnswerBasis} disabled={!canWrite || busy} required />
                    {answerFormulas.length ? <p className='rounded-md bg-muted/30 px-3 py-2 text-sm'>模型草稿含 {answerFormulas.length} 个公式，确认时会原样保留。<ApiLink href={`/question/${encodeURIComponent(stage.question_id)}/`}>高级公式编辑</ApiLink></p> : <p className='text-xs text-muted-foreground'>本表单不编辑公式结构；新答案只保存普通文本。</p>}
                  </div> : null}
                </div>
                <section className='space-y-3'>
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <div><h4 className='text-sm font-semibold'>知识、方法与题型草稿</h4><p className='mt-1 text-xs text-muted-foreground'>可修改或移除；最多保留三个条目，确认时继续使用本阶段来源。</p></div>
                    {nodes.length < 3 ? <label className='text-xs font-medium'>新增条目
                      <select className='ml-2 h-9 rounded-md border bg-background px-2 text-sm' value='' disabled={!canWrite || busy} onChange={(event) => { if (event.target.value) addNode(event.target.value as PreparationNode['kind']) }}>
                        <option value=''>选择类型</option><option value='knowledge'>知识点</option><option value='method'>方法</option><option value='question_type'>题型</option>
                      </select>
                    </label> : null}
                  </div>
                  {nodes.map((node, index) => <NodeEditor key={`${index}:${node.kind}`} node={node} disabled={!canWrite || busy} onRemove={() => setNodes((current) => current.filter((_, row) => row !== index))} onChange={(next) => setNodes((current) => current.map((item, row) => row === index ? next : item))} />)}
                  {nodes.length === 0 ? <p className='rounded-md border border-dashed p-3 text-sm text-muted-foreground'>没有知识／方法／题型草稿；确认时可以保持为空。</p> : null}
                </section>
                <label className='block text-sm font-medium'>本阶段确认原因（必填）<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={reason} onChange={(event) => setReason(event.target.value)} disabled={!canWrite || busy} required /></label>
                <label className='flex items-start gap-2 text-sm'><input type='checkbox' className='mt-1' checked={checked} onChange={(event) => setChecked(event.target.checked)} disabled={!canWrite || busy} />我已对照本阶段原图区域核对题干、答案和条目，并确认保存。</label>
                {canWrite ? <Button type='submit' disabled={!canConfirm}>{busy ? '正在确认…' : '确认本阶段内容'}</Button> : <p className='text-sm text-muted-foreground'>当前成员只读；本阶段草稿可查看，无法确认或取消。</p>}
              </form>
            ) : (
              <div className='space-y-3'>
                {stage.proposal.printed_text ? <p className='whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-sm'>{stage.proposal.printed_text}</p> : <p className='workspace-notice workspace-notice--warning'>题干未识别，保持未知；人工核对后再补写。</p>}
                {stage.proposal.answer ? <p className='text-sm'>包含一份家长答案草稿{answerFormulas.length ? `和 ${answerFormulas.length} 个原样保留的公式` : ''}。</p> : null}
                {stage.state === 'queued' || stage.state === 'running' ? <p role='status' className='text-sm text-muted-foreground'>本阶段仍在处理。页面不会自动轮询；点击“刷新准备阶段”查看结果。</p> : null}
                {stage.state === 'awaiting_review' && !stage.can_confirm ? <p role='status' className='text-sm workspace-inline-state--warning'>阶段上下文已变化，当前结果不能确认。请刷新查看最新状态。</p> : null}
                {stage.state === 'applied' ? <p className='text-sm workspace-inline-state--success'>本阶段内容已人工确认并保存；其他阶段历史仍保留。</p> : null}
              </div>
            )}
          </>
        ) : (
          <p className='text-sm text-muted-foreground'>{stage.state === 'queued' || stage.state === 'running' ? '准备结果尚未返回；可稍后手动刷新。' : '此阶段没有可显示的草稿内容。'}</p>
        )}

        {(canCancel || canRedo) ? <div className='space-y-3 border-t pt-3'>
          {canCancel ? <div className='flex flex-wrap items-end gap-2'>
            <label className='min-w-56 flex-1 text-sm font-medium'>取消阶段原因<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} disabled={busy} /></label>
            <Button type='button' variant='outline' disabled={!cancelReason.trim() || busy} onClick={() => onCancel(cancelReason.trim())}>取消本模型阶段</Button>
          </div> : null}
          {canRedo ? <Button type='button' variant='outline' disabled={busy} onClick={onRedo}>按原来源重做阶段</Button> : null}
        </div> : null}
      </CardContent>
    </Card>
  )
}

function SourcePreviews({ sources, pages }: { sources: PreparationStage['sources']; pages: MaterialPage[] }) {
  const grouped = new Map<string, PreparationStage['sources']>()
  for (const source of sources) grouped.set(source.page_id, [...(grouped.get(source.page_id) || []), source])
  return <div className='grid gap-4 lg:grid-cols-2'>{Array.from(grouped.entries()).map(([pageId, refs]) => {
    const page = pages.find((item) => item.id === pageId)
    if (!page) return <p key={pageId} className='workspace-notice workspace-notice--warning border-dashed'>本阶段包含的来源页已不在当前资料列表中。</p>
    return <div key={pageId} className='space-y-2 rounded-md border p-3'>
      <p className='text-sm font-medium'>资料页 {page.position} · {refs.length} 个固定来源区域</p>
      <ImageBoxPicker page={page} boxes={refs.map((ref, index) => ({ bbox: ref.bbox, label: `本阶段来源区域 ${index + 1}`, color: '#356c3f' }))} onAdd={() => undefined} disabled />
      <ul className='space-y-1 text-xs text-muted-foreground'>{refs.map((ref, index) => <li key={`${ref.bbox.join(':')}:${index}`}>原图区域 [{ref.bbox.join(', ')}] px</li>)}</ul>
    </div>
  })}</div>
}

function NodeEditor({ node, disabled, onChange, onRemove }: { node: PreparationNode; disabled: boolean; onChange: (node: PreparationNode) => void; onRemove: () => void }) {
  const requiredKey = node.kind === 'knowledge' ? 'definition' : 'name'
  return <div className='space-y-3 rounded-lg border p-3'>
    <div className='flex flex-wrap items-center justify-between gap-2'>
      <label className='text-sm font-medium'>条目类型<select className='ml-2 h-9 rounded-md border bg-background px-2' value={node.kind} disabled={disabled} onChange={(event) => onChange({ kind: event.target.value as PreparationNode['kind'], data: {} })}>
        <option value='knowledge'>知识点</option><option value='method'>方法</option><option value='question_type'>题型</option>
      </select></label>
      <Button type='button' variant='ghost' size='sm' disabled={disabled} onClick={onRemove}>移除条目</Button>
    </div>
    {NODE_FIELDS[node.kind].map(([key, label]) => <TextField key={key} label={label} value={node.data[key] || ''} onChange={(value) => onChange({ ...node, data: { ...node.data, [key]: value } })} disabled={disabled} required={key === requiredKey} />)}
  </div>
}

function Field({ label, value, onChange, disabled, required = false }: { label: string; value: string; onChange: (value: string) => void; disabled: boolean; required?: boolean }) {
  return <label className='block text-sm font-medium'>{label}{required ? '（必填）' : ''}<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} required={required} /></label>
}

function TextField({ label, value, onChange, disabled, required = false }: { label: string; value: string; onChange: (value: string) => void; disabled: boolean; required?: boolean }) {
  return <label className='block text-sm font-medium'>{label}{required ? '（必填）' : ''}<textarea className='mt-1 min-h-24 w-full rounded-md border bg-background px-3 py-2 font-normal leading-6' value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} required={required} /></label>
}

export function preparationStateLabel(state: PreparationStage['state']) {
  return ({ queued: '排队中', running: '处理中', awaiting_review: '待人工核对', failed: '准备失败', cancelled: '已取消', stale: '已过期', applied: '已确认' } as const)[state]
}

function preparationErrorMessage(code: string) {
  const messages: Record<string, string> = {
    provider_error: '准备服务未能返回草稿。原图和来源仍保留，可按原来源重做。',
    source_changed: '资料来源已变化；请刷新任务并建立新任务。',
    stale_context: '阶段或结果上下文已变化。请刷新后按最新状态继续。',
    batch_expired: '准备批次已超过有效时间；请建立新任务。',
    invalid_state: '当前任务状态不能继续准备内容。',
  }
  return messages[code] || '本阶段遇到问题；查看任务后可在允许时按原来源重做。'
}

function missingFieldLabel(value: string) {
  if (value === 'printed_text') return '题面未识别或待人工辨认'
  if (value === 'answer') return '家长答案待核对'
  if (value.startsWith('nodes')) return '知识、方法或题型条目待补'
  return value || '待补内容'
}
