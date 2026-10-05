import { useEffect, useRef, useState } from 'react'
import { ImageBoxPicker } from '../content/image-box-picker'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { Disclosure } from '../../components/disclosure'
import { deriveSolutionAsset, getErrorMessage, previewSolutionFormula, uploadSolutionAsset } from '../../api'
import { errorText, isUnauthorized } from '../../components/shared'
import { FormulaDisplay } from '../../components/formula-preview'
import { HelpTip } from '../../components/help-tip'
import { requestKeyFor, type RequestKeyState } from '../materials/request-keys'
import type {
  MaterialPage,
  SolutionAsset,
  SolutionPart,
  SolutionQuestion,
  SolutionSource,
  SolutionStep,
  StructuredSolutionContent,
  StructuredSolutionQuestion,
  SolutionWorkspaceResponse,
} from '../../types'
import { newSolutionId, newSolutionPart, newSolutionQuestion, newSolutionStep } from './model'

const fieldClass = 'mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm'
const textareaClass = `${fieldClass} min-h-20`
const nodeRelations = [
  { value: 'knowledge', label: '知识点', kind: 'knowledge' },
  { value: 'primary_method', label: '主要方法', kind: 'method' },
  { value: 'secondary_method', label: '辅助方法', kind: 'method' },
  { value: 'question_type', label: '题型', kind: 'question_type' },
] as const

export function SolutionEditor({
  content,
  workspace,
  materialId,
  csrfToken,
  canWrite,
  onChange,
  onAssetsChanged,
  onUnauthorized,
}: {
  content: StructuredSolutionContent
  workspace: SolutionWorkspaceResponse
  materialId: string
  csrfToken: string
  canWrite: boolean
  onChange: (content: StructuredSolutionContent) => void
  onAssetsChanged: (assets: SolutionAsset[]) => void
  onUnauthorized: () => void
}) {
  const [activeId, setActiveId] = useState(content.questions[0]?.id || '')
  const [busyAssetQuestions, setBusyAssetQuestions] = useState<Set<string>>(() => new Set())
  useEffect(() => {
    if (content.questions.some((question) => question.id === activeId)) return
    setActiveId(content.questions[0]?.id || '')
  }, [activeId, content.questions])

  const updateQuestion = (id: string, change: (question: StructuredSolutionQuestion) => StructuredSolutionQuestion) => {
    onChange({ ...content, questions: content.questions.map((question) => question.id === id ? change(question) : question) })
  }
  const activeQuestion = content.questions.find((question) => question.id === activeId)

  return <div className='space-y-5'>
    <Disclosure title='文档设置' description='文档标题、讲次和输出格式。解析草稿仍可保留未知项，题干、来源区域和答案的未知状态会原样保存。'>
      <div className='grid gap-5 lg:grid-cols-2'>
        <label className='text-sm font-medium'>文档标题<input className={fieldClass} maxLength={160} value={content.title} disabled={!canWrite} onChange={(event) => onChange({ ...content, title: event.target.value })} /></label>
        <div className='space-y-2'>
          <div className='flex items-center justify-between gap-2'><h3 className='text-sm font-semibold'>讲次</h3><Button type='button' size='sm' variant='outline' disabled={!canWrite} onClick={() => onChange({ ...content, lectures: [...content.lectures, { id: newSolutionId('lecture'), title: `第 ${content.lectures.length + 1} 讲` }] })}>添加讲次</Button></div>
          <div className='space-y-2'>
            {content.lectures.map((lecture) => <div key={lecture.id} className='flex gap-2'>
              <input aria-label={`讲次 ${lecture.title}`} className={fieldClass} maxLength={160} value={lecture.title} disabled={!canWrite} onChange={(event) => onChange({ ...content, lectures: content.lectures.map((item) => item.id === lecture.id ? { ...item, title: event.target.value } : item) })} />
              <Button type='button' variant='outline' disabled={!canWrite || content.lectures.length <= 1 || content.questions.some((question) => question.lecture_id === lecture.id)} onClick={() => onChange({ ...content, lectures: content.lectures.filter((item) => item.id !== lecture.id) })}>删除</Button>
            </div>)}
          </div>
        </div>
        <div className='space-y-2 lg:col-span-2'>
          <h3 className='text-sm font-semibold'>输出组织与格式</h3>
          <div className='grid gap-2 md:grid-cols-3'>
            {([
              ['per_question', '逐题文档'], ['per_lecture', '按讲次合并'], ['combined', '整份合并'],
            ] as const).map(([organization, label]) => <fieldset key={organization} className='rounded-md border p-3'>
              <legend className='px-1 text-sm font-medium'>{label}</legend>
              {(['pdf', 'docx'] as const).map((format) => <label key={format} className='mr-4 inline-flex items-center gap-2 text-sm'>
                <input type='checkbox' checked={content.outputs[organization].includes(format)} disabled={!canWrite} onChange={(event) => {
                  const formats = content.outputs[organization]
                  const next = event.target.checked ? [...formats, format] : formats.filter((item) => item !== format)
                  onChange({ ...content, outputs: { ...content.outputs, [organization]: next } })
                }} />{format === 'pdf' ? 'PDF' : 'Word'}
              </label>)}
            </fieldset>)}
          </div>
        </div>
      </div>
    </Disclosure>

    <Card>
      <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b pb-4'>
        <div><CardTitle className='text-base'>逐题内容</CardTitle><CardDescription>每题的来源、讲次、讲义解法和订正都分别记录。</CardDescription></div>
        <Button type='button' disabled={!canWrite || content.lectures.length === 0} onClick={() => {
          const question = newSolutionQuestion(content.lectures[0].id)
          onChange({ ...content, questions: [...content.questions, question] })
          setActiveId(question.id)
        }}>添加题目</Button>
      </CardHeader>
      <CardContent className='space-y-4 pt-4'>
        {content.questions.length === 0 ? <p className='rounded-md border border-dashed p-4 text-sm text-muted-foreground'>当前还是空白草稿；添加题目后逐项整理即可保存，生成前需要题目、小问和原图来源。</p> : <div className='grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)]'>
          <nav aria-label='解析题目' className='flex gap-2 overflow-x-auto lg:flex-col lg:overflow-visible'>
            {content.questions.map((question, index) => <button key={question.id} type='button' aria-pressed={activeId === question.id} onClick={() => setActiveId(question.id)} className={`shrink-0 rounded-md border px-3 py-2 text-left text-sm ${activeId === question.id ? 'border-primary bg-primary/5 font-semibold' : 'hover:bg-muted/40'}`}>
              {question.number.trim() || `未编号题目 ${index + 1}`}{question.title.trim() ? ` · ${question.title.trim()}` : ''}
            </button>)}
          </nav>
          {activeQuestion ? <QuestionEditor
            key={activeQuestion.id}
            question={activeQuestion}
            lectures={content.lectures}
            pages={workspace.pages}
            assets={workspace.assets}
            publishedQuestions={workspace.questions}
            nodes={workspace.nodes}
            materialId={materialId}
            csrfToken={csrfToken}
            canWrite={canWrite && workspace.writable}
            assetRequestBusy={busyAssetQuestions.has(activeQuestion.id)}
            onAssetRequestBusy={(busy) => setBusyAssetQuestions((current) => {
              const next = new Set(current)
              if (busy) next.add(activeQuestion.id)
              else next.delete(activeQuestion.id)
              return next
            })}
            onChange={(change) => updateQuestion(activeQuestion.id, change)}
            onRemove={() => {
              const next = content.questions.filter((question) => question.id !== activeQuestion.id)
              onChange({ ...content, questions: next })
              setActiveId(next[0]?.id || '')
            }}
            onAssetsChanged={onAssetsChanged}
            onUnauthorized={onUnauthorized}
          /> : null}
        </div>}
      </CardContent>
    </Card>
  </div>
}

function QuestionEditor({
  question,
  lectures,
  pages,
  assets,
  publishedQuestions,
  nodes,
  materialId,
  csrfToken,
  canWrite,
  assetRequestBusy,
  onAssetRequestBusy,
  onChange,
  onRemove,
  onAssetsChanged,
  onUnauthorized,
}: {
  question: StructuredSolutionQuestion
  lectures: StructuredSolutionContent['lectures']
  pages: SolutionWorkspaceResponse['pages']
  assets: SolutionAsset[]
  publishedQuestions: SolutionWorkspaceResponse['questions']
  nodes: SolutionWorkspaceResponse['nodes']
  materialId: string
  csrfToken: string
  canWrite: boolean
  assetRequestBusy: boolean
  onAssetRequestBusy: (busy: boolean) => void
  onChange: (change: (question: StructuredSolutionQuestion) => StructuredSolutionQuestion) => void
  onRemove: () => void
  onAssetsChanged: (assets: SolutionAsset[]) => void
  onUnauthorized: () => void
}) {
  const change = (patch: Partial<StructuredSolutionQuestion>) => onChange((current) => ({ ...current, ...patch }))
  const [sourcePageId, setSourcePageId] = useState(pages[0]?.id || '')
  const sourcePage = pages.find((page) => page.id === sourcePageId)
  useEffect(() => {
    if (!pages.some((page) => page.id === sourcePageId)) setSourcePageId(pages[0]?.id || '')
  }, [pages, sourcePageId])
  const selectedSources = question.sources.filter((source) => source.page_id === sourcePageId)
  const imagePage: MaterialPage | undefined = sourcePage ? {
    id: sourcePage.id,
    position: pages.findIndex((page) => page.id === sourcePage.id) + 1,
    sha256: '',
    width: sourcePage.width,
    height: sourcePage.height,
    page_url: sourcePage.detail_url,
    preview_url: sourcePage.preview_url,
  } : undefined

  const addPart = (parentId: string | null = null) => change({ parts: [...question.parts, newSolutionPart(parentId)] })
  const updatePart = (id: string, patch: Partial<SolutionPart>) => change({ parts: question.parts.map((part) => part.id === id ? { ...part, ...patch } : part) })
  const removePart = (id: string) => {
    const removed = new Set([id])
    let found = true
    while (found) {
      found = false
      for (const part of question.parts) if (part.parent_id && removed.has(part.parent_id) && !removed.has(part.id)) {
        removed.add(part.id)
        found = true
      }
    }
    change({ parts: question.parts.filter((part) => !removed.has(part.id)) })
  }

  return <div className='space-y-4'>
    <Card className='gap-0 py-0 shadow-none'>
      <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b py-4'>
        <div><CardTitle className='text-base'>{question.number.trim() || '未编号题目'}</CardTitle><CardDescription>题目字段、来源和逐层小问。</CardDescription></div>
        <Button type='button' variant='outline' disabled={!canWrite || assetRequestBusy} onClick={onRemove}>删除此题</Button>
      </CardHeader>
      <CardContent className='grid gap-4 pt-4 md:grid-cols-2'>
        <label className='text-sm font-medium'>所属讲次<select className={fieldClass} disabled={!canWrite} value={question.lecture_id} onChange={(event) => change({ lecture_id: event.target.value })}>{lectures.map((lecture) => <option key={lecture.id} value={lecture.id}>{lecture.title}</option>)}</select></label>
        <label className='text-sm font-medium'>题号<input className={fieldClass} maxLength={160} disabled={!canWrite} value={question.number} onChange={(event) => change({ number: event.target.value })} /></label>
        <label className='text-sm font-medium md:col-span-2'>题目标题<input className={fieldClass} maxLength={160} disabled={!canWrite} value={question.title} onChange={(event) => change({ title: event.target.value })} /></label>
        <div className='md:col-span-2'><div className='text-sm font-medium'>题干<NullableText value={question.statement.text} disabled={!canWrite} onChange={(text) => change({ statement: { ...question.statement, text } })} /></div>
          <label className='mt-3 block text-sm font-medium'>题干状态<select className={fieldClass} disabled={!canWrite} value={question.statement.status} onChange={(event) => change({ statement: { ...question.statement, status: event.target.value as SolutionQuestion['statement']['status'] } })}><option value='complete'>已核对完整</option><option value='partial'>部分记录</option><option value='unknown'>未知 / 待核对</option></select></label>
        </div>
        <label className='text-sm font-medium md:col-span-2'>关联已发布题目（可选）<select className={fieldClass} disabled={!canWrite} value={question.question_revision_id || ''} onChange={(event) => change({ question_revision_id: event.target.value || null })}><option value=''>不关联</option>{question.question_revision_id && !publishedQuestions.some((item) => item.revision_id === question.question_revision_id) ? <option value={question.question_revision_id}>历史已发布题目</option> : null}{publishedQuestions.map((item) => <option key={item.revision_id} value={item.revision_id}>{item.label}</option>)}</select></label>
      </CardContent>
    </Card>

    <Card className='gap-0 py-0 shadow-none'>
      <CardHeader className='border-b py-4'><CardTitle className='text-base'>原图来源</CardTitle><CardDescription>来源范围用原图像素坐标保存；整页来源保留范围未知。看不清或没核对的范围继续保留未知。</CardDescription></CardHeader>
      <CardContent className='space-y-3 pt-4'>
        {pages.length ? <label className='block max-w-sm text-sm font-medium'>选择资料页<select className={fieldClass} disabled={!canWrite || assetRequestBusy} value={sourcePageId} onChange={(event) => setSourcePageId(event.target.value)}>{pages.map((page) => <option key={page.id} value={page.id}>{page.label}</option>)}</select></label> : <p className='text-sm text-amber-900'>当前资料没有原图页。可以先保存私人草稿；生成前需要补充原图来源。</p>}
        {imagePage ? <ImageBoxPicker page={imagePage} boxes={selectedSources.flatMap((source) => source.region ? [{ bbox: source.region, label: '已记录解析来源区域' }] : [])} onAdd={(region) => change({ sources: [...question.sources, { page_id: sourcePageId, region }] })} disabled={!canWrite || assetRequestBusy} addLabel='将原图选区加入本题来源' /> : null}
        {sourcePage && canWrite ? <Button type='button' size='sm' variant='outline' disabled={assetRequestBusy} onClick={() => change({ sources: [...question.sources, { page_id: sourcePage.id, region: null }] })}>加入整页来源（范围未知）</Button> : null}
        {question.sources.length ? <ul className='space-y-2'>
          {question.sources.map((source, index) => <li key={`${source.page_id}:${index}`} className='flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm'>
            <span>{pages.find((page) => page.id === source.page_id)?.label || '资料页'} · {source.region ? `原图区域 ${source.region.join(', ')} px` : '整页来源，区域未知'}</span>
            <Button type='button' size='sm' variant='outline' disabled={!canWrite || assetRequestBusy} onClick={() => change({ sources: question.sources.filter((_, sourceIndex) => sourceIndex !== index) })}>移除</Button>
          </li>)}
        </ul> : <p className='text-sm text-muted-foreground'>此题尚未关联来源。</p>}
      </CardContent>
    </Card>

    <Card className='gap-0 py-0 shadow-none'>
      <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b py-4'><div><CardTitle className='text-base'>小问与答案</CardTitle><CardDescription>可指定上级小问，未知的题干、答案或单位按未知保存。</CardDescription></div><Button type='button' size='sm' variant='outline' disabled={!canWrite} onClick={() => addPart()}>添加顶层小问</Button></CardHeader>
      <CardContent className='space-y-3 pt-4'>
        {question.parts.map((part) => <PartEditor key={part.id} part={part} parts={question.parts} disabled={!canWrite} onChange={(patch) => updatePart(part.id, patch)} onRemove={() => removePart(part.id)} />)}
        {question.parts.length === 0 ? <p className='text-sm text-muted-foreground'>尚未添加小问。空白草稿允许保存，生成前需要至少一个小问。</p> : null}
        {question.parts.length > 0 && canWrite ? <label className='block max-w-sm text-sm font-medium'>添加子问到<select className={fieldClass} value='' onChange={(event) => { if (event.target.value) addPart(event.target.value) }}><option value=''>选择上级小问</option>{question.parts.map((part) => <option key={part.id} value={part.id}>{part.label || '未命名小问'}</option>)}</select></label> : null}
      </CardContent>
    </Card>

    <Card className='gap-0 py-0 shadow-none'>
      <CardHeader className='border-b py-4'><CardTitle className='text-base'>思路与解法</CardTitle><CardDescription>先写思路，再按顺序添加步骤；每步可以写文字、公式或图示。</CardDescription></CardHeader>
      <CardContent className='grid gap-4 pt-4 md:grid-cols-2'>
        <label className='text-sm font-medium'>解题思路<textarea className={textareaClass} disabled={!canWrite} value={question.thinking} onChange={(event) => change({ thinking: event.target.value })} /></label>
        <label className='text-sm font-medium'>本讲解法<textarea className={textareaClass} disabled={!canWrite} value={question.lecture_method} onChange={(event) => change({ lecture_method: event.target.value })} /></label>
        <label className='text-sm font-medium md:col-span-2'>其他解法说明<textarea className={textareaClass} disabled={!canWrite} value={question.alternative_method} onChange={(event) => change({ alternative_method: event.target.value })} /></label>
        <div className='space-y-3 md:col-span-2'>
          <SolutionStepList title='解题步骤' steps={question.steps} assets={assets} disabled={!canWrite} csrfToken={csrfToken} onUnauthorized={onUnauthorized} onChange={(steps) => change({ steps })} />
          <SolutionStepList title='其他解法步骤' steps={question.alternative_steps} assets={assets} disabled={!canWrite} csrfToken={csrfToken} onUnauthorized={onUnauthorized} onChange={(alternative_steps) => change({ alternative_steps })} />
        </div>
        <StringListEditor title='易错点' values={question.pitfalls} disabled={!canWrite} onChange={(pitfalls) => change({ pitfalls })} />
        {question.formulas.length ? <details className='rounded-md border p-3'>
          <summary className='cursor-pointer text-sm font-medium'>未关联到步骤的历史公式（{question.formulas.length}）</summary>
          <div className='mt-3'><FormulaListEditor values={question.formulas} csrfToken={csrfToken} disabled={!canWrite} onUnauthorized={onUnauthorized} onChange={(formulas) => change({ formulas })} /></div>
        </details> : null}
        <StringListEditor title='待核实事项' values={question.unknowns} disabled={!canWrite} onChange={(unknowns) => change({ unknowns })} />
      </CardContent>
    </Card>

    <Card className='gap-0 py-0 shadow-none'>
      <CardHeader className='border-b py-4'><CardTitle className='text-base'>补充信息</CardTitle><CardDescription>必要时展开关联、题面图示、订正依据与素材。</CardDescription></CardHeader>
      <CardContent className='space-y-5 pt-4'>
        <details>
          <summary className='cursor-pointer rounded-md py-2 text-sm font-medium'>知识关联、题面图示、订正与素材</summary>
          <div className='space-y-5 pt-3'>
            <LinkEditor links={question.links} nodes={nodes} disabled={!canWrite} onChange={(links) => change({ links })} />
            <FigureEditor figures={question.figures} assets={assets} disabled={!canWrite} onChange={(figures) => change({ figures })} />
            <AssetUploader question={question} pages={pages} assets={assets} materialId={materialId} csrfToken={csrfToken} disabled={!canWrite || assetRequestBusy} onBusyChange={onAssetRequestBusy} onAssetsChanged={onAssetsChanged} onUnauthorized={onUnauthorized} />
            <CorrectionEditor corrections={question.corrections} disabled={!canWrite} onChange={(corrections) => change({ corrections })} />
          </div>
        </details>
      </CardContent>
    </Card>
  </div>
}

function NullableText({ value, disabled, onChange }: { value: string | null; disabled: boolean; onChange: (value: string | null) => void }) {
  return <div>
    <label className='mt-1 inline-flex items-center gap-2 text-xs font-normal text-muted-foreground'><input type='checkbox' checked={value === null} disabled={disabled} onChange={(event) => onChange(event.target.checked ? null : '')} />内容未知</label>
    <textarea className={textareaClass} value={value ?? ''} disabled={disabled || value === null} onChange={(event) => onChange(event.target.value)} />
  </div>
}

function PartEditor({ part, parts, disabled, onChange, onRemove }: { part: SolutionPart; parts: SolutionPart[]; disabled: boolean; onChange: (patch: Partial<SolutionPart>) => void; onRemove: () => void }) {
  const descendants = new Set<string>()
  let changed = true
  while (changed) {
    changed = false
    for (const candidate of parts) if (candidate.parent_id && (candidate.parent_id === part.id || descendants.has(candidate.parent_id)) && !descendants.has(candidate.id)) {
      descendants.add(candidate.id)
      changed = true
    }
  }
  return <fieldset className='rounded-lg border p-3'>
    <legend className='px-1 text-sm font-semibold'>{part.label || '小问'}</legend>
    <div className='grid gap-3 md:grid-cols-2'>
      <label className='text-sm font-medium'>小问标记<input className={fieldClass} maxLength={160} disabled={disabled} value={part.label} onChange={(event) => onChange({ label: event.target.value })} /></label>
      <label className='text-sm font-medium'>上级小问<select className={fieldClass} disabled={disabled} value={part.parent_id || ''} onChange={(event) => onChange({ parent_id: event.target.value || null })}><option value=''>顶层小问</option>{parts.filter((candidate) => candidate.id !== part.id && !descendants.has(candidate.id)).map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.label || '未命名小问'}</option>)}</select></label>
      <div className='text-sm font-medium'>小问题干<NullableText value={part.statement} disabled={disabled} onChange={(statement) => onChange({ statement })} /></div>
      <div className='text-sm font-medium'>答案<NullableText value={part.answer} disabled={disabled} onChange={(answer) => onChange({ answer })} /></div>
      <div className='text-sm font-medium'>单位<NullableText value={part.unit} disabled={disabled} onChange={(unit) => onChange({ unit })} /></div>
      <div className='flex items-end justify-end'><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={onRemove}>删除小问</Button></div>
    </div>
  </fieldset>
}

function SolutionStepList({ title, steps, assets, disabled, csrfToken, onUnauthorized, onChange }: {
  title: string
  steps: SolutionStep[]
  assets: SolutionAsset[]
  disabled: boolean
  csrfToken: string
  onUnauthorized: () => void
  onChange: (steps: SolutionStep[]) => void
}) {
  const update = (id: string, patch: Partial<SolutionStep>) => onChange(steps.map((step) => step.id === id ? { ...step, ...patch } : step))
  const move = (id: string, direction: -1 | 1) => {
    const index = steps.findIndex((step) => step.id === id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= steps.length) return
    const next = [...steps]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }
  const add = () => onChange([...steps, newSolutionStep()])

  return <section className='space-y-3 rounded-md border p-3'>
    <div className='flex flex-wrap items-center justify-between gap-2'>
      <div className='flex items-center gap-2'><h3 className='text-sm font-semibold'>{title}</h3><HelpTip label={`${title}帮助`}>每一步可包含文字、公式和一张图示。添加素材后，可在步骤里明确选择；旧文字、公式和图示会按原顺序分别保留。</HelpTip></div>
      <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={add}>添加步骤</Button>
    </div>
    {steps.map((step, index) => <SolutionStepEditor
      key={step.id}
      step={step}
      index={index}
      total={steps.length}
      assets={assets}
      disabled={disabled}
      csrfToken={csrfToken}
      onUnauthorized={onUnauthorized}
      onChange={(patch) => update(step.id, patch)}
      onMove={(direction) => move(step.id, direction)}
      onRemove={() => onChange(steps.filter((item) => item.id !== step.id))}
    />)}
    {steps.length === 0 ? <p className='text-sm text-muted-foreground'>还没有步骤；可以先填写思路，也可以添加第一步。</p> : null}
  </section>
}

function SolutionStepEditor({ step, index, total, assets, disabled, csrfToken, onUnauthorized, onChange, onMove, onRemove }: {
  step: SolutionStep
  index: number
  total: number
  assets: SolutionAsset[]
  disabled: boolean
  csrfToken: string
  onUnauthorized: () => void
  onChange: (patch: Partial<SolutionStep>) => void
  onMove: (direction: -1 | 1) => void
  onRemove: () => void
}) {
  const asset = assets.find((item) => item.id === step.figure?.asset_id)
  return <fieldset className='space-y-3 rounded-md bg-muted/10 p-3'>
    <legend className='px-1 text-sm font-medium'>{index + 1}. {step.text.trim() || step.formula?.trim() || asset?.label || '步骤'}</legend>
    <div className='flex flex-wrap items-center justify-between gap-2'>
      <label className='inline-flex items-center gap-2 text-sm'><input type='checkbox' checked={step.new_page} disabled={disabled} onChange={(event) => onChange({ new_page: event.target.checked })} />从新页开始</label>
      <div className='flex gap-2'>
        <Button type='button' size='sm' variant='outline' aria-label={`第 ${index + 1} 步上移`} disabled={disabled || index === 0} onClick={() => onMove(-1)}>上移</Button>
        <Button type='button' size='sm' variant='outline' aria-label={`第 ${index + 1} 步下移`} disabled={disabled || index === total - 1} onClick={() => onMove(1)}>下移</Button>
        <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={onRemove}>删除步骤</Button>
      </div>
    </div>
    <label className='block text-sm font-medium'>步骤文字<textarea aria-label={`第 ${index + 1} 步文字`} className={textareaClass} disabled={disabled} value={step.text} onChange={(event) => onChange({ text: event.target.value })} /></label>
    {step.formula === null ? <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ formula: '' })}>添加公式</Button> : <section className='space-y-2 rounded-md border p-3'>
      <div className='flex items-center justify-between gap-2'><h4 className='text-sm font-medium'>本步骤公式</h4><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ formula: null })}>移除公式</Button></div>
      <StepFormulaPreview stepId={step.id} stepNumber={index + 1} value={step.formula} csrfToken={csrfToken} disabled={disabled} onUnauthorized={onUnauthorized} onChange={(formula) => onChange({ formula })} />
    </section>}
    {step.figure === null ? <Button type='button' size='sm' variant='outline' disabled={disabled || assets.length === 0} onClick={() => {
      const first = assets[0]
      if (first) onChange({ figure: { asset_id: first.id, role: 'method', caption: '', width_mm: 80 } })
    }}>添加图示</Button> : <section className='grid gap-2 rounded-md border p-3 md:grid-cols-2'>
      <div className='flex items-center justify-between gap-2 md:col-span-2'><h4 className='text-sm font-medium'>本步骤图示</h4><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ figure: null })}>移除图示</Button></div>
      <label className='text-xs font-medium'>图片素材<select className={fieldClass} disabled={disabled || assets.length === 0} value={step.figure.asset_id} onChange={(event) => onChange({ figure: { ...step.figure!, asset_id: event.target.value } })}>
        {!assets.some((item) => item.id === step.figure?.asset_id) ? <option value={step.figure.asset_id}>历史图示素材</option> : null}
        {assets.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.kind === 'auxiliary' ? '辅助图' : '原图引用'}</option>)}
      </select></label>
      <label className='text-xs font-medium'>用途<select className={fieldClass} disabled={disabled} value={step.figure.role} onChange={(event) => onChange({ figure: { ...step.figure!, role: event.target.value as NonNullable<SolutionStep['figure']>['role'] } })}><option value='question'>题面</option><option value='method'>解法</option><option value='answer'>答案</option></select></label>
      <label className='text-xs font-medium md:col-span-2'>图注<input className={fieldClass} maxLength={2000} disabled={disabled} value={step.figure.caption} onChange={(event) => onChange({ figure: { ...step.figure!, caption: event.target.value } })} /></label>
      <label className='text-xs font-medium md:col-span-2'>图示宽度（毫米）<input className={fieldClass} type='number' min={10} max={172} step={1} disabled={disabled} value={step.figure.width_mm} onChange={(event) => onChange({ figure: { ...step.figure!, width_mm: Number(event.target.value) } })} /></label>
      {asset ? <figure className='md:col-span-2'><img className='max-h-56 max-w-full rounded-md border object-contain' src={asset.url} alt={step.figure.caption || asset.label} /><figcaption className='mt-1 text-xs text-muted-foreground'>{step.figure.caption || asset.label} · {asset.kind === 'auxiliary' ? '辅助图' : '原图引用'}</figcaption></figure> : null}
    </section>}
  </fieldset>
}

function StepFormulaPreview({ stepId, stepNumber, value, csrfToken, disabled, onUnauthorized, onChange }: {
  stepId: string
  stepNumber: number
  value: string
  csrfToken: string
  disabled: boolean
  onUnauthorized: () => void
  onChange: (expression: string) => void
}) {
  const [preview, setPreview] = useState<{ stepId: string; expression: string; status: 'loading' } | { stepId: string; expression: string; status: 'ready'; formula: unknown } | { stepId: string; expression: string; status: 'error'; message: string } | null>(null)

  useEffect(() => {
    const expression = value.trim()
    if (!expression) {
      setPreview(null)
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setPreview({ stepId, expression: value, status: 'loading' })
      void previewSolutionFormula(expression, csrfToken, controller.signal).then((response) => {
        if (!controller.signal.aborted) setPreview({ stepId, expression: value, status: 'ready', formula: response.formula })
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (isUnauthorized(error)) onUnauthorized()
        setPreview({ stepId, expression: value, status: 'error', message: errorText(error) })
      })
    }, 400)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [stepId, value, csrfToken, onUnauthorized])

  const currentPreview = preview?.stepId === stepId && preview.expression === value ? preview : null
  return <div className='space-y-2'>
    <label className='block text-xs font-medium'>公式表达式<textarea aria-label={`第 ${stepNumber} 步公式表达式`} className={textareaClass} disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} /></label>
    <div role='region' aria-label={`第 ${stepNumber} 步公式预览`} className='min-h-12 rounded-md bg-muted/30 px-3 py-2'>
      {!value.trim() ? <p className='text-sm text-muted-foreground'>输入公式后自动预览。</p> : null}
      {value.trim() && (!currentPreview || currentPreview.status === 'loading') ? <p className='text-sm text-muted-foreground' role='status'>正在生成公式预览…</p> : null}
      {currentPreview?.status === 'ready' ? <FormulaDisplay value={currentPreview.formula} /> : null}
      {currentPreview?.status === 'error' ? <p className='text-sm text-amber-900' role='alert'>预览失败：{currentPreview.message}。公式原文已保留；修改表达式后可重试。</p> : null}
    </div>
  </div>
}

function StringListEditor({ title, values, disabled, onChange }: { title: string; values: string[]; disabled: boolean; onChange: (values: string[]) => void }) {
  return <div className='space-y-2'>
    <div className='flex items-center justify-between gap-2'><h3 className='text-sm font-semibold'>{title}</h3><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange([...values, ''])}>添加</Button></div>
    {values.map((value, index) => <div key={index} className='flex items-start gap-2'><textarea aria-label={`${title} ${index + 1}`} className={textareaClass} disabled={disabled} value={value} onChange={(event) => onChange(values.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} /><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))}>移除</Button></div>)}
    {values.length === 0 ? <p className='text-xs text-muted-foreground'>未记录</p> : null}
  </div>
}

function FormulaListEditor({ values, csrfToken, disabled, onUnauthorized, onChange }: {
  values: string[]; csrfToken: string; disabled: boolean; onUnauthorized: () => void; onChange: (values: string[]) => void
}) {
  return <section className='space-y-2'>
    <div className='flex items-center justify-between gap-2'><h3 className='text-sm font-semibold'>公式</h3><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange([...values, ''])}>添加公式</Button></div>
    {values.map((value, index) => <FormulaExpressionField key={index} label={`公式 ${index + 1}`} value={value} csrfToken={csrfToken} disabled={disabled} onUnauthorized={onUnauthorized} onChange={(expression) => onChange(values.map((item, itemIndex) => itemIndex === index ? expression : item))} onRemove={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))} />)}
    {values.length === 0 ? <p className='text-xs text-muted-foreground'>未记录</p> : null}
  </section>
}

function FormulaExpressionField({ label, value, csrfToken, disabled, onUnauthorized, onChange, onRemove }: {
  label: string; value: string; csrfToken: string; disabled: boolean; onUnauthorized: () => void
  onChange: (expression: string) => void; onRemove: () => void
}) {
  const [preview, setPreview] = useState<{ expression: string; status: 'loading' } | { expression: string; status: 'ready'; formula: unknown } | { expression: string; status: 'error'; message: string } | null>(null)

  useEffect(() => {
    const expression = value.trim()
    if (!expression) {
      setPreview(null)
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setPreview({ expression: value, status: 'loading' })
      void previewSolutionFormula(expression, csrfToken, controller.signal).then((response) => {
        if (!controller.signal.aborted) setPreview({ expression: value, status: 'ready', formula: response.formula })
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (isUnauthorized(error)) onUnauthorized()
        setPreview({ expression: value, status: 'error', message: errorText(error) })
      })
    }, 400)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [value, csrfToken, onUnauthorized])

  const currentPreview = preview?.expression === value ? preview : null
  return <div className='space-y-2 rounded-md border p-3'>
    <div className='flex items-start gap-2'>
      <textarea aria-label={label} className={textareaClass} disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} />
      <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={onRemove}>移除</Button>
    </div>
    <div role='region' aria-label={`${label} 预览`} className='min-h-12 rounded-md bg-muted/30 px-3 py-2'>
      {!value.trim() ? <p className='text-sm text-muted-foreground'>输入公式表达式后自动预览。</p> : null}
      {value.trim() && (!currentPreview || currentPreview.status === 'loading') ? <p className='text-sm text-muted-foreground' role='status'>正在生成公式预览…</p> : null}
      {currentPreview?.status === 'ready' ? <FormulaDisplay value={currentPreview.formula} /> : null}
      {currentPreview?.status === 'error' ? <p className='text-sm text-amber-900' role='alert'>预览失败：{currentPreview.message}。公式原文已保留；修改表达式后可重试。</p> : null}
    </div>
  </div>
}

function LinkEditor({ links, nodes, disabled, onChange }: { links: SolutionQuestion['links']; nodes: SolutionWorkspaceResponse['nodes']; disabled: boolean; onChange: (links: SolutionQuestion['links']) => void }) {
  const [relation, setRelation] = useState<(typeof nodeRelations)[number]['value']>('knowledge')
  const [revisionId, setRevisionId] = useState('')
  const matchingNodes = nodes.filter((node) => node.kind === nodeRelations.find((item) => item.value === relation)?.kind)
  const selectableNodes = matchingNodes.filter((node) => node.selectable !== false)
  useEffect(() => {
    if (!selectableNodes.some((node) => node.revision_id === revisionId)) setRevisionId(selectableNodes[0]?.revision_id || '')
  }, [selectableNodes, revisionId])
  return <section className='space-y-2'>
    <div className='flex flex-wrap items-center justify-between gap-2'><h3 className='text-sm font-semibold'>知识关联</h3><p className='text-xs text-muted-foreground'>明确选择关联类型和版本</p></div>
    <div className='grid gap-2 md:grid-cols-[minmax(9rem,0.6fr)_minmax(12rem,1fr)_auto]'>
      <label className='text-xs font-medium'>关联类型<select className={fieldClass} disabled={disabled} value={relation} onChange={(event) => setRelation(event.target.value as typeof relation)}>{nodeRelations.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label className='text-xs font-medium'>关联条目<select className={fieldClass} disabled={disabled || selectableNodes.length === 0} value={revisionId} onChange={(event) => setRevisionId(event.target.value)}>{selectableNodes.map((item) => <option key={item.revision_id} value={item.revision_id}>{item.label}</option>)}</select></label>
      <Button type='button' className='self-end' size='sm' variant='outline' disabled={disabled || selectableNodes.length === 0} onClick={() => {
        if (revisionId && !links.some((link) => link.revision_id === revisionId && link.relation === relation)) onChange([...links, { revision_id: revisionId, relation }])
      }}>添加关联</Button>
    </div>
    {links.length ? <ul className='space-y-2'>{links.map((link, index) => <li key={`${link.revision_id}:${link.relation}`} className='flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm'><span>{nodeRelations.find((item) => item.value === link.relation)?.label || '其他关联'} · {nodes.find((item) => item.revision_id === link.revision_id)?.label || '历史条目'}</span><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange(links.filter((_, itemIndex) => itemIndex !== index))}>移除</Button></li>)}</ul> : <p className='text-sm text-muted-foreground'>尚未关联。</p>}
    {selectableNodes.length === 0 ? <p className='text-xs text-muted-foreground'>当前没有可新关联的此类已发布条目；可以先保存私人草稿。</p> : null}
  </section>
}

function FigureEditor({ figures, assets, disabled, onChange }: { figures: SolutionQuestion['figures']; assets: SolutionAsset[]; disabled: boolean; onChange: (figures: SolutionQuestion['figures']) => void }) {
  return <section className='space-y-2'>
    <div className='flex items-center justify-between gap-2'><h3 className='text-sm font-semibold'>图示</h3><Button type='button' size='sm' variant='outline' disabled={disabled || assets.length === 0} onClick={() => onChange([...figures, { asset_id: assets[0]?.id || '', role: 'method', caption: '', width_mm: 80 }])}>添加图示</Button></div>
    {figures.map((figure, index) => <fieldset key={index} className='grid gap-2 rounded-md border p-3 md:grid-cols-2'>
      <label className='text-xs font-medium'>图片<select className={fieldClass} disabled={disabled || assets.length === 0} value={figure.asset_id} onChange={(event) => onChange(figures.map((item, itemIndex) => itemIndex === index ? { ...item, asset_id: event.target.value } : item))}>{!assets.some((asset) => asset.id === figure.asset_id) ? <option value={figure.asset_id}>历史图示素材</option> : null}{assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.label} · {asset.kind === 'auxiliary' ? '辅助图' : '原图引用'}</option>)}</select></label>
      <label className='text-xs font-medium'>用途<select className={fieldClass} disabled={disabled} value={figure.role} onChange={(event) => onChange(figures.map((item, itemIndex) => itemIndex === index ? { ...item, role: event.target.value as typeof figure.role } : item))}><option value='question'>题干</option><option value='method'>解法</option><option value='answer'>答案</option></select></label>
      <label className='text-xs font-medium'>图注<input className={fieldClass} maxLength={2000} disabled={disabled} value={figure.caption} onChange={(event) => onChange(figures.map((item, itemIndex) => itemIndex === index ? { ...item, caption: event.target.value } : item))} /></label>
      <label className='text-xs font-medium'>宽度（毫米）<input className={fieldClass} type='number' min={10} max={172} step={1} disabled={disabled} value={figure.width_mm} onChange={(event) => onChange(figures.map((item, itemIndex) => itemIndex === index ? { ...item, width_mm: Number(event.target.value) } : item))} /></label>
      <Button type='button' size='sm' variant='outline' className='md:col-span-2 md:justify-self-end' disabled={disabled} onClick={() => onChange(figures.filter((_, itemIndex) => itemIndex !== index))}>移除图示</Button>
    </fieldset>)}
    {figures.length === 0 ? <p className='text-sm text-muted-foreground'>尚未添加图示。</p> : null}
  </section>
}

function CorrectionEditor({ corrections, disabled, onChange }: { corrections: SolutionQuestion['corrections']; disabled: boolean; onChange: (corrections: SolutionQuestion['corrections']) => void }) {
  const add = () => onChange([...corrections, { kind: 'draft_correction', original: '', replacement: '', basis: '' }])
  return <section className='space-y-2'>
    <div className='flex items-center justify-between gap-2'><h3 className='text-sm font-semibold'>订正记录</h3><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={add}>添加订正</Button></div>
    {corrections.map((correction, index) => <fieldset key={index} className='grid gap-2 rounded-md border p-3 md:grid-cols-2'>
      <label className='text-xs font-medium'>类型<select className={fieldClass} disabled={disabled} value={correction.kind} onChange={(event) => onChange(corrections.map((item, itemIndex) => itemIndex === index ? { ...item, kind: event.target.value as typeof correction.kind } : item))}><option value='printing_error'>资料印刷错误</option><option value='naming'>命名调整</option><option value='draft_correction'>解析草稿订正</option></select></label>
      <div />
      <label className='text-xs font-medium'>原内容<input className={fieldClass} required maxLength={20000} disabled={disabled} value={correction.original} onChange={(event) => onChange(corrections.map((item, itemIndex) => itemIndex === index ? { ...item, original: event.target.value } : item))} /></label>
      <label className='text-xs font-medium'>订正内容<input className={fieldClass} required maxLength={20000} disabled={disabled} value={correction.replacement} onChange={(event) => onChange(corrections.map((item, itemIndex) => itemIndex === index ? { ...item, replacement: event.target.value } : item))} /></label>
      <label className='text-xs font-medium md:col-span-2'>依据<textarea className={textareaClass} required maxLength={20000} disabled={disabled} value={correction.basis} onChange={(event) => onChange(corrections.map((item, itemIndex) => itemIndex === index ? { ...item, basis: event.target.value } : item))} /></label>
      <Button type='button' size='sm' variant='outline' className='md:col-span-2 md:justify-self-end' disabled={disabled} onClick={() => onChange(corrections.filter((_, itemIndex) => itemIndex !== index))}>移除订正</Button>
    </fieldset>)}
    {corrections.length === 0 ? <p className='text-sm text-muted-foreground'>尚未记录订正。</p> : null}
  </section>
}

function AssetUploader({ question, pages, assets, materialId, csrfToken, disabled, onBusyChange, onAssetsChanged, onUnauthorized }: {
  question: Pick<StructuredSolutionQuestion, 'id' | 'sources'>
  pages: SolutionWorkspaceResponse['pages']
  assets: SolutionAsset[]
  materialId: string
  csrfToken: string
  disabled: boolean
  onBusyChange: (busy: boolean) => void
  onAssetsChanged: (assets: SolutionAsset[]) => void
  onUnauthorized: () => void
}) {
  const [kind, setKind] = useState<SolutionAsset['kind']>('auxiliary')
  const [file, setFile] = useState<File | null>(null)
  const [sourceIndex, setSourceIndex] = useState('')
  const [label, setLabel] = useState('')
  const [basis, setBasis] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const uploadKey = useRef<RequestKeyState>(null)
  const questionRef = useRef(question)
  questionRef.current = question
  const selectedSource = sourceIndex === '' ? null : question.sources.find((source) => sourceIdentity(source) === sourceIndex) || null
  const sourcePage = selectedSource ? pages.find((page) => page.id === selectedSource.page_id) : null
  const requiresPage = kind !== 'auxiliary'
  const validSource = kind === 'source_crop' ? Boolean(selectedSource?.region) : kind === 'source_image' ? Boolean(selectedSource && !selectedSource.region) : true
  const canSubmit = !disabled && !busy && Boolean(label.trim() && basis.trim())
    && (requiresPage ? Boolean(sourcePage && validSource) : Boolean(file))

  const submit = async () => {
    if (!canSubmit) return
    setBusy(true)
    onBusyChange(true)
    setError('')
    setNotice('')
    const targetQuestionId = question.id
    const targetSourceId = selectedSource ? sourceIdentity(selectedSource) : null
    try {
      const source: SolutionSource | null = kind === 'auxiliary' ? null : selectedSource
      let result: SolutionWorkspaceResponse
      if (kind !== 'auxiliary' && source) {
        const signature = JSON.stringify([materialId, kind, source, label.trim(), basis.trim()])
        const requestKey = requestKeyFor(uploadKey, signature)
        result = await deriveSolutionAsset(materialId, {
          kind,
          source,
          label: label.trim(),
          basis: basis.trim(),
          request_key: requestKey,
        }, csrfToken)
      } else {
        if (!file) throw new Error('请选择 PNG 辅助图。')
        const signature = JSON.stringify([materialId, kind, file.name, file.size, file.lastModified, label.trim(), basis.trim(), null])
        const requestKey = requestKeyFor(uploadKey, signature)
        const form = new FormData()
        form.append('file', file)
        form.append('kind', 'auxiliary')
        form.append('label', label.trim())
        form.append('basis', basis.trim())
        form.append('source', 'null')
        form.append('request_key', requestKey)
        result = await uploadSolutionAsset(materialId, form, csrfToken)
      }
      uploadKey.current = null
      onAssetsChanged(result.assets)
      setFile(null)
      const targetStillMatches = questionRef.current.id === targetQuestionId
        && (!targetSourceId || questionRef.current.sources.some((source) => sourceIdentity(source) === targetSourceId))
      setNotice(targetStillMatches
        ? '素材已加入本资料素材库；它没有自动关联步骤，请在需要的位置选择。'
        : '素材已加入本资料素材库；题目或来源已变化，没有自动关联。请在仍存在的步骤中选择该素材。')
    } catch (cause) {
      if (cause instanceof Error && 'status' in cause && (cause as { status?: number }).status === 401) onUnauthorized()
      setError(getErrorMessage(cause))
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  return <section className='space-y-2 rounded-lg border border-dashed p-3'>
    <h3 className='text-sm font-semibold'>上传图示素材</h3>
    <p className='text-xs text-muted-foreground'>来源裁切图和整页原图由当前资料原图生成并与原始像素校验；修改过的构图请按辅助图上传并记录依据。素材会先进入资料素材库，不会自动插入或改变解题步骤。</p>
    <div className='grid gap-2 md:grid-cols-2'>
      <label className='text-xs font-medium'>图片类型<select className={fieldClass} disabled={disabled || busy} value={kind} onChange={(event) => { setKind(event.target.value as SolutionAsset['kind']); setError(''); setNotice('') }}><option value='auxiliary'>辅助图（PNG）</option><option value='source_crop'>原图来源裁切</option><option value='source_image'>整张原图</option></select></label>
      {requiresPage ? <label className='text-xs font-medium'>对应原图来源<select className={fieldClass} disabled={disabled || busy || question.sources.length === 0} value={sourceIndex} onChange={(event) => setSourceIndex(event.target.value)}><option value=''>选择本题已记录来源</option>{question.sources.map((source) => <option key={sourceIdentity(source)} value={sourceIdentity(source)}>{pages.find((page) => page.id === source.page_id)?.label || '资料页'} · {source.region ? `区域 ${source.region.join(', ')}` : '整页 / 区域未知'}</option>)}</select></label> : <label className='text-xs font-medium'>PNG 辅助图<input className={fieldClass} type='file' accept='image/png' disabled={disabled || busy} onChange={(event) => { setFile(event.currentTarget.files?.[0] || null); setError(''); setNotice('') }} /></label>}
      <label className='text-xs font-medium'>图示名称<input className={fieldClass} maxLength={160} disabled={disabled || busy} value={label} onChange={(event) => setLabel(event.target.value)} /></label>
      <label className='text-xs font-medium'>依据<input className={fieldClass} maxLength={1000} disabled={disabled || busy} value={basis} onChange={(event) => setBasis(event.target.value)} placeholder='说明用途或来源' /></label>
    </div>
    {kind === 'source_crop' && selectedSource && !selectedSource.region ? <p className='text-xs text-amber-900'>裁切图需要一个已框选的来源区域。</p> : null}
    {kind === 'source_image' && selectedSource?.region ? <p className='text-xs text-amber-900'>整张原图需要选择范围为未知的整页来源。</p> : null}
    <div className='flex flex-wrap items-center gap-2'><Button type='button' size='sm' variant='outline' disabled={!canSubmit} onClick={() => void submit()}>{busy ? '正在验证并上传…' : '上传素材'}</Button>{file ? <span className='text-xs text-muted-foreground'>{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MiB</span> : null}</div>
    {notice ? <p role='status' className='text-xs text-emerald-800'>{notice}</p> : null}{error ? <p role='alert' className='text-xs text-destructive'>{error}</p> : null}
    {assets.length ? <p className='text-xs text-muted-foreground'>当前资料已收存 {assets.length} 张素材。</p> : null}
  </section>
}

function sourceIdentity(source: SolutionSource) {
  return JSON.stringify([source.page_id, source.region])
}
