import { useRef, useState, type FormEvent } from 'react'
import { CheckCheck, CircleAlert, X } from 'lucide-react'
import { api } from '../../api'
import { ApiLink, errorText, isUnauthorized } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { ContentNodeInput, ContentSource, MaterialContentQuestion, MaterialPage } from '../../types'
import { requestKeyFor, type RequestKeyState } from '../materials/request-keys'
import { ImageBoxPicker } from './image-box-picker'

const NODE_FIELDS = {
  knowledge: [
    ['definition', '知识定义'], ['conditions', '成立条件'], ['common_errors', '常见错误'],
  ],
  method: [
    ['name', '方法名称'], ['conditions', '适用条件'], ['steps', '步骤'], ['notes', '注意事项'],
  ],
  question_type: [
    ['name', '题型名称'], ['conditions', '适用条件'], ['structural_features', '结构特征'],
  ],
} as const

type NodeKind = keyof typeof NODE_FIELDS
type NodeDrafts = Record<NodeKind, Record<string, string>>

function emptyNodeDrafts(): NodeDrafts {
  return { knowledge: {}, method: {}, question_type: {} }
}

export function QuestionEditor({
  materialId,
  context,
  pages,
  selectedPage,
  question,
  canWrite,
  workspaceBusy,
  csrfToken,
  onUnauthorized,
  onBusyChange,
  onUnsavedChange,
  onErratumUnsavedChange,
  onSaved,
}: {
  materialId: string
  context: { source_stamp: string }
  pages: MaterialPage[]
  selectedPage: MaterialPage
  question?: MaterialContentQuestion
  canWrite: boolean
  workspaceBusy: boolean
  csrfToken: string
  onUnauthorized: () => void
  onBusyChange: (busy: boolean) => void
  onUnsavedChange?: (dirty: boolean) => void
  onErratumUnsavedChange?: (dirty: boolean) => void
  onSaved: (questionId: string, message: string) => void
}) {
  const [number, setNumber] = useState(question?.number || '')
  const [printedText, setPrintedText] = useState(question?.printed_text || '')
  const [sources, setSources] = useState<ContentSource[]>(question?.sources || [])
  const [answerEnabled, setAnswerEnabled] = useState(Boolean(question?.answer))
  const [answerBody, setAnswerBody] = useState(question?.answer?.body || '')
  const [answerBasis, setAnswerBasis] = useState(question?.answer?.basis || '')
  const [nodes, setNodes] = useState<NodeDrafts>(emptyNodeDrafts)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const [erratumOpen, setErratumOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [questionDirty, setQuestionDirty] = useState(false)
  const discardQuestionForErratum = useRef(false)
  const requestKey = useRef<RequestKeyState>(null)
  const answerHasRequiredText = !answerEnabled || (answerBody.trim().length > 0 && answerBasis.trim().length > 0)
  const hasNodeDraft = Object.values(nodes).some((draft) => Object.values(draft).some((value) => value.trim().length > 0))
  const formDisabled = !canWrite || busy || workspaceBusy || erratumOpen
  const markQuestionDirty = () => {
    setQuestionDirty(true)
    onUnsavedChange?.(true)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canWrite || busy || workspaceBusy || erratumOpen || !checked || !reason.trim() || !printedText.trim() || sources.length === 0 || !answerHasRequiredText) return
    const nodeInputs = Object.entries(nodes).flatMap(([kind, values]) => {
      const data = Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim()))
      return Object.keys(data).length ? [{ kind: kind as NodeKind, data } satisfies ContentNodeInput] : []
    })
    const answer = answerEnabled ? {
      body: answerBody.trim(),
      formulas: question?.answer?.formulas || [],
      basis: answerBasis.trim(),
    } : undefined
    const payload = {
      expected: context,
      reason: reason.trim(),
      checked: true as const,
      ...(question ? { question_id: question.id } : {}),
      printed_text: printedText.trim(),
      original_number: number.trim(),
      sources,
      ...(answer ? { answer } : {}),
      ...(nodeInputs.length ? { nodes: nodeInputs } : {}),
    }
    setBusy(true)
    onBusyChange(true)
    setError('')
    try {
      const key = requestKeyFor(requestKey, JSON.stringify([materialId, payload]))
      const result = await api.saveMaterialContent(materialId, { ...payload, request_key: key }, csrfToken)
      requestKey.current = null
      setQuestionDirty(false)
      onUnsavedChange?.(false)
      onSaved(result.question_id, '内容已核对并保存；历史版本和来源仍保留。')
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(errorText(cause))
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  const saveDraft = async () => {
    if (!canWrite || busy || workspaceBusy || erratumOpen || !reason.trim() || sources.length === 0 || answerEnabled || hasNodeDraft) return
    const payload = {
      expected: context,
      reason: reason.trim(),
      ...(question ? { question_id: question.id } : {}),
      printed_text: printedText.trim(),
      original_number: number.trim(),
      sources,
    }
    setBusy(true)
    onBusyChange(true)
    setError('')
    try {
      const key = requestKeyFor(requestKey, JSON.stringify(['draft', materialId, payload]))
      const result = await api.saveMaterialContentDraft(materialId, { ...payload, request_key: key }, csrfToken)
      requestKey.current = null
      setQuestionDirty(false)
      onUnsavedChange?.(false)
      onSaved(result.question_id, '待补题面草稿已保存；题目仍未确认。')
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(errorText(cause))
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  const sourceBoxes = sources.filter((source) => source.page_id === selectedPage.id).map((source, index) => ({
    bbox: source.bbox,
    label: `已选来源区域 ${index + 1}`,
  }))
  const formulaCount = question?.answer?.formulas.length || 0

  return (
    <Card className='gap-0 py-0 shadow-sm'>
      <CardHeader className='border-b py-4'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div>
            <CardTitle className='text-base'>{question ? '核对现有题目' : '核对并新建题目'}</CardTitle>
            <CardDescription className='mt-1'>题面转写按图中印刷内容录入；印刷错误应通过“讲义勘误”单独记录。</CardDescription>
          </div>
          {question ? <Badge variant={question.confirmed ? 'secondary' : 'outline'}>{question.confirmed ? '已确认' : '待核对'}</Badge> : <Badge variant='outline'>新题目草稿</Badge>}
        </div>
      </CardHeader>
      <CardContent className='px-5 py-5'>
        {question?.working_text && question.working_text !== question.printed_text ? (
          <div className='mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm'>
            <p className='font-medium text-amber-950'>当前题目工作题干</p>
            <p className='mt-1 whitespace-pre-wrap leading-6 text-amber-900'>{question.working_text}</p>
            <p className='mt-2 text-xs text-amber-900'>与原印刷题面不同的订正请留在讲义勘误记录中。</p>
          </div>
        ) : null}

        <form className='space-y-5' onSubmit={(event) => void submit(event)}>
          <div className='grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,0.9fr)]'>
            <section className='space-y-3' aria-labelledby='content-source-title'>
              <div>
                <h3 id='content-source-title' className='font-semibold'>原图来源区域</h3>
                <p className='mt-1 text-xs leading-5 text-muted-foreground'>当前查看资料页 {selectedPage.position}；在图上框选，确认后以原图整数坐标保存。</p>
              </div>
              <ImageBoxPicker
                page={selectedPage}
                boxes={sourceBoxes}
                disabled={formDisabled}
                onSelectionChange={(hasSelection) => { if (hasSelection) markQuestionDirty() }}
                onAdd={(bbox) => { setSources((current) => [...current, { page_id: selectedPage.id, bbox }]); setError(''); markQuestionDirty() }}
                addLabel='确认添加这个题目来源'
              />
              <div>
                <h4 className='mb-2 text-sm font-medium'>已选来源 · {sources.length} 个</h4>
                {sources.length === 0 ? <p className='rounded-md border border-dashed px-3 py-3 text-sm text-amber-900'>请至少从一张资料页框选题目区域。</p> : (
                  <ul className='space-y-2'>
                    {sources.map((source, index) => {
                      const sourcePage = pages.find((page) => page.id === source.page_id)
                      return (
                        <li key={`${source.page_id}:${index}`} className='flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm'>
                          <span>资料页 {sourcePage?.position ?? '未知'} · 原图区域 [{source.bbox.join(', ')}] px</span>
                          {canWrite ? <button type='button' className='inline-flex items-center gap-1 text-destructive underline' aria-label={`移除第 ${index + 1} 个来源`} onClick={() => { setSources((current) => current.filter((_, sourceIndex) => sourceIndex !== index)); markQuestionDirty() }} disabled={formDisabled}><X className='size-3.5' aria-hidden='true' />移除</button> : null}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </section>

            <section className='space-y-4' aria-labelledby='content-question-title'>
              <div>
                <h3 id='content-question-title' className='font-semibold'>题目内容与核对</h3>
                <p className='mt-1 text-xs text-muted-foreground'>核对图中题面、题号与来源。看不清或缺失处可以保留为空并说明。</p>
              </div>
              <Field label='题号（可留空）' value={number} onChange={(value) => { setNumber(value); markQuestionDirty() }} disabled={formDisabled} />
              <TextField label='图中印刷题面转写' value={printedText} onChange={(value) => { setPrintedText(value); markQuestionDirty() }} disabled={formDisabled} required />

              <div className='rounded-lg border p-4'>
                <label className='flex items-start gap-2 text-sm font-medium'>
                  <input type='checkbox' className='mt-1' checked={answerEnabled} disabled={formDisabled || Boolean(question?.answer)} onChange={(event) => { setAnswerEnabled(event.target.checked); markQuestionDirty() }} />
                  可选家长答案
                </label>
                {answerEnabled ? <div className='mt-3 space-y-3'>
                  <TextField label='家长核对的答案或解答' value={answerBody} onChange={(value) => { setAnswerBody(value); markQuestionDirty() }} disabled={formDisabled} required />
                  <TextField label='答案依据' value={answerBasis} onChange={(value) => { setAnswerBasis(value); markQuestionDirty() }} disabled={formDisabled} required />
                  {formulaCount > 0 ? (
                    <div className='rounded-md bg-muted/30 px-3 py-2 text-sm'>
                      <p>该答案已有 {formulaCount} 个公式，保存时会原样保留。</p>
                      <ApiLink href={question?.question_url}>高级公式编辑</ApiLink>
                    </div>
                  ) : <p className='text-xs text-muted-foreground'>本表单不编辑公式结构；新答案只保存普通文本。</p>}
                </div> : null}
              </div>

              <NodeFields nodes={nodes} onChange={(value) => { setNodes(value); markQuestionDirty() }} disabled={formDisabled} hasSources={sources.length > 0} />

              {canWrite ? (
                <div className='space-y-3 rounded-lg border bg-muted/20 p-4'>
                  <label className='flex items-start gap-2 text-sm'>
                    <input type='checkbox' className='mt-1' checked={checked} onChange={(event) => { setChecked(event.target.checked); markQuestionDirty() }} disabled={formDisabled} />
                    我已对照原图核对题面、题号、来源及已填写内容，并确认保存本次修订。
                  </label>
                  <Field label='本次核对原因' value={reason} onChange={(value) => { setReason(value); markQuestionDirty() }} disabled={formDisabled} required />
                  {error ? <p role='alert' className='text-sm text-destructive'>{error}</p> : null}
                  <div className='sticky bottom-3 z-10 flex flex-wrap gap-2 rounded-md border bg-background p-3'>
                  <Button type='submit' disabled={busy || workspaceBusy || erratumOpen || !checked || !reason.trim() || !printedText.trim() || sources.length === 0 || !answerHasRequiredText}>
                    <CheckCheck aria-hidden='true' />{busy ? '正在保存…' : '确认并保存题目'}
                  </Button>
                  {canWrite ? <Button type='button' variant='outline' onClick={() => void saveDraft()} disabled={busy || workspaceBusy || erratumOpen || !reason.trim() || sources.length === 0 || answerEnabled || hasNodeDraft}>保存待补草稿</Button> : null}
                  </div>
                  {!sources.length ? <p className='text-xs text-amber-900'>先添加至少一个原图来源区域后才能保存。</p> : null}
                  {canWrite ? <p className='text-xs text-muted-foreground'>待补草稿只保存来源与题干，不保存答案或关联条目；题干看不清可留空。</p> : null}
                </div>
              ) : (
                <p className='rounded-md border bg-muted/20 px-4 py-3 text-sm text-muted-foreground'>当前为只读成员，无法确认或修改题目内容。</p>
              )}
            </section>
          </div>
        </form>

        {question && canWrite ? (
          <div className='mt-5 border-t pt-4'>
            {!erratumOpen ? <Button type='button' variant='outline' size='sm' onClick={() => setErratumOpen(true)} disabled={busy || workspaceBusy}><CircleAlert aria-hidden='true' />记录讲义勘误</Button> : (
              <ErratumForm
                materialId={materialId}
                context={context}
                question={question}
                workspaceBusy={workspaceBusy}
                csrfToken={csrfToken}
                onUnauthorized={onUnauthorized}
                onBusyChange={onBusyChange}
                onUnsavedChange={onErratumUnsavedChange}
                onBeforeSave={() => {
                  if (!questionDirty) {
                    discardQuestionForErratum.current = false
                    return true
                  }
                  const confirmed = window.confirm('题目表单还有未保存输入。应用讲义勘误后会重新读取题目并丢弃这些修改，仍要继续吗？')
                  discardQuestionForErratum.current = confirmed
                  return confirmed
                }}
                onCancel={() => {
                  discardQuestionForErratum.current = false
                  setErratumOpen(false)
                }}
                onSaved={(message) => {
                  setErratumOpen(false)
                  if (discardQuestionForErratum.current) {
                    setQuestionDirty(false)
                    onUnsavedChange?.(false)
                  }
                  discardQuestionForErratum.current = false
                  onSaved(question.id, message)
                }}
              />
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function NodeFields({ nodes, onChange, disabled, hasSources }: { nodes: NodeDrafts; onChange: (value: NodeDrafts) => void; disabled: boolean; hasSources: boolean }) {
  return (
    <section className='space-y-2'>
      <h3 className='text-sm font-semibold'>可选新建关联条目</h3>
      <p className='text-xs leading-5 text-muted-foreground'>最多新增一个知识点、一个方法和一个题型；它们会复用当前题目的已选来源。</p>
      {(Object.entries(NODE_FIELDS) as Array<[NodeKind, typeof NODE_FIELDS[NodeKind]]>).map(([kind, fields]) => (
        <details key={kind} className='rounded-lg border px-3 py-2'>
          <summary className='cursor-pointer list-none py-1 text-sm font-medium'>{kindLabel(kind)}（可选）</summary>
          <div className='mt-3 space-y-3'>
            {fields.map(([name, label]) => <TextField key={`${kind}-${name}`} label={label} value={nodes[kind][name] || ''} onChange={(value) => onChange({ ...nodes, [kind]: { ...nodes[kind], [name]: value } })} disabled={disabled} />)}
            {!hasSources ? <p className='text-xs text-amber-900'>新条目必须和题目使用同一组原图来源；请先框选来源。</p> : null}
          </div>
        </details>
      ))}
    </section>
  )
}

function ErratumForm({
  materialId,
  context,
  question,
  workspaceBusy,
  csrfToken,
  onUnauthorized,
  onBusyChange,
  onUnsavedChange,
  onBeforeSave,
  onCancel,
  onSaved,
}: {
  materialId: string
  context: { source_stamp: string }
  question: MaterialContentQuestion
  workspaceBusy: boolean
  csrfToken: string
  onUnauthorized: () => void
  onBusyChange: (busy: boolean) => void
  onUnsavedChange?: (dirty: boolean) => void
  onBeforeSave?: () => boolean
  onCancel: () => void
  onSaved: (message: string) => void
}) {
  const [correctedText, setCorrectedText] = useState(question.working_text || question.printed_text)
  const [basis, setBasis] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draftDirty, setDraftDirty] = useState(false)
  const keyRef = useRef<RequestKeyState>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy || workspaceBusy || !checked || !correctedText.trim() || !basis.trim() || !reason.trim()) return
    if (onBeforeSave && !onBeforeSave()) return
    const payload = {
      expected: context,
      question_id: question.id,
      corrected_text: correctedText.trim(),
      basis: basis.trim(),
      checked: true as const,
      reason: reason.trim(),
    }
    setBusy(true)
    onBusyChange(true)
    setError('')
    try {
      const key = requestKeyFor(keyRef, JSON.stringify([materialId, payload]))
      await api.saveErratum(materialId, { ...payload, request_key: key }, csrfToken)
      keyRef.current = null
      setDraftDirty(false)
      onUnsavedChange?.(false)
      onSaved('讲义勘误已核对并应用；原印刷题面及勘误依据仍会保留。')
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(errorText(cause))
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  return (
    <form className='space-y-4 rounded-lg border border-amber-300 bg-amber-50/60 p-4' onSubmit={(event) => void submit(event)}>
      <div>
        <h3 className='font-semibold text-amber-950'>讲义勘误</h3>
        <p className='mt-1 text-sm leading-5 text-amber-900'>记录讲义印刷内容本身的错误并保留原文；这不会创建学习者作答、错误或评价。</p>
      </div>
      <div className='grid gap-3 sm:grid-cols-2'>
        <div className='rounded-md border bg-background p-3'><p className='text-xs font-medium text-muted-foreground'>原印刷题面（保留）</p><p className='mt-1 whitespace-pre-wrap text-sm'>{question.printed_text || '未记录'}</p></div>
        <div className='rounded-md border bg-background p-3'><p className='text-xs font-medium text-muted-foreground'>当前工作题干</p><p className='mt-1 whitespace-pre-wrap text-sm'>{question.working_text || '未记录'}</p></div>
      </div>
      <TextField label='订正后的讲义题干' value={correctedText} onChange={(value) => { setCorrectedText(value); setDraftDirty(true); onUnsavedChange?.(true) }} disabled={busy || workspaceBusy} required />
      <TextField label='订正依据' value={basis} onChange={(value) => { setBasis(value); setDraftDirty(true); onUnsavedChange?.(true) }} disabled={busy || workspaceBusy} required />
      <Field label='勘误原因' value={reason} onChange={(value) => { setReason(value); setDraftDirty(true); onUnsavedChange?.(true) }} disabled={busy || workspaceBusy} required />
      <label className='flex items-start gap-2 text-sm'>
        <input type='checkbox' className='mt-1' checked={checked} onChange={(event) => { setChecked(event.target.checked); setDraftDirty(true); onUnsavedChange?.(true) }} disabled={busy || workspaceBusy} />
        我已核对讲义原文、订正内容和依据，并确认应用这条勘误。
      </label>
      {error ? <p role='alert' className='text-sm text-destructive'>{error}</p> : null}
      <div className='flex flex-wrap gap-2'>
        <Button type='submit' disabled={busy || workspaceBusy || !checked || !correctedText.trim() || !basis.trim() || !reason.trim()}>{busy ? '正在保存…' : '确认并应用勘误'}</Button>
        <Button type='button' variant='outline' disabled={busy || workspaceBusy} onClick={() => {
          if (draftDirty && !window.confirm('讲义勘误还有未保存内容，返回会丢失这些输入。仍要返回吗？')) return
          if (draftDirty) onUnsavedChange?.(false)
          onCancel()
        }}>返回题目核对</Button>
      </div>
    </form>
  )
}

function Field({ label, value, onChange, required = false, disabled = false }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; disabled?: boolean }) {
  return <label className='block text-sm font-medium'>{label}{required ? '（必填）' : ''}<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={value} onChange={(event) => onChange(event.target.value)} required={required} disabled={disabled} /></label>
}

function TextField({ label, value, onChange, required = false, disabled = false }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; disabled?: boolean }) {
  return <label className='block text-sm font-medium'>{label}{required ? '（必填）' : ''}<textarea className='mt-1 min-h-24 w-full rounded-md border bg-background px-3 py-2 font-normal leading-6' value={value} onChange={(event) => onChange(event.target.value)} required={required} disabled={disabled} /></label>
}

function kindLabel(kind: NodeKind) {
  return kind === 'knowledge' ? '新增知识点' : kind === 'method' ? '新增方法' : '新增题型'
}
