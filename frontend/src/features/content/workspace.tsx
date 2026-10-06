import { useEffect, useRef, useState } from 'react'
import { WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import { BookOpenCheck, FileCheck2 } from 'lucide-react'
import { api } from '../../api'
import { ApiLink, EmptyState, errorText, isUnauthorized, LoadingState, RetryState, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { MaterialContentResponse, MaterialPage } from '../../types'
import { QuestionEditor, type QuestionFocusTarget } from './question-editor'
import { PageReading } from './page-reading'

export function ContentWorkspace({
  materialId,
  pages,
  csrfToken,
  canWrite,
  onUnauthorized,
  onBusyChange,
  onUnsavedChange,
  refreshSignal = 0,
  onClose,
}: {
  materialId: string
  pages: MaterialPage[]
  csrfToken: string
  canWrite: boolean
  onUnauthorized: () => void
  onBusyChange: (busy: boolean) => void
  onUnsavedChange?: (dirty: boolean) => void
  refreshSignal?: number
  onClose: () => void
}) {
  const [content, setContent] = useState<Remote<MaterialContentResponse>>({ status: 'loading' })
  const [refreshError, setRefreshError] = useState('')
  const [selectedQuestionId, setSelectedQuestionId] = useState('')
  const selectedQuestionRef = useRef(selectedQuestionId)
  selectedQuestionRef.current = selectedQuestionId
  const [selectedPageId, setSelectedPageId] = useState(pages[0]?.id || '')
  const [editorEpoch, setEditorEpoch] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [notice, setNotice] = useState('')
  const [editingTab, setEditingTab] = useState('question')
  const [focusRequest, setFocusRequest] = useState<{ target: QuestionFocusTarget; sequence: number } | null>(null)
  const [writing, setWriting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [unsaved, setUnsaved] = useState({ question: false, erratum: false, reading: false })
  const previousRefreshSignal = useRef(refreshSignal)
  const continuedRef = useRef(false)
  const focusSequence = useRef(0)
  const hasLoadedContent = useRef(false)
  const hasUnsaved = unsaved.question || unsaved.erratum || unsaved.reading

  const handleBusyChange = (busy: boolean) => {
    setWriting(busy)
    onBusyChange(busy)
  }

  useEffect(() => {
    onUnsavedChange?.(hasUnsaved)
  }, [hasUnsaved, onUnsavedChange])

  useEffect(() => () => onUnsavedChange?.(false), [onUnsavedChange])

  const updateUnsaved = (scope: keyof typeof unsaved, dirty: boolean) => {
    setUnsaved((current) => current[scope] === dirty ? current : { ...current, [scope]: dirty })
  }

  const requestRefresh = () => {
    if (hasUnsaved && !window.confirm('题面、答案或整页阅读记录还有未保存输入。刷新会丢弃这些输入，仍要继续吗？')) return
    setUnsaved({ question: false, erratum: false, reading: false })
    setFocusRequest(null)
    setNotice('')
    setRefreshError('')
    hasLoadedContent.current = false
    setRefreshing(true)
    setContent({ status: 'loading' })
    setRefresh((value) => value + 1)
  }

  useEffect(() => {
    if (previousRefreshSignal.current === refreshSignal) return
    previousRefreshSignal.current = refreshSignal
    setUnsaved({ question: false, erratum: false, reading: false })
    setFocusRequest(null)
    setNotice('')
    setRefreshError('')
    hasLoadedContent.current = false
    setRefreshing(true)
    setContent({ status: 'loading' })
    setRefresh((value) => value + 1)
  }, [refreshSignal])

  const selectQuestion = (questionId: string) => {
    if (questionId === selectedQuestionId || refreshing) return
    if ((unsaved.question || unsaved.erratum) && !window.confirm('当前题面、来源或讲义勘误还有未保存输入。切换题目会丢弃这些输入，仍要继续吗？')) return
    if (unsaved.question) updateUnsaved('question', false)
    if (unsaved.erratum) updateUnsaved('erratum', false)
    setFocusRequest(null)
    setSelectedQuestionId(questionId)
    setNotice('')
  }

  const selectPage = (pageId: string) => {
    if (pageId === selectedPageId) return true
    const questionUnsaved = unsaved.question || unsaved.erratum
    if ((unsaved.reading || questionUnsaved) && !window.confirm('当前内容核对或整页阅读有未保存输入。切换来源页会重置选区或阅读状态，仍要继续吗？')) return false
    if (unsaved.reading) updateUnsaved('reading', false)
    setSelectedPageId(pageId)
    return true
  }

  const retryContentLoad = () => {
    if (unsaved.question || unsaved.erratum) {
      if (!window.confirm('题面或讲义勘误还有未保存输入。重试会更新题目内容并可能重置这些输入，仍要继续吗？')) return
      if (unsaved.question) updateUnsaved('question', false)
      if (unsaved.erratum) updateUnsaved('erratum', false)
      setEditorEpoch((value) => value + 1)
    }
    setFocusRequest(null)
    setRefreshError('')
    setRefreshing(true)
    setRefresh((value) => value + 1)
  }

  useEffect(() => {
    if (!pages.some((page) => page.id === selectedPageId)) setSelectedPageId(pages[0]?.id || '')
  }, [pages, selectedPageId])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRefreshing(true)
    api.materialContent(materialId, controller.signal).then((data) => {
      if (!active) return
      hasLoadedContent.current = true
      setRefreshError('')
      setRefreshing(false)
      setContent({ status: 'loaded', data })
      if (!data.questions.some((question) => question.id === selectedQuestionRef.current)) {
        const next = continuedRef.current ? undefined : data.questions.find((question) => !question.confirmed)
        continuedRef.current = true
        setSelectedQuestionId(next?.id || '')
        if (next) setSelectedPageId(next.sources.find((source) => pages.some((page) => page.id === source.page_id))?.page_id || pages[0]?.id || '')
      }
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRefreshing(false)
      if (hasLoadedContent.current) setRefreshError(errorText(cause))
      else setContent({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [materialId, refresh, onUnauthorized])

  const current = content.status === 'loaded'
    ? content.data.questions.find((question) => question.id === selectedQuestionId)
    : undefined
  const selectedPage = pages.find((page) => page.id === selectedPageId)
  const questionReview = current ? reviewQuestionContent(current) : undefined

  const focusQuestionTarget = (target: QuestionFocusTarget) => {
    if (!canWrite || writing || refreshing || !selectedPage || !current) return
    if (target === 'source-region') {
      const sourcePageId = current.sources.find((source) => pages.some((page) => page.id === source.page_id))?.page_id
      if (sourcePageId && !selectPage(sourcePageId)) return
    }
    setEditingTab('question')
    setFocusRequest({ target, sequence: ++focusSequence.current })
  }

  return (
    <Card className='gap-0 border-primary/25 py-0 shadow-sm'>
      <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b py-4'>
        <div>
          <CardTitle className='flex items-center gap-2 text-base'><BookOpenCheck className='size-4 text-primary' aria-hidden='true' />同页内容核对</CardTitle>
          <CardDescription className='mt-1'>对照原图选区，人工核对题面转写、可选家长答案及知识关联；讲义印刷错误使用独立勘误记录。</CardDescription>
        </div>
        <Button type='button' variant='outline' size='sm' onClick={onClose} disabled={writing}>返回原图与进度</Button>
      </CardHeader>

      <CardContent className='space-y-5 px-5 py-5'>
        <div className='flex flex-wrap items-center gap-3'>
          <Badge variant={canWrite ? 'secondary' : 'outline'}>{canWrite ? '可核对和保存' : '只读查看'}</Badge>
          {content.status === 'loaded' ? <p className='text-xs text-muted-foreground'>现有知识／方法／题型条目 {content.data.nodes.length} 项</p> : null}
          <Button type='button' variant='ghost' size='sm' onClick={requestRefresh} disabled={writing || refreshing}>刷新核对数据</Button>
        </div>
        {notice ? <p role='status' className='rounded-md border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900'>{notice}</p> : null}
        {content.status === 'loaded' && refreshing ? <p role='status' className='text-sm text-muted-foreground'>正在更新题目和来源；整页阅读输入仍可继续编辑。</p> : null}
        {content.status === 'loading' ? <LoadingState label='正在读取已确认题目和来源…' /> : null}
        {content.status === 'error' ? <RetryState message={content.message} onRetry={requestRefresh} /> : null}
        {content.status === 'loaded' && refreshError ? <div role='alert' className='flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100'><span>无法更新题目和来源，当前输入仍保留。{refreshError}</span><Button type='button' size='sm' variant='outline' onClick={retryContentLoad}>重试更新</Button></div> : null}
        {content.status === 'loaded' ? (
          <>
            <section className='space-y-3'>
              {!selectedQuestionId ? <p className='text-sm text-muted-foreground'>当前没有选中的待补题，可选择已有题目或新建草稿。</p> : null}
              <Button type='button' variant='outline' size='sm' disabled={writing || refreshing} onClick={() => selectQuestion('')}>＋ 新建题目草稿</Button>
              <div className='sticky top-16 z-20 grid gap-3 rounded-md border bg-background p-3 sm:grid-cols-[minmax(15rem,1fr)_minmax(13rem,0.7fr)]'>
                <label className='text-sm font-medium'>正在核对的题目
                  <select className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={selectedQuestionId} onChange={(event) => selectQuestion(event.target.value)} disabled={writing || refreshing}>
                    <option value=''>新建题目草稿</option>
                    {content.data.questions.map((question) => <option key={question.id} value={question.id}>{question.number ? `第 ${question.number} 题` : '未编号题目'} · {question.printed_text || '题干待补'}</option>)}
                  </select>
                </label>
                <label className='text-sm font-medium'>来源页
                  <select className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={selectedPageId} onChange={(event) => selectPage(event.target.value)} disabled={pages.length === 0 || writing}>
                    {pages.map((page) => <option key={page.id} value={page.id}>资料页 {page.position}</option>)}
                    {pages.length === 0 ? <option value=''>暂无资料页</option> : null}
                  </select>
                </label>
              </div>
              {content.data.nodes.length ? (
                <div className='flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg bg-muted/25 px-4 py-3 text-sm'>
                  <span className='font-medium'>本资料已有条目</span>
                  {content.data.nodes.map((node) => <ApiLink key={`${node.kind}:${node.id}`} href={node.node_url}>{node.label || nodeKindLabel(node.kind)}</ApiLink>)}
                </div>
              ) : null}
              {current && questionReview ? (
                <section className='space-y-3 rounded-lg border border-amber-300 bg-amber-50/50 p-4 dark:border-amber-800 dark:bg-amber-950/25' aria-labelledby='content-question-readiness-title'>
                  <div>
                    <h3 id='content-question-readiness-title' className='font-semibold'>当前题目待补项定位</h3>
                    <p className='mt-1 text-xs leading-5 text-muted-foreground'>定位只会切换到对应编辑项并聚焦，不会填写、勾选、保存或确认内容。</p>
                  </div>
                  {questionReview.gaps.length ? (
                    <ul className='space-y-2'>
                      {questionReview.gaps.map((gap) => (
                        <li key={gap.key} className='flex flex-wrap items-start justify-between gap-3 rounded-md border bg-background px-3 py-2 text-sm'>
                          <div className='min-w-0 flex-1'>
                            <p className='font-medium'>{gap.statusLabel || '待补'}：{gap.label}</p>
                            {gap.detail ? <p className='mt-1 text-xs leading-5 text-muted-foreground'>{gap.detail}</p> : null}
                          </div>
                          {gap.target && canWrite && selectedPage ? (
                            <Button type='button' size='sm' variant='outline' data-ux-target={`content-gap-${gap.target}`} aria-label={`去补充：${gap.label}`} disabled={writing || refreshing} onClick={() => focusQuestionTarget(gap.target!)}>去补充</Button>
                          ) : gap.target ? <span className='text-xs text-muted-foreground'>{!canWrite ? '当前为只读查看' : '请先上传原图页后再定位编辑项'}</span>
                            : <span className='text-xs text-muted-foreground'>无对应跳转；保留待核对状态。</span>}
                          {gap.rawCode ? <details className='basis-full text-xs text-muted-foreground'><summary className='w-fit cursor-pointer'>查看缺项记录</summary><code className='mt-1 inline-block'>{gap.rawCode}</code></details> : null}
                        </li>
                      ))}
                    </ul>
                  ) : <p className='text-sm text-muted-foreground'>当前没有题面或来源待补项，仍请完成下方人工确认。</p>}
                  <div className='rounded-md border bg-background px-3 py-3 text-sm'>
                    <h4 className='font-medium'>独立练习基础条件</h4>
                    <ul className='mt-2 space-y-1 text-xs leading-5'>
                      <li>{questionReview.textReady ? '已具备' : '待补'}：可用于练习的题面文本已记录</li>
                      <li>{questionReview.reportedFieldsReady ? '已具备' : '待补'}：已标注的内容缺项已清除</li>
                      <li>{questionReview.sourcesReady ? '已具备' : '待补'}：原图来源区域就绪</li>
                      <li>{current.confirmed ? '已具备' : '待补'}：题目已人工确认</li>
                    </ul>
                    <p className='mt-2 text-xs text-muted-foreground'>独立练习不要求家长答案；生成时还会检查图片内容安全等条件。</p>
                  </div>
                </section>
              ) : null}
            </section>

            {pages.length === 0 || !selectedPage ? (
              <EmptyState title='资料还没有原图页' detail='上传原图后，可以在这里按原图像素选择题面来源。' icon={FileCheck2} />
            ) : (
              <div className='space-y-5'>
                <WorkspaceTabs id='content-editing' label='内容整理方式' tabs={[{ value: 'question', label: '逐题核对' }, { value: 'reading', label: '整页阅读' }]} value={editingTab} onChange={setEditingTab} />
                <WorkspacePanel id='content-editing' value='question' active={editingTab}>
                <QuestionEditor
                  key={`${selectedQuestionId || 'new'}:${current?.revision_id || 'draft'}:${content.data.context.source_stamp}:${editorEpoch}`}
                  materialId={materialId}
                  context={content.data.context}
                  pages={pages}
                  selectedPage={selectedPage}
                  question={current}
                  focusRequest={focusRequest}
                  canWrite={canWrite}
                  workspaceBusy={writing || refreshing}
                  csrfToken={csrfToken}
                  onUnauthorized={onUnauthorized}
                  onBusyChange={handleBusyChange}
                  onUnsavedChange={(dirty) => updateUnsaved('question', dirty)}
                  onErratumUnsavedChange={(dirty) => updateUnsaved('erratum', dirty)}
                  onSaved={(questionId, message) => {
                    setFocusRequest(null)
                    setSelectedQuestionId(questionId)
                    setNotice(message)
                    setRefreshError('')
                    setRefreshing(true)
                    setRefresh((value) => value + 1)
                  }}
                />
                </WorkspacePanel>
                <WorkspacePanel id='content-editing' value='reading' active={editingTab}>
                <PageReading
                  key={selectedPage.id}
                  page={selectedPage}
                  csrfToken={csrfToken}
                  canWrite={canWrite}
                  workspaceBusy={writing}
                  onUnauthorized={onUnauthorized}
                  onBusyChange={handleBusyChange}
                  onUnsavedChange={(dirty) => updateUnsaved('reading', dirty)}
                />
                </WorkspacePanel>
              </div>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function nodeKindLabel(kind: string) {
  return kind === 'knowledge' ? '知识点' : kind === 'method' ? '方法' : '题型'
}

type QuestionGap = {
  key: string
  label: string
  detail?: string
  target?: QuestionFocusTarget
  rawCode?: string
  statusLabel?: '待补' | '待核对'
}

function reviewQuestionContent(question: NonNullable<MaterialContentResponse['questions'][number]>) {
  const reportedMissing = (Array.isArray(question.missing_fields) ? question.missing_fields : [])
    .filter((field): field is string => typeof field === 'string' && Boolean(field.trim()))
    .map((field) => field.trim())
  const missing = new Set(reportedMissing)
  const printedTextReady = Boolean(question.printed_text.trim())
  const workingTextReady = Boolean(question.working_text.trim())
  if (!printedTextReady && !workingTextReady && !missing.has('printed_text') && !missing.has('working_text')) missing.add('printed_text')

  const sourceCodes = new Set(['evidence', 'source', 'source_region', 'region', 'region_id', 'region_revision_id'])
  const hasSourceGap = [...missing].some((field) => sourceCodes.has(field))
  const sourcesReady = question.sources.length > 0 && question.sources_ready !== false && !hasSourceGap
  const gaps: QuestionGap[] = []
  let sourceGapListed = false
  for (const field of missing) {
    if (sourceCodes.has(field)) {
      if (!sourceGapListed) {
        gaps.push({ key: 'source-region', label: '原图来源区域', detail: '该题没有可用来源区域，或来源信息不完整。请在正确资料页原图上框选并确认加入；定位不会代替这一步。', target: 'source-region' })
        sourceGapListed = true
      }
    } else if (field === 'printed_text') {
      gaps.push({ key: field, label: '图中印刷题面转写', detail: '按原图核对后填写；看不清的部分应保留未知并说明。', target: 'printed-text' })
    } else if (field === 'working_text') {
      gaps.push({
        key: field,
        label: '当前工作题干字段',
        detail: printedTextReady || workingTextReady
          ? '当前已有可用于练习的题面文本；不要求再录一份重复题干。此项已标注缺失，但本页没有独立工作题干输入，暂不提供会改写原文的跳转。'
          : '当前没有可用题面文本；请先按原图补录印刷题面，保存新修订时会生成当前工作题干。',
        target: printedTextReady || workingTextReady ? undefined : 'printed-text',
        statusLabel: printedTextReady || workingTextReady ? '待核对' : undefined,
      })
    } else {
      gaps.push({ key: `unknown:${field}`, label: '其他内容待核对', detail: '有一项缺项暂无法对应到本页的具体控件；该状态会保留。', rawCode: field, statusLabel: '待核对' })
    }
  }
  if (!sourcesReady && !sourceGapListed) {
    gaps.push({ key: 'source-region', label: '原图来源区域', detail: '来源区域尚未就绪。请在正确资料页原图上框选并确认加入；定位不会代替这一步。', target: 'source-region' })
  }
  if (!question.confirmed) {
    gaps.push({ key: 'confirmation', label: '人工核对与确认', detail: '定位到人工核对框后，请自行核对并勾选；本操作不会替你确认或保存。', target: 'confirmation' })
  }

  return {
    gaps,
    textReady: printedTextReady || workingTextReady,
    reportedFieldsReady: reportedMissing.length === 0,
    sourcesReady,
  }
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
