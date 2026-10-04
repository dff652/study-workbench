import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { FilePlus2, RefreshCw } from 'lucide-react'
import { api, getErrorMessage } from '../../api'
import { ApiLink, EmptyState, isUnauthorized, LoadingState, RetryState } from '../../components/shared'
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

type Remote<T> = { status: 'loading' } | { status: 'loaded'; data: T } | { status: 'error'; message: string }

export function MaterialWorkspace({
  householdId,
  householdName,
  csrfToken,
  canWrite,
  learners,
  selectedLearnerId,
  onUnauthorized,
  onOpenSolutions,
}: {
  householdId: string
  householdName: string
  csrfToken: string
  canWrite: boolean
  learners: Learner[]
  selectedLearnerId: string
  onUnauthorized: () => void
  onOpenSolutions: (materialId: string) => void
}) {
  const [materials, setMaterials] = useState<Remote<MaterialListResponse>>({ status: 'loading' })
  const [selectedMaterialId, setSelectedMaterialId] = useState('')
  const [detail, setDetail] = useState<Remote<MaterialDetailResponse>>({ status: 'loading' })
  const [detailMaterialId, setDetailMaterialId] = useState('')
  const [listRetry, setListRetry] = useState(0)
  const [detailRetry, setDetailRetry] = useState(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState('')
  const [uploadQueueBusy, setUploadQueueBusy] = useState(false)
  const [jobId, setJobId] = useState('')
  const [workflowBusy, setWorkflowBusy] = useState(false)
  const [workflowActionBusy, setWorkflowActionBusy] = useState(false)
  const [contentBusy, setContentBusy] = useState(false)
  const [contentOpen, setContentOpen] = useState(false)
  const [workflowError, setWorkflowError] = useState('')
  const [proposal, setProposal] = useState<SkillImport | null>(null)
  const [createWorkflowOpen, setCreateWorkflowOpen] = useState(false)
  const [learnerId, setLearnerId] = useState(selectedLearnerId)
  const materialCreateKey = useRef<RequestKeyState>(null)
  const workflowCreateKey = useRef<RequestKeyState>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setMaterials({ status: 'loading' })
    api.materials(householdId, controller.signal).then((data) => {
      if (!active) return
      setMaterials({ status: 'loaded', data })
      setSelectedMaterialId((current) => current && data.items.some((item) => item.id === current) ? current : data.items[0]?.id || '')
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setMaterials({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, listRetry, onUnauthorized])

  useEffect(() => {
    setLearnerId(selectedLearnerId)
  }, [selectedLearnerId])

  useEffect(() => {
    if (!selectedMaterialId) {
      setDetail({ status: 'loading' })
      setDetailMaterialId('')
      setJobId('')
      setProposal(null)
      return
    }
    const controller = new AbortController()
    let active = true
    setDetail({ status: 'loading' })
    setDetailMaterialId(selectedMaterialId)
    setJobId('')
    setProposal(null)
    api.material(selectedMaterialId, controller.signal).then((data) => {
      if (!active) return
      setDetail({ status: 'loaded', data })
      setJobId(data.jobs[0]?.id || '')
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setDetail({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [selectedMaterialId, detailRetry, onUnauthorized])

  useEffect(() => {
    setProposal(null)
    setWorkflowError('')
    setCreateWorkflowOpen(false)
    setContentOpen(false)
    setContentBusy(false)
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

  const selectMaterial = (materialId: string) => {
    if (materialId === selectedMaterialId) return
    setSelectedMaterialId(materialId)
    setDetail({ status: 'loading' })
    setDetailMaterialId('')
    setJobId('')
    setProposal(null)
    setWorkflowError('')
    setCreateWorkflowOpen(false)
    workflowCreateKey.current = null
  }

  const currentDetail: Remote<MaterialDetailResponse> = detailMaterialId === selectedMaterialId
    ? detail
    : { status: 'loading' }
  const scopeBusy = createBusy || uploadQueueBusy || workflowBusy || workflowActionBusy || contentBusy

  const createMaterial = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const cleanTitle = title.trim()
    if (!cleanTitle || createBusy) return
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
      setTitle('')
      setCreateOpen(false)
      selectMaterial(response.material.id)
      setListRetry((value) => value + 1)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setCreateError(getErrorMessage(cause))
    } finally {
      setCreateBusy(false)
    }
  }

  const createWorkflow = async () => {
    if (!selectedMaterialId || workflowBusy) return
    setWorkflowBusy(true)
    setWorkflowError('')
    let key: string
    try {
      key = requestKeyFor(workflowCreateKey, JSON.stringify({ material: selectedMaterialId, learner: learnerId || null, proposal }))
    } catch (cause) {
      setWorkflowError(getErrorMessage(cause))
      setWorkflowBusy(false)
      return
    }
    try {
      const response = await api.createWorkflow(selectedMaterialId, {
        request_key: key,
        ...(learnerId ? { learner_id: learnerId } : {}),
        ...(proposal ? { proposal } : {}),
      }, csrfToken)
      workflowCreateKey.current = null
      setJobId(response.job.id)
      setCreateWorkflowOpen(false)
      setProposal(null)
      setListRetry((value) => value + 1)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setWorkflowError(getErrorMessage(cause))
    } finally {
      setWorkflowBusy(false)
    }
  }

  return (
    <div className='space-y-5'>
      <Card>
        <CardHeader className='flex flex-wrap items-start justify-between gap-3 border-b pb-4'>
          <div><CardTitle className='text-base'>家庭资料</CardTitle><CardDescription className='mt-1'>{householdName} · 创建资料、逐张上传原图，再按需建立整理任务。</CardDescription></div>
          <div className='flex gap-2'><Button type='button' variant='outline' size='sm' onClick={refreshMaterials}><RefreshCw className='size-4' aria-hidden='true' />刷新资料</Button><Button type='button' size='sm' onClick={() => setCreateOpen((value) => !value)} disabled={!canWrite || scopeBusy}><FilePlus2 className='size-4' aria-hidden='true' />新建资料</Button></div>
        </CardHeader>
        <CardContent className='space-y-4 pt-4'>
          {materials.status === 'loading' ? <LoadingState label='正在读取当前家庭的资料…' /> : null}
          {materials.status === 'error' ? <RetryState message={materials.message} onRetry={refreshMaterials} title='无法读取资料列表' /> : null}
          {materials.status === 'loaded' ? <>
            {materials.data.total > materials.data.items.length ? <p className='flex flex-wrap items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-950'>当前列表显示最近 {materials.data.items.length} 份资料。<ApiLink href='/materials/'>查看全部资料</ApiLink></p> : null}
            {materials.data.items.length === 0 ? <EmptyState title='这个家庭还没有资料' detail='新建一份资料后，可以从本机逐张上传原始图片。' icon={FilePlus2} /> : (
              <div className='grid gap-2 sm:grid-cols-2 xl:grid-cols-3'>
                {materials.data.items.map((item) => <button key={item.id} type='button' aria-pressed={selectedMaterialId === item.id} onClick={() => selectMaterial(item.id)} disabled={scopeBusy} className={`rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${selectedMaterialId === item.id ? 'border-primary bg-primary/[0.04] ring-1 ring-primary/30' : 'bg-background hover:bg-muted/40'}`}><span className='flex items-center justify-between gap-2'><span className='truncate font-semibold'>{item.title}</span>{selectedMaterialId === item.id ? <Badge variant='secondary'>当前资料</Badge> : null}</span><span className='mt-2 block text-xs text-muted-foreground'>{item.page_count} 张原图页</span></button>)}
              </div>
            )}
          </> : null}
          {createOpen ? <form className='grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_auto]' onSubmit={(event) => void createMaterial(event)}>
            <label className='text-sm font-medium'>资料名称<input autoFocus required maxLength={200} disabled={scopeBusy} className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={title} onChange={(event) => setTitle(event.target.value)} /></label>
            <div className='flex items-end'><Button type='submit' disabled={scopeBusy || !title.trim()}>{createBusy ? '正在创建…' : '创建资料'}</Button></div>
            {createError ? <p role='alert' className='text-sm text-destructive sm:col-span-2'>{createError}</p> : null}
          </form> : null}
        </CardContent>
      </Card>

      {selectedMaterialId ? <>
        <MaterialUploadQueue materialId={selectedMaterialId} csrfToken={csrfToken} canWrite={canWrite} onUnauthorized={onUnauthorized} onBusyChange={setUploadQueueBusy} onUploaded={() => { refreshDetail(); refreshMaterials() }} />

        {currentDetail.status === 'loading' ? <LoadingState label='正在读取资料页、完整度和任务历史…' /> : null}
        {currentDetail.status === 'error' ? <RetryState message={currentDetail.message} onRetry={refreshDetail} title='无法读取资料详情' /> : null}
        {currentDetail.status === 'loaded' ? <>
          <div key={selectedMaterialId} className='space-y-5'>
            <Card><CardContent className='flex flex-wrap items-center justify-between gap-3 p-4'><div><h2 className='font-semibold'>逐题解析与文档</h2><p className='mt-1 text-sm text-muted-foreground'>在原图核对后，可把题干、讲义解法和答案整理为独立解析版本。</p></div><Button type='button' onClick={() => onOpenSolutions(selectedMaterialId)}>整理解析</Button></CardContent></Card>
            {canWrite ? <ProposalPicker pages={currentDetail.data.pages} value={proposal} onChange={setProposal} /> : <p className='rounded-md border bg-muted/20 p-4 text-sm text-muted-foreground'>当前为只读成员，可以查看原图、任务和输出；内容修改由家庭所有者或审核成员操作。</p>}
            <MaterialReadiness detail={currentDetail.data} selectedJobId={jobId} onSelectJob={setJobId} busy={scopeBusy} />
            <Card className='gap-0 py-0 shadow-sm'>
              <CardHeader className='flex flex-wrap items-start justify-between gap-3 py-4'>
                <div><CardTitle className='text-base'>同页题面核对与整页阅读</CardTitle><CardDescription className='mt-1'>对照本资料原图选区，记录题目内容、讲义勘误和每页阅读状态。</CardDescription></div>
                <Button type='button' variant={contentOpen ? 'secondary' : 'outline'} onClick={() => setContentOpen((value) => !value)} disabled={scopeBusy}>{contentOpen ? '收起内容核对' : '打开内容核对'}</Button>
              </CardHeader>
            </Card>
            {contentOpen ? <ContentWorkspace
              materialId={currentDetail.data.material.id}
              pages={currentDetail.data.pages}
              csrfToken={csrfToken}
              canWrite={canWrite}
              onUnauthorized={onUnauthorized}
              onBusyChange={setContentBusy}
              onClose={() => setContentOpen(false)}
            /> : null}
            {!createWorkflowOpen && canWrite ? <Button type='button' onClick={() => setCreateWorkflowOpen(true)} disabled={scopeBusy}>新建整理任务</Button> : null}
            {createWorkflowOpen ? <Card><CardHeader><CardTitle className='text-base'>新建资料整理任务</CardTitle><CardDescription>交换 JSON 为可选项；不选时任务整理当前资料中已有的已确认内容。创建不会自动开始处理。</CardDescription></CardHeader><CardContent className='space-y-4'>
              {learners.length ? <label className='block max-w-md text-sm font-medium'>学习者（可选）<select disabled={scopeBusy} className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={learnerId} onChange={(event) => setLearnerId(event.target.value)}><option value=''>不关联学习者</option>{learners.map((learner) => <option key={learner.id} value={learner.id}>{learner.display_name}{learner.grade ? ` · ${learner.grade}` : ''}</option>)}</select></label> : <p className='text-sm text-muted-foreground'>此任务不必关联学习者；可稍后从家庭设置中管理学习者。</p>}
              {workflowError ? <p role='alert' className='rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-950'>{workflowError}</p> : null}
              <div className='flex flex-wrap gap-2'><Button type='button' onClick={() => void createWorkflow()} disabled={scopeBusy}>{workflowBusy ? '正在创建…' : '创建并查看任务'}</Button><Button type='button' variant='outline' onClick={() => setCreateWorkflowOpen(false)} disabled={scopeBusy}>返回资料</Button></div>
            </CardContent></Card> : null}
            {jobId ? <WorkflowPanel key={`${selectedMaterialId}:${jobId}`} jobId={jobId} csrfToken={csrfToken} canWrite={canWrite} pages={currentDetail.data.pages} onUnauthorized={onUnauthorized} onJobUpdated={onJobUpdated} onBusyChange={setWorkflowActionBusy} onOpenContent={() => setContentOpen(true)} /> : null}
          </div>
        </> : null}
      </> : materials.status === 'loaded' && materials.data.items.length === 0 ? <p className='sr-only'>新建资料后可以继续。</p> : null}
    </div>
  )
}
