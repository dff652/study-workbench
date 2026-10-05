import { useEffect, useRef, useState } from 'react'
import { WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import { BookOpenCheck, FileCheck2 } from 'lucide-react'
import { api } from '../../api'
import { ApiLink, EmptyState, errorText, isUnauthorized, LoadingState, RetryState, type Remote } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { MaterialContentResponse, MaterialPage } from '../../types'
import { QuestionEditor } from './question-editor'
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
  const [selectedPageId, setSelectedPageId] = useState(pages[0]?.id || '')
  const [editorEpoch, setEditorEpoch] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [notice, setNotice] = useState('')
  const [editingTab, setEditingTab] = useState('question')
  const [writing, setWriting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [unsaved, setUnsaved] = useState({ question: false, erratum: false, reading: false })
  const previousRefreshSignal = useRef(refreshSignal)
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
    setSelectedQuestionId(questionId)
    setNotice('')
  }

  const selectPage = (pageId: string) => {
    if (pageId === selectedPageId) return
    const questionUnsaved = unsaved.question || unsaved.erratum
    if ((unsaved.reading || questionUnsaved) && !window.confirm('当前内容核对或整页阅读有未保存输入。切换来源页会重置选区或阅读状态，仍要继续吗？')) return
    if (unsaved.reading) updateUnsaved('reading', false)
    setSelectedPageId(pageId)
  }

  const retryContentLoad = () => {
    if (unsaved.question || unsaved.erratum) {
      if (!window.confirm('题面或讲义勘误还有未保存输入。重试会更新题目内容并可能重置这些输入，仍要继续吗？')) return
      if (unsaved.question) updateUnsaved('question', false)
      if (unsaved.erratum) updateUnsaved('erratum', false)
      setEditorEpoch((value) => value + 1)
    }
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
      setSelectedQuestionId((current) => data.questions.some((question) => question.id === current) ? current : '')
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
                  canWrite={canWrite}
                  workspaceBusy={writing || refreshing}
                  csrfToken={csrfToken}
                  onUnauthorized={onUnauthorized}
                  onBusyChange={handleBusyChange}
                  onUnsavedChange={(dirty) => updateUnsaved('question', dirty)}
                  onErratumUnsavedChange={(dirty) => updateUnsaved('erratum', dirty)}
                  onSaved={(questionId, message) => {
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

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
