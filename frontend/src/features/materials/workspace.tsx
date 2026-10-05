import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ChevronLeft, ChevronRight, FilePlus2, RefreshCw, Search } from 'lucide-react'
import { api, getErrorMessage } from '../../api'
import { EmptyState, isUnauthorized, LoadingState, RetryState } from '../../components/shared'
import { HelpTip } from '../../components/help-tip'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { WorkspaceHeading, WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import type { Learner, MaterialDetailResponse, MaterialListResponse, Readiness, SkillImport, WorkflowJob } from '../../types'
import { requestKeyFor, type RequestKeyState } from './request-keys'
import { MaterialReadiness, MaterialTaskHistory } from './readiness'
import { ProposalPicker } from './proposal-picker'
import { WorkflowPanel } from './workflow-panel'
import { ContentWorkspace } from '../content/workspace'
import { MaterialUploadQueue } from './page'
import { usePrivateDraft } from '../drafts/use-private-draft'
import type { PrivateDraft } from '../drafts/client'
import { SubjectEditor, SubjectSelect } from './subjects'

type Remote<T> = { status: 'loading' } | { status: 'loaded'; data: T } | { status: 'error'; message: string }
const MATERIAL_PAGE_SIZE = 20

type MaterialTitleDraft = { title: string }
type WorkflowEvidenceScope = 'material_questions' | 'selected_learner_history'
type WorkflowInputDraft = { learnerId: string; evidenceScope: WorkflowEvidenceScope; hasLocalProposal: boolean }

export function MaterialWorkspace({
  householdId,
  csrfToken,
  canWrite,
  learners,
  selectedLearnerId,
  onUnauthorized,
  onOpenSolutions,
  onUnsavedChange,
  initialTab = 'pages',
  onTabChange,
  initialMaterialId,
  initialQuery,
  initialSubject = '',
  initialPage = 1,
  onLocationChange,
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
  initialTab?: string
  onTabChange?: (value: string) => void
  initialMaterialId?: string
  initialQuery?: string
  initialSubject?: string
  initialPage?: number
  onLocationChange?: (location: { materialId: string; query: string; page: number; subject?: string }) => void
}) {
  const [materials, setMaterials] = useState<Remote<MaterialListResponse>>({ status: 'loading' })
  const [materialsScope, setMaterialsScope] = useState('')
  const [selection, setSelection] = useState({ householdId, materialId: initialMaterialId || '' })
  const [searchInput, setSearchInput] = useState(initialQuery || '')
  const [searchQuery, setSearchQuery] = useState(initialQuery || '')
  const [subjectFilter, setSubjectFilter] = useState(initialSubject)
  const [subjectDirty, setSubjectDirty] = useState(false)
  const [subjectBusy, setSubjectBusy] = useState(false)
  const [searchPage, setSearchPage] = useState(() => normalizeMaterialPage(initialPage))
  const [searchHouseholdId, setSearchHouseholdId] = useState(householdId)
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
  const [contentDirty, setContentDirty] = useState(false)
  const [contentRefreshSignal, setContentRefreshSignal] = useState(0)
  const [activeTab, setActiveTab] = useState<MaterialTab>(() => normalizeMaterialTab(initialTab))
  const [visitedTabs, setVisitedTabs] = useState<Set<MaterialTab>>(() => new Set([normalizeMaterialTab(initialTab)]))
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
  const detailSelectionRef = useRef('')
  const title = titleEntry.householdId === householdId ? titleEntry.value : ''
  const createOpen = createFormHouseholdId === householdId
  const selectedMaterialId = selection.householdId === householdId ? selection.materialId : ''
  const visibleSearchInput = searchHouseholdId === householdId ? searchInput : ''
  const materialQuery = searchHouseholdId === householdId ? searchQuery : ''
  const materialPage = searchHouseholdId === householdId ? searchPage : 1
  const materialListKey = JSON.stringify([householdId, materialQuery, materialPage, subjectFilter])
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
    const nextTab = normalizeMaterialTab(initialTab)
    setActiveTab(nextTab)
    setVisitedTabs((current) => current.has(nextTab) ? current : new Set([...current, nextTab]))
  }, [initialTab])

  useEffect(() => {
    setSelection({ householdId, materialId: initialMaterialId || '' })
  }, [householdId, initialMaterialId])

  useEffect(() => {
    setSearchHouseholdId(householdId)
    setSearchInput(initialQuery || '')
    setSearchQuery(initialQuery || '')
    setSearchPage(normalizeMaterialPage(initialPage))
    setSubjectFilter(initialSubject)
  }, [householdId, initialPage, initialQuery, initialSubject])

  useEffect(() => {
    if (!initialMaterialId && selectedMaterialId) {
      onLocationChange?.({ materialId: selectedMaterialId, query: materialQuery, page: materialPage })
    }
  }, [initialMaterialId, selectedMaterialId, materialQuery, materialPage, onLocationChange])

  const changeTab = (value: MaterialTab) => {
    setActiveTab(value)
    setVisitedTabs((current) => current.has(value) ? current : new Set([...current, value]))
    onTabChange?.(value)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setMaterials({ status: 'loading' })
    setMaterialsScope(`loading:${materialListKey}`)
    api.materials(householdId, controller.signal, { q: materialQuery, subject: subjectFilter, page: materialPage, pageSize: MATERIAL_PAGE_SIZE }).then((data) => {
      if (!active) return
      setMaterialsScope(materialListKey)
      setMaterials({ status: 'loaded', data })
      setSelection((current) => ({
        householdId,
        materialId: current.householdId === householdId && current.materialId
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
  }, [householdId, listRetry, materialListKey, materialQuery, materialPage, subjectFilter, onUnauthorized])

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
    setContentBusy(false)
    setWorkflowNotice('')
    workflowCreateKey.current = null
  }, [selectedMaterialId])

  const refreshMaterials = () => setListRetry((value) => value + 1)
  const refreshDetail = (confirmUnsaved = true) => {
    if (confirmUnsaved && contentDirty && !window.confirm('题面、答案或整页阅读记录还有未保存输入。刷新资料会丢弃这些输入，仍要继续吗？')) return
    if (confirmUnsaved) {
      setContentDirty(false)
      setContentRefreshSignal((value) => value + 1)
    }
    setDetailRetry((value) => value + 1)
  }
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

  const selectMaterial = (materialId: string, skipUnsavedCheck = false, location?: { query: string; page: number }) => {
    if ((!skipUnsavedCheck && scopeBusy) || materialId === selectedMaterialId) return
    if (!skipUnsavedCheck && workflowSavePending && !window.confirm('当前整理任务设置尚未保存。切换资料后这些设置会丢失，仍要切换吗？')) return
    if (!skipUnsavedCheck && (contentDirty || subjectDirty) && !window.confirm('题面、答案、学科或整页阅读记录还有未保存输入。切换资料会丢弃这些输入，仍要切换吗？')) return
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
    onLocationChange?.({ materialId, query: location?.query ?? materialQuery, page: location?.page ?? materialPage })
    changeTab('pages')
  }

  const scopeBusy = createBusy || uploadQueueBusy || workflowBusy || workflowActionBusy || contentBusy || subjectBusy

  const searchMaterials = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (scopeBusy) return
    if (workflowSavePending && !window.confirm('当前整理任务设置尚未保存。搜索结果可能切换资料并丢失这些设置，仍要搜索吗？')) return
    setSearchHouseholdId(householdId)
    const query = visibleSearchInput.trim()
    setSearchQuery(query)
    setSearchPage(1)
    onLocationChange?.({ materialId: selectedMaterialId, query, page: 1 })
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
    onLocationChange?.({ materialId: selectedMaterialId, query: materialQuery, page })
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
    onUnsavedChange(titleSavePending || workflowSavePending || createBusy || workflowBusy || contentDirty || subjectDirty || subjectBusy)
    return () => onUnsavedChange(false)
  }, [contentDirty, createBusy, onUnsavedChange, titleSavePending, workflowBusy, workflowSavePending, subjectDirty, subjectBusy])

  const createMaterial = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const cleanTitle = title.trim()
    if (!cleanTitle || createBusy || hasTitlePendingDraft) return
    if (contentDirty && !window.confirm('题面、答案或整页阅读记录还有未保存输入。创建后切换到新资料会丢弃这些输入，仍要继续吗？')) return
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
      selectMaterial(response.material.id, true, { query: '', page: 1 })
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

  const selectJob = (selectedJobId: string) => {
    setJobId(selectedJobId)
    changeTab('tasks')
  }

  return (
    <div className='grid min-w-0 gap-5 xl:grid-cols-[minmax(16rem,0.28fr)_minmax(0,1fr)]'>
      <section className='min-w-0 space-y-3' aria-label='资料列表'>
          <WorkspaceHeading title='资料列表' actions={<>
          <Button type='button' variant='outline' size='sm' onClick={refreshMaterials}><RefreshCw className='size-4' aria-hidden='true' />刷新</Button>
          <Button type='button' size='sm' onClick={() => setCreateFormHouseholdId(createOpen ? '' : householdId)} disabled={!canWrite || scopeBusy}><FilePlus2 className='size-4' aria-hidden='true' />新建资料</Button>
        </>} />
        <form className='flex flex-wrap items-end gap-2 border-b pb-3' role='search' onSubmit={searchMaterials}>
          <SubjectSelect value={subjectFilter} all label='资料学科' disabled={scopeBusy} onChange={(subject) => { setSubjectFilter(subject); setSearchPage(1); onLocationChange?.({ materialId: selectedMaterialId, query: materialQuery, page: 1, subject }) }} />
          <label className='min-w-[min(100%,14rem)] flex-1 text-sm font-medium'>搜索资料 <HelpTip label='资料搜索帮助'>输入资料名称中的几个字，按“搜索”查看匹配资料；翻页会继续在当前家庭的全部资料中查找。</HelpTip><input type='search' disabled={scopeBusy} value={visibleSearchInput} onChange={(event) => updateSearchInput(event.target.value)} placeholder='输入资料名称' className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' /></label>
          <Button type='submit' variant='outline' disabled={scopeBusy}><Search className='size-4' aria-hidden='true' />搜索</Button>
          {materialQuery ? <Button type='button' variant='ghost' disabled={scopeBusy} onClick={() => { if (workflowSavePending && !window.confirm('当前整理任务设置尚未保存。清除搜索后可能切换资料并丢失这些设置，仍要继续吗？')) return; updateSearchInput(''); setSearchQuery(''); setSearchPage(1); onLocationChange?.({ materialId: selectedMaterialId, query: '', page: 1 }) }}>清除</Button> : null}
        </form>
        {currentMaterials.status === 'loading' ? <LoadingState label='正在读取资料列表…' /> : null}
        {currentMaterials.status === 'error' ? <RetryState message={currentMaterials.message} onRetry={refreshMaterials} title='无法读取资料列表' /> : null}
        {currentMaterials.status === 'loaded' ? <>
          {currentMaterials.data.items.length === 0 ? (materialQuery
            ? <EmptyState title='没有找到匹配的资料' detail='试试更短的关键词，或清除搜索查看全部资料。' icon={Search} />
            : <EmptyState title='还没有资料' detail='新建资料后，可以从本机逐张上传原图。' icon={FilePlus2} />) : (
            <ul className='max-h-[min(62vh,48rem)] space-y-1 overflow-y-auto pr-1'>
              {currentMaterials.data.items.map((item) => <li key={item.id}>
                <button type='button' aria-pressed={selectedMaterialId === item.id} onClick={() => selectMaterial(item.id)} disabled={scopeBusy} className={`flex min-h-11 w-full items-center justify-between gap-3 border-b px-2 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${selectedMaterialId === item.id ? 'border-l-2 border-l-primary bg-primary/[0.05] font-semibold' : 'hover:bg-muted/40'}`}>
                  <span className='min-w-0 break-words'>{item.title}</span><span className='shrink-0 text-xs text-muted-foreground'>{item.page_count} 页</span>
                </button>
              </li>)}
            </ul>
          )}
          <div className='flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground'>
            <span>共 {currentMaterials.data.total} 份 · 第 {currentMaterials.data.page ?? materialPage} 页</span>
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
        {createOpen ? <form className='grid gap-2 border-t pt-3 sm:grid-cols-[minmax(0,1fr)_auto]' onSubmit={(event) => void createMaterial(event)}>
          <label className='text-sm font-medium'>资料名称<input autoFocus required maxLength={200} disabled={scopeBusy || hasTitlePendingDraft} className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={title} onChange={(event) => { const value = event.target.value; setTitleEntry({ householdId, value }); setTitleEdited(true); setTitleSavePending(true) }} /></label>
          <div className='flex items-end'><Button type='submit' disabled={scopeBusy || !title.trim()}>{createBusy ? '正在创建…' : '创建资料'}</Button></div>
          {createError ? <p role='alert' className='text-sm text-destructive sm:col-span-2'>{createError}</p> : null}
          {titleDraft.loadError ? <p role='alert' className='text-sm text-amber-900 sm:col-span-2'>私人草稿暂时无法读取，自动保存已暂停；当前输入仍保留在页面中。</p> : null}
          {titleDraft.message ? <p role='status' className='text-sm text-muted-foreground sm:col-span-2'>{titleDraft.message}</p> : null}
        </form> : null}
      </section>

      <section className='min-w-0 space-y-4' aria-label='当前资料详情'>
        {!selectedMaterialId ? <EmptyState title='选择一份资料' detail='资料名称、原图和整理状态会显示在这里。' /> : <>
          <WorkspaceHeading
            title={currentDetail.status === 'loaded' ? currentDetail.data.material.title : materialTitle(currentMaterials, selectedMaterialId)}
            actions={<Button type='button' variant='outline' size='sm' onClick={() => refreshDetail()} disabled={currentDetail.status === 'loading'}><RefreshCw className='size-4' aria-hidden='true' />刷新资料</Button>}
          />
          {currentDetail.status === 'loading' ? <LoadingState label='正在读取资料页、完整度和任务历史…' /> : null}
          {currentDetail.status === 'error' ? <RetryState message={currentDetail.message} onRetry={refreshDetail} title='无法读取资料详情' /> : null}
          {currentDetail.status === 'loaded' ? <>
            <SubjectEditor key={selectedMaterialId} materialId={selectedMaterialId} csrfToken={csrfToken} writable={canWrite} onUnauthorized={onUnauthorized} onSaved={() => { refreshDetail(); setListRetry((value) => value + 1) }} onDirtyChange={setSubjectDirty} onBusyChange={setSubjectBusy} />
            {detailRefreshError ? <div role='alert' className='flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/30'><span>资料暂时无法刷新：{detailRefreshError}。当前输入仍保留。</span><Button type='button' size='sm' variant='outline' onClick={() => refreshDetail()}>重试刷新资料</Button></div> : null}
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
            {workflowError ? <p role='alert' className='rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950'>{workflowError}</p> : null}
            {workflowNotice ? <div role='status' className='flex flex-wrap items-center justify-between gap-3 rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-950'><span>{workflowNotice}</span><Button type='button' variant='outline' size='sm' onClick={() => changeTab('tasks')}>查看当前任务</Button></div> : null}
            <WorkspaceTabs id='materials' label='资料工作区' tabs={[
              { value: 'pages', label: '原图与进度', count: currentDetail.data.pages.length },
              { value: 'content', label: '题面核对', count: currentDetail.data.readiness.questions.length },
              { value: 'solutions', label: '讲解' },
              { value: 'tasks', label: '整理任务', count: currentDetail.data.jobs.length },
            ]} value={activeTab} onChange={(value) => changeTab(value as MaterialTab)} />
            <div key={selectedMaterialId} className='min-w-0'>
              <WorkspacePanel id='materials' value='pages' active={activeTab}>
                {visitedTabs.has('pages') ? <>
                  <MaterialUploadQueue materialId={selectedMaterialId} csrfToken={csrfToken} canWrite={canWrite} onUnauthorized={onUnauthorized} onBusyChange={setUploadQueueBusy} onUploaded={() => { refreshDetail(false); refreshMaterials() }} />
                  <MaterialReadiness detail={currentDetail.data} />
                </> : null}
              </WorkspacePanel>
              <WorkspacePanel id='materials' value='content' active={activeTab}>
                {visitedTabs.has('content') ? <ContentWorkspace
                  materialId={currentDetail.data.material.id}
                  pages={currentDetail.data.pages}
                  csrfToken={csrfToken}
                  canWrite={canWrite}
                  onUnauthorized={onUnauthorized}
                  onBusyChange={setContentBusy}
                  onUnsavedChange={setContentDirty}
                  refreshSignal={contentRefreshSignal}
                  onClose={() => changeTab('pages')}
                /> : null}
              </WorkspacePanel>
              <WorkspacePanel id='materials' value='solutions' active={activeTab}>
                {visitedTabs.has('solutions') ? <section className='space-y-3 border-b pb-4'>
                    <WorkspaceHeading title='逐题讲解与文档' />
                    <p className='max-w-3xl text-sm text-muted-foreground'>整理独立的讲解版本，核对原图来源和每一步，再生成 PDF／Word。讲解文件与学习者的真实作答分别保存。</p>
                    <Button type='button' onClick={() => onOpenSolutions(selectedMaterialId)}>打开讲解工作区</Button>
                  </section> : null}
              </WorkspacePanel>
              <WorkspacePanel id='materials' value='tasks' active={activeTab}>
                {visitedTabs.has('tasks') ? <div className='space-y-4'>
                  <div className='flex flex-wrap items-center justify-between gap-3'>
                    <p className='max-w-3xl text-sm text-muted-foreground'>选择整理范围并导入可选文件；创建后逐项核对结果，再决定是否确认。</p>
                    {!createWorkflowOpen && canWrite ? <Button type='button' onClick={() => setCreateWorkflowOpen(true)} disabled={scopeBusy || hasWorkflowPendingDraft}>新建整理任务</Button> : null}
                  </div>
                  {canWrite ? <ProposalPicker key={selectedMaterialId} pages={currentDetail.data.pages} value={proposal} onChange={(value) => { setProposal(value); setProposalNeedsReselect(false); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }} /> : <p className='rounded-md border bg-muted/20 p-4 text-sm text-muted-foreground'>当前为只读成员，可以查看原图、任务和输出；内容修改由家庭所有者或审核成员操作。</p>}
                  {createWorkflowOpen ? <Card className='gap-0 py-0'>
                    <CardHeader className='border-b py-4'><CardTitle className='text-base'>新建资料整理任务</CardTitle><CardDescription>创建后不会自动处理或确认内容，家长仍需逐项核对。</CardDescription></CardHeader>
                    <CardContent className='space-y-4 p-4'>
                      <ol className='grid gap-2 text-sm sm:grid-cols-3' aria-label='整理任务步骤'><li className='border-l-2 border-primary/40 pl-3'><span className='font-semibold'>1. 选择范围</span><span className='mt-1 block text-muted-foreground'>可指定学习者，也可不关联。</span></li><li className='border-l-2 border-primary/40 pl-3'><span className='font-semibold'>2. 补充资料</span><span className='mt-1 block text-muted-foreground'>已有内容可直接整理；额外文件需重新选择。</span></li><li className='border-l-2 border-primary/40 pl-3'><span className='font-semibold'>3. 创建并核对</span><span className='mt-1 block text-muted-foreground'>创建后检查，再决定是否确认。</span></li></ol>
                      {learners.length ? <label className='block max-w-md text-sm font-medium'>学习者（可选）<select disabled={scopeBusy || hasWorkflowPendingDraft} className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={learnerId} onChange={(event) => { setLearnerId(event.target.value); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }}><option value=''>不关联学习者</option>{learners.map((learner) => <option key={learner.id} value={learner.id}>{learner.display_name}{learner.grade ? ` · ${learner.grade}` : ''}</option>)}</select></label> : <p className='text-sm text-muted-foreground'>此任务不必关联学习者；可稍后从家庭设置中管理学习者。</p>}
                      <fieldset disabled={scopeBusy || hasWorkflowPendingDraft} className='space-y-2 border-l-2 border-muted pl-3'><legend className='flex items-center gap-1 px-1 text-sm font-medium'>整理哪些作答记录<HelpTip label='作答记录范围帮助'>选择“本资料题目”会整理当前资料关联题目的历次作答；选择“所选学习者”会包含这名学习者在其他资料中的记录。未选择学习者时不会关联个人历史。</HelpTip></legend>
                        <label className='flex items-start gap-2 text-sm'><input type='radio' name='evidence-scope' value='material_questions' checked={evidenceScope === 'material_questions'} onChange={() => { setEvidenceScope('material_questions'); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }} /><span><span className='font-medium'>本资料题目的全部作答记录</span><span className='mt-0.5 block text-xs text-muted-foreground'>默认只看当前资料中题目的历次作答。</span></span></label>
                        <label className='flex items-start gap-2 text-sm'><input type='radio' name='evidence-scope' value='selected_learner_history' checked={evidenceScope === 'selected_learner_history'} onChange={() => { setEvidenceScope('selected_learner_history'); setWorkflowEdited(true); setWorkflowSavePending(true); workflowDraft.setMessage('') }} /><span><span className='font-medium'>所选学习者的全部历史记录</span><span className='mt-0.5 block text-xs text-muted-foreground'>{learnerId ? '包括这名学习者在其他资料中的作答。' : '尚未选择学习者，创建后会列出待测项目，不会关联个人历史。'}</span></span></label>
                      </fieldset>
                      {proposalNeedsReselect ? <p role='status' className='rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950'>已恢复其他任务设置。此前选择的本机文件没有随草稿保存，请重新选择并核对后再创建。</p> : null}
                      {workflowDraft.message ? <p role='status' className='text-sm text-muted-foreground'>{workflowDraft.message}</p> : null}
                      <div className='flex flex-wrap gap-2'><Button type='button' onClick={() => void createWorkflow()} disabled={scopeBusy || hasWorkflowPendingDraft || Boolean(proposalNeedsReselect)}>{workflowBusy ? '正在创建…' : '创建并查看任务'}</Button><Button type='button' variant='outline' onClick={() => setCreateWorkflowOpen(false)} disabled={scopeBusy}>取消</Button></div>
                    </CardContent>
                  </Card> : null}
                  <MaterialTaskHistory jobs={currentDetail.data.jobs} selectedJobId={jobId} onSelectJob={selectJob} busy={scopeBusy} />
                  {jobId ? <WorkflowPanel key={`${selectedMaterialId}:${jobId}`} jobId={jobId} csrfToken={csrfToken} canWrite={canWrite} pages={currentDetail.data.pages} onUnauthorized={onUnauthorized} onJobUpdated={onJobUpdated} onBusyChange={setWorkflowActionBusy} onOpenContent={() => changeTab('content')} /> : null}
                </div> : null}
              </WorkspacePanel>
            </div>
          </> : null}
        </>}
      </section>
    </div>
  )
}

type MaterialTab = 'pages' | 'content' | 'solutions' | 'tasks'

function normalizeMaterialTab(value: string | undefined): MaterialTab {
  return value === 'content' || value === 'solutions' || value === 'tasks' ? value : 'pages'
}

function normalizeMaterialPage(value: number | undefined) {
  return Number.isSafeInteger(value) && value! > 0 ? value! : 1
}

function materialTitle(materials: Remote<MaterialListResponse>, materialId: string) {
  return materials.status === 'loaded' ? materials.data.items.find((item) => item.id === materialId)?.title || '当前资料' : '当前资料'
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
  return <section className='space-y-3 rounded-lg border border-sky-200 bg-sky-50/60 p-4 dark:border-sky-900 dark:bg-sky-950/30' aria-label='私人草稿'>
    {loadError ? <p role='alert' className='text-sm text-amber-950 dark:text-amber-200'>私人草稿暂时无法读取，自动保存已暂停；当前页面的输入仍保留。刷新页面后可以重试。</p> : null}
    {invalidDraft ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm text-amber-950 dark:text-amber-200'><span>这份私人草稿格式无法识别，当前内容没有被替换。</span><Button type='button' size='sm' variant='outline' onClick={onClearInvalid}>清理不可恢复草稿</Button></div> : null}
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
