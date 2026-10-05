import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ChevronLeft, ChevronRight, FilePlus2, RefreshCw, Search } from 'lucide-react'
import { api, getErrorMessage } from '../../api'
import { EmptyState, isUnauthorized, LoadingState, RetryState } from '../../components/shared'
import { HelpTip } from '../../components/help-tip'
import { Disclosure } from '../../components/disclosure'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { Learner, MaterialDetailResponse, MaterialListResponse, Readiness, SkillImport, WorkflowJob } from '../../types'
import { requestKeyFor, type RequestKeyState } from './request-keys'
import { MaterialReadiness } from './readiness'
import { ProposalPicker } from './proposal-picker'
import { WorkflowPanel } from './workflow-panel'
import { ContentWorkspace } from '../content/workspace'
import { MaterialUploadQueue } from './page'
import { usePrivateDraft } from '../drafts/use-private-draft'
import type { PrivateDraft } from '../drafts/client'

type Remote<T> = { status: 'loading' } | { status: 'loaded'; data: T } | { status: 'error'; message: string }
const MATERIAL_PAGE_SIZE = 20

type MaterialTitleDraft = { title: string }
type WorkflowEvidenceScope = 'material_questions' | 'selected_learner_history'
type WorkflowInputDraft = { learnerId: string; evidenceScope: WorkflowEvidenceScope; hasLocalProposal: boolean }

export function MaterialWorkspace({
  householdId,
  householdName,
  csrfToken,
  canWrite,
  learners,
  selectedLearnerId,
  onUnauthorized,
  onOpenSolutions,
  onUnsavedChange,
}: {
  householdId: string
  householdName: string
  csrfToken: string
  canWrite: boolean
  learners: Learner[]
  selectedLearnerId: string
  onUnauthorized: () => void
  onOpenSolutions: (materialId: string) => void
  onUnsavedChange: (hasChanges: boolean) => void
}) {
  const [materials, setMaterials] = useState<Remote<MaterialListResponse>>({ status: 'loading' })
  const [materialsScope, setMaterialsScope] = useState('')
  const [selection, setSelection] = useState({ householdId: '', materialId: '' })
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchPage, setSearchPage] = useState(1)
  const [searchHouseholdId, setSearchHouseholdId] = useState('')
  const [detail, setDetail] = useState<Remote<MaterialDetailResponse>>({ status: 'loading' })
  const [detailMaterialId, setDetailMaterialId] = useState('')
  const [detailHouseholdId, setDetailHouseholdId] = useState('')
  const [detailRefreshError, setDetailRefreshError] = useState('')
  const [listRetry, setListRetry] = useState(0)
  const [detailRetry, setDetailRetry] = useState(0)
  const [createFormHouseholdId, setCreateFormHouseholdId] = useState('')
  const [titleEntry, setTitleEntry] = useState({ householdId: '', value: '' })
  const [titleEdited, setTitleEdited] = useState(false)
  const [titleSavePending, setTitleSavePending] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState('')
  const [uploadQueueBusy, setUploadQueueBusy] = useState(false)
  const [jobId, setJobId] = useState('')
  const [workflowBusy, setWorkflowBusy] = useState(false)
  const [workflowActionBusy, setWorkflowActionBusy] = useState(false)
  const [contentBusy, setContentBusy] = useState(false)
  const [contentOpen, setContentOpen] = useState(false)
  const [contentMounted, setContentMounted] = useState(false)
  const [workflowError, setWorkflowError] = useState('')
  const [workflowNotice, setWorkflowNotice] = useState('')
  const [proposal, setProposal] = useState<SkillImport | null>(null)
  const [createWorkflowOpen, setCreateWorkflowOpen] = useState(false)
  const [learnerId, setLearnerId] = useState(selectedLearnerId)
  const [evidenceScope, setEvidenceScope] = useState<WorkflowEvidenceScope>('material_questions')
  const [workflowEdited, setWorkflowEdited] = useState(false)
  const [workflowSavePending, setWorkflowSavePending] = useState(false)
  const [proposalNeedsReselect, setProposalNeedsReselect] = useState(false)
  const materialCreateKey = useRef<RequestKeyState>(null)
  const workflowCreateKey = useRef<RequestKeyState>(null)
  const workflowDetailsRef = useRef<HTMLDetailsElement>(null)
  const detailSelectionRef = useRef('')
  const title = titleEntry.householdId === householdId ? titleEntry.value : ''
  const createOpen = createFormHouseholdId === householdId
  const selectedMaterialId = selection.householdId === householdId ? selection.materialId : ''
  const visibleSearchInput = searchHouseholdId === householdId ? searchInput : ''
  const materialQuery = searchHouseholdId === householdId ? searchQuery : ''
  const materialPage = searchHouseholdId === householdId ? searchPage : 1
  const materialListKey = JSON.stringify([householdId, materialQuery, materialPage])
  const currentMaterials: Remote<MaterialListResponse> = materialsScope === materialListKey ? materials : { status: 'loading' }
  const currentDetail: Remote<MaterialDetailResponse> = detailMaterialId === selectedMaterialId && detailHouseholdId === householdId && selectedMaterialId
    ? detail
    : { status: 'loading' }
  const titleDraftPayload = useMemo(() => ({ title }), [title])
  const workflowDraftPayload = useMemo(() => ({ learnerId, evidenceScope, hasLocalProposal: Boolean(proposal) || proposalNeedsReselect }), [evidenceScope, learnerId, proposal, proposalNeedsReselect])
  const titleDraft = usePrivateDraft<MaterialTitleDraft>({
    key: 'materials:create-title', householdId, csrfToken, baseStamp: 'material-title:v1',
    enabled: canWrite, dirty: titleEdited, payload: titleDraftPayload, onUnauthorized,
  })
  const workflowDraft = usePrivateDraft<WorkflowInputDraft>({
    key: `materials:workflow:${selectedMaterialId || 'none'}`, householdId, csrfToken,
    baseStamp: `material:${selectedMaterialId || 'none'}`,
    enabled: canWrite && Boolean(selectedMaterialId), dirty: workflowEdited,
    payload: workflowDraftPayload, onUnauthorized,
  })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setMaterials({ status: 'loading' })
    setMaterialsScope(`loading:${materialListKey}`)
    api.materials(householdId, controller.signal, { q: materialQuery, page: materialPage, pageSize: MATERIAL_PAGE_SIZE }).then((data) => {
      if (!active) return
      setMaterialsScope(materialListKey)
      setMaterials({ status: 'loaded', data })
      setSelection((current) => ({
        householdId,
        materialId: current.householdId === householdId && current.materialId && data.items.some((item) => item.id === current.materialId)
          ? current.materialId
          : data.items[0]?.id || '',
      }))
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setMaterialsScope(materialListKey)
      setMaterials({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, listRetry, materialListKey, materialQuery, materialPage, onUnauthorized])

  useEffect(() => {
    setLearnerId(selectedLearnerId)
    setEvidenceScope('material_questions')
    setWorkflowEdited(false)
  }, [selectedLearnerId])

  useEffect(() => {
    if (!selectedMaterialId) {
      detailSelectionRef.current = ''
      setDetail({ status: 'loading' })
      setDetailMaterialId('')
      setDetailHouseholdId('')
      setJobId('')
      setProposal(null)
      setEvidenceScope('material_questions')
      return
    }
    const controller = new AbortController()
    let active = true
    const selectionKey = JSON.stringify([householdId, selectedMaterialId])
    const selectionChanged = detailSelectionRef.current !== selectionKey
    detailSelectionRef.current = selectionKey
    setDetailRefreshError('')
    if (selectionChanged) setDetail({ status: 'loading' })
    setDetailMaterialId(selectedMaterialId)
    setDetailHouseholdId(householdId)
    if (selectionChanged) {
      setJobId('')
      setProposal(null)
      setEvidenceScope('material_questions')
      setProposalNeedsReselect(false)
      setWorkflowEdited(false)
      setWorkflowSavePending(false)
    }
    api.material(selectedMaterialId, controller.signal).then((data) => {
      if (!active) return
      setDetail({ status: 'loaded', data })
      setJobId((current) => !selectionChanged && data.jobs.some((job) => job.id === current) ? current : data.jobs[0]?.id || '')
      if (selectionChanged) setWorkflowNotice(data.jobs[0] ? '当前资料已有整理任务。可以查看任务状态和待核对结果。' : '')
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      if (selectionChanged) setDetail({ status: 'error', message: getErrorMessage(cause) })
      else setDetailRefreshError(getErrorMessage(cause))
    })
    return () => { active = false; controller.abort() }
  }, [householdId, selectedMaterialId, detailRetry, onUnauthorized])

  useEffect(() => {
    setProposal(null)
    setWorkflowError('')
    setCreateWorkflowOpen(false)
    setContentOpen(false)
    setContentMounted(false)
    setContentBusy(false)
    setWorkflowNotice('')
    workflowCreateKey.current = null
  }, [selectedMaterialId])

  const refreshMaterials = () => setListRetry((value) => value + 1)
  const refreshDetail = () => setDetailRetry((value) => value + 1)
  const onJobUpdated = useCallback((job: WorkflowJob, readiness?: Readiness) => {
    setJobId(job.id)
    setDetail((current) => {
      if (current.status !== 'loaded' || current.data.material.id !== job.material_id) return current
      const jobs = [job, ...current.data.jobs.filter((item) => item.id !== job.id)]
        .sort((left, right) => right.created_at.localeCompare(left.created_at))
      return { status: 'loaded', data: { ...current.data, jobs, readiness: readiness || current.data.readiness } }
    })
    setListRetry((value) => value + 1)
  }, [])

  const selectMaterial = (materialId: string, skipUnsavedCheck = false) => {
    if ((!skipUnsavedCheck && scopeBusy) || materialId === selectedMaterialId) return
    if (!skipUnsavedCheck && workflowSavePending && !window.confirm('当前整理任务设置尚未保存。切换资料后这些设置会丢失，仍要切换吗？')) return
    setSelection({ householdId, materialId })
    setDetail({ status: 'loading' })
    setDetailMaterialId('')
    setDetailHouseholdId('')
    setJobId('')
    setProposal(null)
    setProposalNeedsReselect(false)
    setWorkflowEdited(false)
    setWorkflowSavePending(false)
    setWorkflowError('')
    setWorkflowNotice('')
    setCreateWorkflowOpen(false)
    workflowCreateKey.current = null
  }

  const scopeBusy = createBusy || uploadQueueBusy || workflowBusy || workflowActionBusy || contentBusy

  const searchMaterials = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (scopeBusy) return
    if (workflowSavePending && !window.confirm('当前整理任务设置尚未保存。搜索结果可能切换资料并丢失这些设置，仍要搜索吗？')) return
    setSearchHouseholdId(householdId)
    setSearchQuery(visibleSearchInput.trim())
    setSearchPage(1)
  }

  const updateSearchInput = (value: string) => {
    if (scopeBusy) return
    setSearchHouseholdId(householdId)
    setSearchInput(value)
  }

  const changeMaterialPage = (page: number) => {
    if (scopeBusy) return
    if (workflowSavePending && !window.confirm('当前整理任务设置尚未保存。切换资料列表可能丢失这些设置，仍要继续吗？')) return
    setSearchHouseholdId(householdId)
    setSearchPage(page)
  }

  const titleCandidate = titleDraft.candidate && isMaterialTitleDraft(titleDraft.candidate.payload) ? titleDraft.candidate : null
  const titleConflict = titleDraft.conflict && !isMaterialTitleDraft(titleDraft.conflict.payload) ? undefined : titleDraft.conflict
  const invalidTitleDraft = Boolean(titleDraft.candidate && !titleCandidate) || Boolean(titleDraft.conflict && !titleConflict)
  const workflowCandidate = workflowDraft.candidate && isWorkflowInputDraft(workflowDraft.candidate.payload) ? workflowDraft.candidate : null
  const workflowConflict = workflowDraft.conflict && !isWorkflowInputDraft(workflowDraft.conflict.payload) ? undefined : workflowDraft.conflict
  const invalidWorkflowDraft = Boolean(workflowDraft.candidate && !workflowCandidate) || Boolean(workflowDraft.conflict && !workflowConflict)
  const hasTitlePendingDraft = Boolean(titleDraft.candidate) || titleDraft.conflict !== undefined
  const hasWorkflowPendingDraft = Boolean(workflowDraft.candidate) || workflowDraft.conflict !== undefined

  const restoreTitle = (draft: PrivateDraft<MaterialTitleDraft | { cleared: true }>) => {
    if (!isMaterialTitleDraft(draft.payload) || isClearedDraftPayload(draft.payload)) return
    setTitleEntry({ householdId, value: draft.payload.title })
    setTitleEdited(false)
    setCreateFormHouseholdId(householdId)
    titleDraft.accept(draft)
    titleDraft.setMessage('已恢复这份资料名称草稿；创建资料仍需点击“创建资料”。')
  }

  const restoreWorkflow = (draft: PrivateDraft<WorkflowInputDraft | { cleared: true }>) => {
    if (!isWorkflowInputDraft(draft.payload) || isClearedDraftPayload(draft.payload)) return
    setLearnerId(draft.payload.learnerId)
    setEvidenceScope(draft.payload.evidenceScope)
    setProposal(null)
    setProposalNeedsReselect(draft.payload.hasLocalProposal)
    setWorkflowEdited(false)
    setCreateWorkflowOpen(true)
    workflowDraft.accept(draft)
    workflowDraft.setMessage('已恢复任务设置；此前选择的本机文件需要重新选择。')
  }

  useEffect(() => {
    if (titleDraft.message === '私人草稿已保存。' || titleDraft.message === '私人草稿已清理。') {
      setTitleSavePending(false)
      setTitleEdited(false)
    }
  }, [titleDraft.message])

  useEffect(() => {
    if (workflowDraft.message === '私人草稿已保存。' || workflowDraft.message === '私人草稿已清理。') {
      setWorkflowSavePending(false)
      setWorkflowEdited(false)
    }
  }, [workflowDraft.message])

  useEffect(() => {
    onUnsavedChange(titleSavePending || workflowSavePending || createBusy || workflowBusy)
    return () => onUnsavedChange(false)
  }, [createBusy, onUnsavedChange, titleSavePending, workflowBusy, workflowSavePending])

  const createMaterial = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const cleanTitle = title.trim()
    if (!cleanTitle || createBusy || hasTitlePendingDraft) return
    setCreateBusy(true)
    setCreateError('')
    let key: string
    try {
      key = requestKeyFor(materialCreateKey, JSON.stringify([householdId, cleanTitle]))
    } catch (cause) {
      setCreateError(getErrorMessage(cause))
      setCreateBusy(false)
      return
    }
    try {
      const response = await api.createMaterial({ household_id: householdId, title: cleanTitle, request_key: key }, csrfToken)
      materialCreateKey.current = null
      setTitleEntry({ householdId, value: '' })
      setTitleEdited(false)
      setTitleSavePending(false)
      setCreateFormHouseholdId('')
      setSearchHouseholdId(householdId)
      setSearchInput('')
      setSearchQuery('')
      setSearchPage(1)
      selectMaterial(response.material.id, true)
      setListRetry((value) => value + 1)
      void titleDraft.tombstone()
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setCreateError(getErrorMessage(cause))
    } finally {
      setCreateBusy(false)
    }
  }

  const createWorkflow = async () => {
    if (!selectedMaterialId || workflowBusy || hasWorkflowPendingDraft) return
    setWorkflowBusy(true)
    setWorkflowError('')
    let key: string
    try {
      key = requestKeyFor(workflowCreateKey, JSON.stringify({ material: selectedMaterialId, learner: learnerId || null, evidenceScope, proposal }))
    } catch (cause) {
      setWorkflowError(getErrorMessage(cause))
      setWorkflowBusy(false)
      return
    }
    try {
      const response = await api.createWorkflow(selectedMaterialId, {
        request_key: key,
        evidence_scope: evidenceScope,
        ...(learnerId ? { learner_id: learnerId } : {}),
        ...(proposal ? { proposal } : {}),
      }, csrfToken)
      workflowCreateKey.current = null
      setJobId(response.job.id)
      setCreateWorkflowOpen(false)
      setWorkflowNotice('整理任务已创建。下一步请查看当前任务，逐项核对处理结果后再确认。')
      setProposal(null)
      setProposalNeedsReselect(false)
      setWorkflowEdited(false)
      setWorkflowSavePending(false)
      void workflowDraft.tombstone()
      setListRetry((value) => value + 1)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setWorkflowError(getErrorMessage(cause))
    } finally {
      setWorkflowBusy(false)
    }
  }

  const openTaskPanel = () => {
    const section = document.querySelector('.materials-task-disclosure')
    if (section instanceof HTMLDetailsElement) section.open = true
    if (workflowDetailsRef.current) {
      workflowDetailsRef.current.open = true
      workflowDetailsRef.current.scrollIntoView?.({ block: 'start' })
    }
  }

  const selectJob = (selectedJobId: string) => {
    setJobId(selectedJobId)
    openTaskPanel()
  }

  return (
    <div className='space-y-5'>
      <Card>
        <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b pb-4'>
          <div><CardTitle className='text-base'>家庭资料</CardTitle><CardDescription className='mt-1'>{householdName} · 创建资料、逐张上传原图，再按需建立整理任务。</CardDescription></div>
          <div className='flex gap-2'><Button type='button' variant='outline' size='sm' onClick={refreshMaterials}><RefreshCw className='size-4' aria-hidden='true' />刷新资料</Button><Button type='button' size='sm' onClick={() => setCreateFormHouseholdId(createOpen ? '' : householdId)} disabled={!canWrite || scopeBusy}><FilePlus2 className='size-4' aria-hidden='true' />新建资料</Button></div>
        </CardHeader>
        <CardContent className='space-y-4 pt-4'>
          <form className='flex flex-wrap items-end gap-2 rounded-lg border bg-muted/20 p-3' role='search' onSubmit={searchMaterials}>
            <label className='min-w-[min(100%,20rem)] flex-1 text-sm font-medium'>搜索当前家庭的资料 <HelpTip label='资料搜索帮助'>输入资料名称中的几个字，按“搜索”查看匹配资料；翻页会继续在当前家庭的全部资料中查找。</HelpTip><input type='search' disabled={scopeBusy} value={visibleSearchInput} onChange={(event) => updateSearchInput(event.target.value)} placeholder='例如：数学周练' className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' /></label>
            <Button type='submit' variant='outline' disabled={scopeBusy}><Search className='size-4' aria-hidden='true' />搜索</Button>
            {materialQuery ? <Button type='button' variant='ghost' disabled={scopeBusy} onClick={() => { if (workflowSavePending && !window.confirm('当前整理任务设置尚未保存。清除搜索后可能切换资料并丢失这些设置，仍要继续吗？')) return; updateSearchInput(''); setSearchQuery(''); setSearchPage(1) }}>清除搜索</Button> : null}
          </form>
            {currentMaterials.status === 'loading' ? <LoadingState label='正在读取当前家庭的资料…' /> : null}
          {currentMaterials.status === 'error' ? <RetryState message={currentMaterials.message} onRetry={refreshMaterials} title='无法读取资料列表' /> : null}
          {currentMaterials.status === 'loaded' ? <>
            {currentMaterials.data.items.length === 0 ? (materialQuery
              ? <EmptyState title='没有找到匹配的资料' detail='试试更短的关键词，或清除搜索查看全部资料。' icon={Search} />
              : <EmptyState title='这个家庭还没有资料' detail='新建一份资料后，可以从本机逐张上传原始图片。' icon={FilePlus2} />) : (
              <div className='grid gap-2 sm:grid-cols-2 xl:grid-cols-3'>
                {currentMaterials.data.items.map((item) => <button key={item.id} type='button' aria-pressed={selectedMaterialId === item.id} onClick={() => selectMaterial(item.id)} disabled={scopeBusy} className={`rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${selectedMaterialId === item.id ? 'border-primary bg-primary/[0.04] ring-1 ring-primary/30' : 'bg-background hover:bg-muted/40'}`}><span className='flex items-center justify-between gap-2'><span className='truncate font-semibold'>{item.title}</span>{selectedMaterialId === item.id ? <Badge variant='secondary'>当前资料</Badge> : null}</span><span className='mt-2 block text-xs text-muted-foreground'>{item.page_count} 张原图页</span></button>)}
              </div>
            )}
            <div className='flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm text-muted-foreground'>
              <span>共 {currentMaterials.data.total} 份资料 · 第 {currentMaterials.data.page ?? materialPage} 页</span>
              <div className='flex gap-2'>
                <Button type='button' variant='outline' size='sm' disabled={scopeBusy || (currentMaterials.data.page ?? materialPage) <= 1} onClick={() => changeMaterialPage(Math.max(1, materialPage - 1))}><ChevronLeft className='size-4' aria-hidden='true' />上一页</Button>
                <Button type='button' variant='outline' size='sm' disabled={scopeBusy || !(currentMaterials.data.has_next ?? (currentMaterials.data.total > (currentMaterials.data.page ?? materialPage) * (currentMaterials.data.page_size ?? MATERIAL_PAGE_SIZE)))} onClick={() => changeMaterialPage(materialPage + 1)}>下一页<ChevronRight className='size-4' aria-hidden='true' /></Button>
              </div>
            </div>
          </> : null}
          <PrivateDraftRecovery
            title='发现一份未完成的资料名称'
            loadError={titleDraft.loadError}
            message={titleDraft.message}
            candidate={titleCandidate}
            conflict={titleConflict}
            invalidDraft={invalidTitleDraft}
            currentSummary={title || '尚未输入资料名称'}
            savedSummary={(draft) => isClearedDraftPayload(draft.payload) ? '已清理' : isMaterialTitleDraft(draft.payload) ? draft.payload.title || '（空白）' : '无法识别的草稿内容'}
            onRestore={restoreTitle}
            onKeepCurrent={titleDraft.keepCurrent}
            onClearInvalid={titleDraft.keepCurrent}
          />
          {createOpen ? <form className='grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_auto]' onSubmit={(event) => void createMaterial(event)}>
            <label className='text-sm font-medium'>资料名称<input autoFocus required maxLength={200} disabled={scopeBusy || hasTitlePendingDraft} className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={title} onChange={(event) => { const value = event.target.value; setTitleEntry({ householdId, value }); setTitleEdited(true); setTitleSavePending(true) }} /></label>
            <div className='flex items-end'><Button type='submit' disabled={scopeBusy || !title.trim()}>{createBusy ? '正在创建…' : '创建资料'}</Button></div>
            {createError ? <p role='alert' className='text-sm text-destructive sm:col-span-2'>{createError}</p> : null}
            {titleDraft.loadError ? <p role='alert' className='text-sm text-amber-900 sm:col-span-2'>私人草稿暂时无法读取，自动保存已暂停；当前输入会保留在页面中。</p> : null}
            {titleDraft.message ? <p role='status' className='text-sm text-muted-foreground sm:col-span-2'>{titleDraft.message}</p> : null}
          </form> : null}
        </CardContent>
      </Card>

      {selectedMaterialId ? <>
        <Disclosure title='1. 原图' description='逐张上传本机图片；服务器会保留原始文件。' defaultOpen={currentDetail.status === 'loaded' && currentDetail.data.pages.length === 0}>
          <MaterialUploadQueue materialId={selectedMaterialId} csrfToken={csrfToken} canWrite={canWrite} onUnauthorized={onUnauthorized} onBusyChange={setUploadQueueBusy} onUploaded={() => { refreshDetail(); refreshMaterials() }} />
        </Disclosure>

        {currentDetail.status === 'loading' ? <LoadingState label='正在读取资料页、完整度和任务历史…' /> : null}
        {currentDetail.status === 'error' ? <RetryState message={currentDetail.message} onRetry={refreshDetail} title='无法读取资料详情' /> : null}
        {currentDetail.status === 'loaded' ? <>
          {detailRefreshError ? <div role='alert' className='flex flex-wrap items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm'><span>资料暂时无法刷新：{detailRefreshError}。当前输入仍保留。</span><Button type='button' size='sm' variant='outline' onClick={refreshDetail}>重试刷新资料</Button></div> : null}
          <PrivateDraftRecovery
            title='发现一份未完成的整理任务设置'
            loadError={workflowDraft.loadError}
            message={workflowDraft.message}
            candidate={workflowCandidate}
            conflict={workflowConflict}
            invalidDraft={invalidWorkflowDraft}
            currentSummary={`学习者：${learners.find((item) => item.id === learnerId)?.display_name || (learnerId ? '已选学习者' : '未关联学习者')}；历史范围：${evidenceScopeLabel(evidenceScope, Boolean(learnerId))}；本机导入文件：${proposal || proposalNeedsReselect ? '需要重新选择并核对' : '未选择'}`}
            savedSummary={(draft) => summarizeWorkflowDraft(draft, learners)}
            onRestore={restoreWorkflow}
            onKeepCurrent={workflowDraft.keepCurrent}
            onClearInvalid={workflowDraft.keepCurrent}
          />
          {workflowError ? <p role='alert' className='rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950'>{workflowError}</p> : null}
          {workflowNotice ? <div role='status' className='flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-950'><span>{workflowNotice}</span><Button type='button' variant='outline' size='sm' onClick={openTaskPanel}>查看当前任务</Button></div> : null}
          <div key={selectedMaterialId} className='space-y-4'>
            <Disclosure title='2. 题目核对' description='对照原图核对题面、讲义勘误、答案和页面阅读状态。' defaultOpen className='materials-question-disclosure'>
              <div className='space-y-5'>
                <MaterialReadiness detail={currentDetail.data} selectedJobId={jobId} onSelectJob={selectJob} busy={scopeBusy} />
                <div className='flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/20 p-4'><div><h2 className='font-semibold'>同页内容核对</h2><p className='mt-1 text-sm text-muted-foreground'>记录题目内容、讲义勘误和每页阅读状态；收起本区后输入仍会保留。</p></div><Button type='button' variant={contentOpen ? 'secondary' : 'outline'} onClick={() => { setContentOpen(true); setContentMounted(true) }} disabled={scopeBusy}>{contentOpen ? '内容核对已打开' : '打开内容核对'}</Button></div>
                {contentMounted ? <div hidden={!contentOpen}><ContentWorkspace
                  materialId={currentDetail.data.material.id}
                  pages={currentDetail.data.pages}
                  csrfToken={csrfToken}
                  canWrite={canWrite}
                  onUnauthorized={onUnauthorized}
                  onBusyChange={setContentBusy}
                  onClose={() => setContentOpen(false)}
                /></div> : null}
              </div>
            </Disclosure>

            <Disclosure title='3. 讲解' description='为题目整理讲解、生成文件并查看讲解历史。'>
              <Card><CardContent className='flex flex-wrap items-center justify-between gap-3 p-4'><div><h2 className='font-semibold'>逐题解析与文档</h2><p className='mt-1 text-sm text-muted-foreground'>整理独立解析版本，并检查生成文件。</p></div><Button type='button' onClick={() => onOpenSolutions(selectedMaterialId)}>整理解析</Button></CardContent></Card>
            </Disclosure>

            <Disclosure title='4. 整理任务' description='选择学习者和作答记录范围，可选导入交换包，再创建并核对任务。' className='materials-task-disclosure'>
              {canWrite ? <ProposalPicker key={selectedMaterialId} pages={currentDetail.data.pages} value={proposal} onChange={(value) => { setProposal(value); setProposalNeedsReselect(false); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }} /> : <p className='rounded-md border bg-muted/20 p-4 text-sm text-muted-foreground'>当前为只读成员，可以查看原图、任务和输出；内容修改由家庭所有者或审核成员操作。</p>}
              {!createWorkflowOpen && canWrite ? <Button type='button' className='mt-4' onClick={() => setCreateWorkflowOpen(true)} disabled={scopeBusy || hasWorkflowPendingDraft}>新建整理任务</Button> : null}
              {createWorkflowOpen ? <Card className='mt-4'><CardHeader><CardTitle className='text-base'>新建资料整理任务</CardTitle><CardDescription>先选择整理范围，再创建任务。创建后不会自动处理或确认内容，家长仍需逐项核对。</CardDescription></CardHeader><CardContent className='space-y-4'>
                <ol className='grid gap-2 text-sm sm:grid-cols-3' aria-label='整理任务步骤'><li className='rounded-md border bg-muted/20 p-3'><span className='font-semibold'>1. 选择范围</span><span className='mt-1 block text-muted-foreground'>可指定学习者，也可不关联。</span></li><li className='rounded-md border bg-muted/20 p-3'><span className='font-semibold'>2. 补充资料</span><span className='mt-1 block text-muted-foreground'>已有内容可直接整理；额外文件需重新选择。</span></li><li className='rounded-md border bg-muted/20 p-3'><span className='font-semibold'>3. 创建并核对</span><span className='mt-1 block text-muted-foreground'>创建后由家长检查，再决定是否确认。</span></li></ol>
                {learners.length ? <label className='block max-w-md text-sm font-medium'>学习者（可选）<select disabled={scopeBusy || hasWorkflowPendingDraft} className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={learnerId} onChange={(event) => { setLearnerId(event.target.value); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }}><option value=''>不关联学习者</option>{learners.map((learner) => <option key={learner.id} value={learner.id}>{learner.display_name}{learner.grade ? ` · ${learner.grade}` : ''}</option>)}</select></label> : <p className='text-sm text-muted-foreground'>此任务不必关联学习者；可稍后从家庭设置中管理学习者。</p>}
                <fieldset disabled={scopeBusy || hasWorkflowPendingDraft} className='space-y-2 rounded-md border p-3'><legend className='flex items-center gap-1 px-1 text-sm font-medium'>整理哪些作答记录<HelpTip label='作答记录范围帮助'>选择“本资料题目”会整理当前资料关联题目的历次作答；选择“所选学习者”会包含这名学习者在其他资料中的记录。未选择学习者时不会关联个人历史。</HelpTip></legend>
                  <label className='flex items-start gap-2 text-sm'><input type='radio' name='evidence-scope' value='material_questions' checked={evidenceScope === 'material_questions'} onChange={() => { setEvidenceScope('material_questions'); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }} /><span><span className='font-medium'>本资料题目的全部作答记录</span><span className='mt-0.5 block text-xs text-muted-foreground'>默认选项，只看当前资料中题目的历次作答。</span></span></label>
                  <label className='flex items-start gap-2 text-sm'><input type='radio' name='evidence-scope' value='selected_learner_history' checked={evidenceScope === 'selected_learner_history'} onChange={() => { setEvidenceScope('selected_learner_history'); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }} /><span><span className='font-medium'>所选学习者的全部历史记录</span><span className='mt-0.5 block text-xs text-muted-foreground'>{learnerId ? '包括这名学习者在其他资料中的作答。' : '尚未选择学习者，创建后会列出待测项目，不会关联个人历史。'}</span></span></label>
                </fieldset>
                {proposalNeedsReselect ? <p role='status' className='rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950'>已恢复其他任务设置。此前选择的本机文件没有随草稿保存，请重新选择并核对后再创建。</p> : null}
                {workflowDraft.message ? <p role='status' className='text-sm text-muted-foreground'>{workflowDraft.message}</p> : null}
                <div className='flex flex-wrap gap-2'><Button type='button' onClick={() => void createWorkflow()} disabled={scopeBusy || hasWorkflowPendingDraft || Boolean(proposalNeedsReselect)}>{workflowBusy ? '正在创建…' : '创建并查看任务'}</Button><Button type='button' variant='outline' onClick={() => setCreateWorkflowOpen(false)} disabled={scopeBusy}>返回资料</Button></div>
              </CardContent></Card> : null}
              {jobId ? <details ref={workflowDetailsRef} className='mt-4 rounded-lg border bg-background'><summary className='cursor-pointer px-4 py-3 font-semibold'>当前任务：查看处理阶段、结果和历史操作</summary><div className='border-t p-4'><WorkflowPanel key={`${selectedMaterialId}:${jobId}`} jobId={jobId} csrfToken={csrfToken} canWrite={canWrite} pages={currentDetail.data.pages} onUnauthorized={onUnauthorized} onJobUpdated={onJobUpdated} onBusyChange={setWorkflowActionBusy} onOpenContent={() => { setContentOpen(true); setContentMounted(true); const section = document.querySelector('.materials-question-disclosure'); if (section instanceof HTMLDetailsElement) section.open = true }} /></div></details> : null}
            </Disclosure>
          </div>
        </> : null}
      </> : currentMaterials.status === 'loaded' && currentMaterials.data.items.length === 0 ? <p className='sr-only'>新建资料后可以继续。</p> : null}
    </div>
  )
}

function PrivateDraftRecovery<T>({
  title,
  loadError,
  message,
  candidate,
  conflict,
  invalidDraft,
  currentSummary,
  savedSummary,
  onRestore,
  onKeepCurrent,
  onClearInvalid,
}: {
  title: string
  loadError: string
  message: string
  candidate: PrivateDraft<T | { cleared: true }> | null
  conflict: PrivateDraft<T | { cleared: true }> | null | undefined
  invalidDraft: boolean
  currentSummary: string
  savedSummary: (draft: PrivateDraft<T | { cleared: true }>) => string
  onRestore: (draft: PrivateDraft<T | { cleared: true }>) => void
  onKeepCurrent: () => void
  onClearInvalid: () => void
}) {
  const hasConflict = conflict !== undefined
  const pendingDraft = hasConflict ? conflict : candidate
  if (!loadError && !message && !pendingDraft && !hasConflict && !candidate && !invalidDraft) return null
  return <section className='space-y-3 rounded-lg border border-sky-200 bg-sky-50/60 p-4' aria-label='私人草稿'>
    {loadError ? <div role='alert' className='text-sm text-amber-950'><p>私人草稿暂时无法读取，自动保存已暂停；当前页面的输入仍保留。</p><details className='mt-1'><summary className='cursor-pointer text-xs'>诊断详情</summary><p className='mt-1 break-words'>{loadError}</p></details></div> : null}
    {invalidDraft ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm text-amber-950'><span>这份私人草稿格式无法识别，当前内容没有被替换。</span><Button type='button' size='sm' variant='outline' onClick={onClearInvalid}>清理不可恢复草稿</Button></div> : null}
    {hasConflict || candidate ? <>
      <div><h3 className='font-semibold'>{hasConflict ? '另一窗口也修改了这项内容' : title}</h3><p className='mt-1 text-sm text-muted-foreground'>请先比较两边内容，再选择恢复草稿或保留当前输入；系统不会替你覆盖。</p></div>
      <dl className='grid gap-3 sm:grid-cols-2'>
        <div className='rounded-md border bg-background p-3'><dt className='text-xs font-medium text-muted-foreground'>当前页面</dt><dd className='mt-1 whitespace-pre-wrap break-words text-sm'>{currentSummary}</dd></div>
        <div className='rounded-md border bg-background p-3'><dt className='text-xs font-medium text-muted-foreground'>已保存内容</dt><dd className='mt-1 whitespace-pre-wrap break-words text-sm'>{pendingDraft ? savedSummary(pendingDraft) : '另一窗口已清理草稿'}</dd></div>
      </dl>
      <div className='flex flex-wrap gap-2'>
        <Button type='button' size='sm' onClick={() => pendingDraft && !isClearedDraftPayload(pendingDraft.payload) && onRestore(pendingDraft)} disabled={!pendingDraft || isClearedDraftPayload(pendingDraft.payload)}>{pendingDraft && isClearedDraftPayload(pendingDraft.payload) ? '草稿已清理' : hasConflict ? '恢复另一窗口内容' : '恢复这份草稿'}</Button>
        <Button type='button' size='sm' variant='outline' onClick={onKeepCurrent}>保留当前内容</Button>
      </div>
    </> : null}
    {!pendingDraft && message ? <p role='status' className='text-sm text-muted-foreground'>{message}</p> : null}
  </section>
}

function evidenceScopeLabel(scope: WorkflowEvidenceScope, hasLearner: boolean) {
  if (scope === 'material_questions') return '本资料题目的全部作答记录'
  return hasLearner ? '所选学习者的全部历史记录' : '待测项目清单'
}

function isClearedDraftPayload(value: unknown): value is { cleared: true } {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) && 'cleared' in value && value.cleared === true)
}

function isMaterialTitleDraft(value: unknown): value is MaterialTitleDraft | { cleared: true } {
  if (isClearedDraftPayload(value)) return true
  if (!value || typeof value !== 'object' || Array.isArray(value) || 'cleared' in value) return false
  const draft = value as Record<string, unknown>
  return typeof draft.title === 'string' && draft.title.length <= 200
}

function isWorkflowInputDraft(value: unknown): value is WorkflowInputDraft | { cleared: true } {
  if (isClearedDraftPayload(value)) return true
  if (!value || typeof value !== 'object' || Array.isArray(value) || 'cleared' in value) return false
  const draft = value as Record<string, unknown>
  return typeof draft.learnerId === 'string' && draft.learnerId.length <= 200
    && (draft.evidenceScope === 'material_questions' || draft.evidenceScope === 'selected_learner_history')
    && typeof draft.hasLocalProposal === 'boolean'
}

function summarizeWorkflowDraft(draft: PrivateDraft<WorkflowInputDraft | { cleared: true }>, learners: Learner[]) {
  const payload = draft.payload
  if (isClearedDraftPayload(payload)) return '已清理'
  if (!isWorkflowInputDraft(payload)) return '无法识别的草稿内容'
  const learner = learners.find((item) => item.id === payload.learnerId)?.display_name
    || (payload.learnerId ? '需要重新选择学习者' : '未关联学习者')
  const proposal = payload.hasLocalProposal ? '需要重新选择并核对' : '未选择'
  return `学习者：${learner}；历史范围：${evidenceScopeLabel(payload.evidenceScope, Boolean(payload.learnerId))}；本机导入文件：${proposal}`
}
