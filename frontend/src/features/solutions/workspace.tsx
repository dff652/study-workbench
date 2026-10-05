import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, getErrorMessage, getSolutionHistory, getSolutionOutput, getSolutionOutputs, getSolutionRevision, getSolutions, saveSolution, solutionAction, solutionOutputAction } from '../../api'
import { EmptyState, isUnauthorized, LoadingState, RetryState, sameOriginHref } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { Disclosure } from '../../components/disclosure'
import type { AnySolutionContent, SolutionFigure, SolutionOutput, SolutionOutputActionInput, SolutionQuestion, SolutionWorkspaceResponse, StructuredSolutionContent, StructuredSolutionQuestion } from '../../types'
import type { PrivateDraft } from '../drafts/client'
import { usePrivateDraft } from '../drafts/use-private-draft'
import { requestKeyFor, type RequestKeyState } from '../materials/request-keys'
import { SolutionEditor } from './editor'
import { contentHasMinimumForGeneration, isAnySolutionContent, outputIsProcessing, solutionText, toStructuredSolutionContent } from './model'

type Remote<T> = { status: 'loading' } | { status: 'loaded'; data: T } | { status: 'error'; message: string }
type SaveState = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict'
type ActionName = 'confirm' | 'generate'
type SolutionDraftPayload = { content: AnySolutionContent; reason: string }
type SolutionPrivateDraft = PrivateDraft<SolutionDraftPayload | { cleared: true }>

const EMPTY_SOLUTION_CONTENT: StructuredSolutionContent = {
  schema_version: 'swb.solution.v2', title: '', lectures: [], questions: [],
  outputs: { per_question: [], per_lecture: [], combined: [] },
}

export function SolutionWorkspace({
  materialId,
  householdId,
  csrfToken,
  canWrite,
  onUnauthorized,
  onBack,
  onUnsavedChange,
  initialPanel = 'editor',
}: {
  materialId: string
  householdId: string
  csrfToken: string
  canWrite: boolean
  onUnauthorized: () => void
  onBack: () => void
  onUnsavedChange?: (unsaved: boolean) => void
  initialPanel?: 'editor' | 'outputs'
}) {
  const [remote, setRemote] = useState<Remote<SolutionWorkspaceResponse>>({ status: 'loading' })
  const [content, setContent] = useState<StructuredSolutionContent | null>(null)
  const [baseline, setBaseline] = useState<StructuredSolutionContent | null>(null)
  const [draftCompare, setDraftCompare] = useState<{ title: string; content: StructuredSolutionContent } | null>(null)
  const contentRef = useRef<StructuredSolutionContent | null>(null)
  const baselineRef = useRef<StructuredSolutionContent | null>(null)
  const expectedVersionRef = useRef(0)
  const saveBusyRef = useRef(false)
  const saveStateRef = useRef<SaveState>('idle')
  const saveRequestKeyRef = useRef<RequestKeyState>(null)
  const actionRequestKeyRef = useRef<RequestKeyState>(null)
  const outputActionKeysRef = useRef(new Map<string, { current: RequestKeyState }>())
  const mountedRef = useRef(true)
  const privateDraftSavedSignatureRef = useRef('')
  const previousPrivateDraftMessageRef = useRef('')
  const historyPageControllerRef = useRef<AbortController | null>(null)
  const outputPageControllerRef = useRef<AbortController | null>(null)
  const historyPageBusyRef = useRef(false)
  const outputPageBusyRef = useRef(false)
  const failedSnapshotRef = useRef('')
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [saveError, setSaveError] = useState('')
  const [conflict, setConflict] = useState<SolutionWorkspaceResponse | null>(null)
  const [showConflictCompare, setShowConflictCompare] = useState(false)
  const [conflictLoading, setConflictLoading] = useState(false)
  const [reason, setReason] = useState('整理逐题解析')
  const [action, setAction] = useState<ActionName | null>(null)
  const [actionError, setActionError] = useState('')
  const [retry, setRetry] = useState(0)
  const [historyId, setHistoryId] = useState<number | null>(null)
  const [activePanel, setActivePanel] = useState<'editor' | 'outputs' | 'history'>(initialPanel)
  const [expandedOutputId, setExpandedOutputId] = useState<string | null>(null)
  const [history, setHistory] = useState<{ status: 'idle' | 'loading' | 'loaded' | 'error'; revision?: SolutionWorkspaceResponse['revision']; message?: string }>({ status: 'idle' })
  const [olderHistory, setOlderHistory] = useState<SolutionWorkspaceResponse['history']>([])
  const [olderNodes, setOlderNodes] = useState<SolutionWorkspaceResponse['nodes']>([])
  const [historyBefore, setHistoryBefore] = useState<number | null>(null)
  const [historyPageLoading, setHistoryPageLoading] = useState(false)
  const [historyPageError, setHistoryPageError] = useState('')
  const [olderOutputs, setOlderOutputs] = useState<SolutionOutput[]>([])
  const [outputBefore, setOutputBefore] = useState<string | null>(null)
  const [outputPageLoading, setOutputPageLoading] = useState(false)
  const [outputPageError, setOutputPageError] = useState('')
  const [checksDraft, setChecksDraft] = useState<Record<string, SolutionOutput['checks']>>({})
  const [outputActionError, setOutputActionError] = useState('')
  const [pollError, setPollError] = useState('')
  const [pollRetry, setPollRetry] = useState(0)

  useEffect(() => {
    setActivePanel(initialPanel)
  }, [initialPanel, materialId])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      historyPageControllerRef.current?.abort()
      outputPageControllerRef.current?.abort()
    }
  }, [])

  const setLoadedWorkspace = useCallback((data: SolutionWorkspaceResponse, resetPageCursors = false) => {
    setRemote({ status: 'loaded', data })
    if (resetPageCursors) {
      setHistoryBefore(data.history_next_before ?? null)
      setOutputBefore(data.output_next_before ?? null)
      setExpandedOutputId(mergeOutputs([], data.outputs)[0]?.id || null)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    setContent(null)
    setConflict(null)
    setHistoryId(null)
    setHistory({ status: 'idle' })
    setOlderHistory([])
    setOlderNodes([])
    setHistoryBefore(null)
    setHistoryPageLoading(false)
    setHistoryPageError('')
    setOlderOutputs([])
    setOutputBefore(null)
    setOutputPageLoading(false)
    setOutputPageError('')
    setSaveState('idle')
    saveStateRef.current = 'idle'
    setSaveError('')
    getSolutions(materialId, controller.signal).then((data) => {
      if (!active) return
      const current = toStructuredSolutionContent(data.revision?.content || data.initial_content)
      contentRef.current = current
      baselineRef.current = current
      setBaseline(current)
      expectedVersionRef.current = data.revision?.version || 0
      setContent(current)
      setLoadedWorkspace(data, true)
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [materialId, onUnauthorized, retry, setLoadedWorkspace])

  const dirty = useMemo(() => Boolean(content && baseline && JSON.stringify(content) !== JSON.stringify(baseline)), [baseline, content])
  const writable = canWrite && remote.status === 'loaded' && remote.data.writable
  const baseStamp = remote.status === 'loaded'
    ? JSON.stringify([remote.data.revision?.version || 0, remote.data.source_stamp || ''])
    : ''
  const privateDraftPayload = useMemo(() => ({ content: content || EMPTY_SOLUTION_CONTENT, reason }), [content, reason])
  const privateDraftPayloadRef = useRef(privateDraftPayload)
  privateDraftPayloadRef.current = privateDraftPayload
  const privateDraft = usePrivateDraft<SolutionDraftPayload>({
    key: `solution:${materialId}`,
    householdId,
    csrfToken,
    baseStamp,
    enabled: writable,
    dirty: Boolean(content && baseline && dirty),
    payload: privateDraftPayload,
    onUnauthorized,
  })
  const privateDraftPayloadSignature = JSON.stringify([householdId, materialId, baseStamp, privateDraftPayload])
  const privateCandidateContent = useMemo(() => privateDraftContent(privateDraft.candidate), [privateDraft.candidate])
  const privateConflictContent = useMemo(() => privateDraftContent(privateDraft.conflict || null), [privateDraft.conflict])
  saveStateRef.current = saveState

  useEffect(() => {
    if (privateDraft.message === '私人草稿已保存。' && previousPrivateDraftMessageRef.current !== '私人草稿已保存。') {
      privateDraftSavedSignatureRef.current = privateDraftPayloadSignature
    }
    previousPrivateDraftMessageRef.current = privateDraft.message
  }, [privateDraft.message, privateDraftPayloadSignature])

  useEffect(() => {
    const locallyUnpersisted = dirty && privateDraftSavedSignatureRef.current !== privateDraftPayloadSignature
    onUnsavedChange?.(locallyUnpersisted || saveState === 'failed' || saveState === 'conflict' || Boolean(privateDraft.loadError))
    return () => onUnsavedChange?.(false)
  }, [dirty, onUnsavedChange, privateDraft.loadError, privateDraft.message, privateDraftPayloadSignature, saveState])

  const changeContent = (next: StructuredSolutionContent) => {
    contentRef.current = next
    setContent(next)
    if (saveState === 'failed') {
      setSaveState('idle')
      saveStateRef.current = 'idle'
    }
    setSaveError('')
  }

  const restorePrivateDraft = (draft: SolutionPrivateDraft) => {
    const restored = privateDraftContent(draft)
    if (!restored) return
    const sameAsSaved = baselineRef.current !== null && JSON.stringify(restored) === JSON.stringify(baselineRef.current)
    changeContent(restored)
    setReason(privateDraftReason(draft) || '整理逐题解析')
    privateDraft.accept(draft)
    setDraftCompare(null)
    if (sameAsSaved) void privateDraft.tombstone(draft)
  }

  const loadConflict = useCallback(async () => {
    setConflictLoading(true)
    try {
      const data = await getSolutions(materialId, new AbortController().signal)
      setConflict(data)
      setShowConflictCompare(true)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setSaveError(getErrorMessage(cause))
    } finally {
      setConflictLoading(false)
    }
  }, [materialId, onUnauthorized])

  const saveOfficialVersion = useCallback(async (saveReason: string, expectedOverride?: number, force = false) => {
    if (!writable || !contentRef.current) return false
    if (privateDraft.candidate || privateDraft.conflict !== undefined) {
      setSaveError('请先处理待恢复或冲突的私人草稿，再正式保存。')
      return false
    }
    if (saveBusyRef.current) {
      setSaveError('正式保存仍在进行，请稍后再试。')
      return false
    }
    const snapshot = contentRef.current
    const privateDraftPayloadAtStart = JSON.stringify(privateDraftPayloadRef.current)
    if (!force && expectedVersionRef.current > 0 && baselineRef.current && JSON.stringify(snapshot) === JSON.stringify(baselineRef.current)) {
      void privateDraft.tombstone()
      return true
    }
    if (saveStateRef.current === 'conflict' && expectedOverride === undefined) return false
    saveBusyRef.current = true
    setSaveState('saving')
    saveStateRef.current = 'saving'
    setSaveError('')
    const expectedVersion = expectedOverride ?? expectedVersionRef.current
    const normalizedReason = saveReason.trim() || '整理逐题解析'
    const signature = JSON.stringify([materialId, expectedVersion, snapshot, normalizedReason])
    const requestKey = requestKeyFor(saveRequestKeyRef, signature)
    try {
      const data = await saveSolution(materialId, {
        expected_version: expectedVersion,
        request_key: requestKey,
        content: snapshot,
        reason: normalizedReason,
      }, csrfToken)
      if (!mountedRef.current) return false
      if (saveRequestKeyRef.current?.signature === signature) saveRequestKeyRef.current = null
      expectedVersionRef.current = data.revision?.version || expectedVersionRef.current
      baselineRef.current = snapshot
      setBaseline(snapshot)
      setLoadedWorkspace(data)
      setConflict(null)
      setShowConflictCompare(false)
      setSaveState('saved')
      saveStateRef.current = 'saved'
      failedSnapshotRef.current = ''
      if (JSON.stringify(contentRef.current) === JSON.stringify(snapshot)
        && JSON.stringify(privateDraftPayloadRef.current) === privateDraftPayloadAtStart) {
        void privateDraft.tombstone()
      }
      return true
    } catch (cause) {
      if (!mountedRef.current) return false
      if (isUnauthorized(cause)) onUnauthorized()
      const stale = cause instanceof ApiError && ['stale_solution', 'source_changed'].includes(cause.code)
      if (stale) {
        failedSnapshotRef.current = JSON.stringify(snapshot)
        setSaveState('conflict')
        saveStateRef.current = 'conflict'
        void loadConflict()
      } else {
        failedSnapshotRef.current = JSON.stringify(snapshot)
        setSaveState('failed')
        saveStateRef.current = 'failed'
      }
      setSaveError(getErrorMessage(cause))
      return false
    } finally {
      saveBusyRef.current = false
    }
  }, [csrfToken, loadConflict, materialId, onUnauthorized, privateDraft.candidate, privateDraft.conflict, privateDraft.tombstone, setLoadedWorkspace, writable])

  useEffect(() => {
    if (historyId === null) {
      setHistory({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    setHistory({ status: 'loading' })
    getSolutionRevision(historyId, controller.signal).then((response) => {
      setHistory({ status: 'loaded', revision: response.revision })
    }).catch((cause: unknown) => {
      if (cause instanceof DOMException && cause.name === 'AbortError') return
      if (isUnauthorized(cause)) onUnauthorized()
      setHistory({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => controller.abort()
  }, [historyId, onUnauthorized])

  const processing = remote.status === 'loaded' && mergeOutputs(olderOutputs, remote.data.outputs).some((output) => outputIsProcessing(output.state))
  useEffect(() => {
    if (!processing) {
      setPollError('')
      return
    }
    const controller = new AbortController()
    let active = true
    let timer = 0
    const poll = async () => {
      try {
        const latest = await getSolutions(materialId, controller.signal)
        if (!active) return
        const latestIds = new Set(latest.outputs.map((output) => output.id))
        const olderProcessing = olderOutputs.filter((output) => outputIsProcessing(output.state) && !latestIds.has(output.id))
        const refreshedOlder = await Promise.all(olderProcessing.map(async (output) => {
          const response = await getSolutionOutput(output.id, controller.signal)
          return response.output
        }))
        if (!active) return
        setRemote((current) => current.status === 'loaded' ? { status: 'loaded', data: { ...current.data, outputs: latest.outputs, output_next_before: latest.output_next_before } } : current)
        if (refreshedOlder.length) setOlderOutputs((current) => mergeOutputs(current, refreshedOlder))
        const visibleLatest = mergeOutputs(mergeOutputs(olderOutputs, refreshedOlder), latest.outputs)
        if (visibleLatest.some((output) => outputIsProcessing(output.state))) timer = window.setTimeout(() => void poll(), 3000)
      } catch (cause) {
        if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
        if (isUnauthorized(cause)) {
          onUnauthorized()
          return
        }
        setPollError(getErrorMessage(cause))
      }
    }
    timer = window.setTimeout(() => void poll(), pollRetry ? 0 : 3000)
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [materialId, onUnauthorized, olderOutputs, pollRetry, processing])

  const runSolutionAction = async (nextAction: ActionName) => {
    if (!content || !writable || action || !reason.trim()) return
    if (nextAction === 'confirm' && !content.questions.length) return
    if (nextAction === 'generate' && !contentHasMinimumForGeneration(content)) return
    setActionError('')
    const actionReason = reason.trim()
    setAction(nextAction)
    try {
      const saved = await saveOfficialVersion(actionReason, undefined, false)
      if (!saved) return
      const expectedVersion = expectedVersionRef.current
      const signature = JSON.stringify([materialId, nextAction, expectedVersion, contentRef.current, actionReason])
      const requestKey = requestKeyFor(actionRequestKeyRef, signature)
      const data = await solutionAction(materialId, {
        action: nextAction,
        expected_version: expectedVersion,
        request_key: requestKey,
        reason: actionReason,
      }, csrfToken)
      if (actionRequestKeyRef.current?.signature === signature) actionRequestKeyRef.current = null
      setLoadedWorkspace(data)
      if (data.revision) expectedVersionRef.current = data.revision.version
      if (nextAction === 'generate') {
        setExpandedOutputId(mergeOutputs(olderOutputs, data.outputs)[0]?.id || null)
        setActivePanel('outputs')
      }
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setActionError(getErrorMessage(cause))
    } finally {
      setAction(null)
    }
  }

  const outputAction = async (output: SolutionOutput, nextAction: SolutionOutputActionInput['action'], checks?: SolutionOutput['checks']) => {
    if (!writable) return
    setOutputActionError('')
    let keyState = outputActionKeysRef.current.get(output.id)
    if (!keyState) {
      keyState = { current: null }
      outputActionKeysRef.current.set(output.id, keyState)
    }
    const actionReason = reason.trim() || '检查逐题解析输出'
    const expectedVersion = output.version
    const signature = JSON.stringify([output.id, nextAction, expectedVersion, actionReason, checks ?? null])
    const requestKey = requestKeyFor(keyState, signature)
    try {
      const data = await solutionOutputAction(output.id, {
        action: nextAction,
        expected_version: expectedVersion,
        request_key: requestKey,
        reason: actionReason,
        ...(checks ? { checks } : {}),
      }, csrfToken)
      if (keyState.current?.signature === signature) keyState.current = null
      setLoadedWorkspace(data)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setOutputActionError(getErrorMessage(cause))
    }
  }

  const updateOutputCheck = (output: SolutionOutput, name: keyof SolutionOutput['checks'], patch: Partial<SolutionOutput['checks'][typeof name]>) => {
    const current = checksDraft[output.id] || output.checks
    setChecksDraft({ ...checksDraft, [output.id]: { ...current, [name]: { ...current[name], ...patch } } })
  }

  const loadEarlierHistory = useCallback(async () => {
    if (historyBefore === null || historyPageBusyRef.current) return
    historyPageBusyRef.current = true
    setHistoryPageLoading(true)
    setHistoryPageError('')
    const controller = new AbortController()
    historyPageControllerRef.current = controller
    try {
      const result = await getSolutionHistory(materialId, historyBefore, controller.signal)
      if (!mountedRef.current) return
      setOlderHistory((current) => mergeHistory(current, result.history))
      setOlderNodes((current) => mergeNodes(current, result.nodes))
      setHistoryBefore(result.history_next_before)
    } catch (cause) {
      if (!mountedRef.current || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setHistoryPageError(getErrorMessage(cause))
    } finally {
      if (historyPageControllerRef.current === controller) historyPageControllerRef.current = null
      historyPageBusyRef.current = false
      if (mountedRef.current) setHistoryPageLoading(false)
    }
  }, [historyBefore, materialId, onUnauthorized])

  const loadEarlierOutputs = useCallback(async () => {
    if (outputBefore === null || outputPageBusyRef.current) return
    outputPageBusyRef.current = true
    setOutputPageLoading(true)
    setOutputPageError('')
    const controller = new AbortController()
    outputPageControllerRef.current = controller
    try {
      const result = await getSolutionOutputs(materialId, outputBefore, controller.signal)
      if (!mountedRef.current) return
      setOlderOutputs((current) => mergeOutputs(current, result.outputs))
      setOutputBefore(result.output_next_before)
    } catch (cause) {
      if (!mountedRef.current || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setOutputPageError(getErrorMessage(cause))
    } finally {
      if (outputPageControllerRef.current === controller) outputPageControllerRef.current = null
      outputPageBusyRef.current = false
      if (mountedRef.current) setOutputPageLoading(false)
    }
  }, [materialId, onUnauthorized, outputBefore])

  if (remote.status === 'loading') return <LoadingState label='正在读取逐题解析草稿、原图来源和文档历史…' />
  if (remote.status === 'error') return <RetryState title='无法读取逐题解析' message={remote.message} onRetry={() => setRetry((value) => value + 1)} />
  if (content === null) return <LoadingState label='正在读取逐题解析草稿、原图来源和文档历史…' />

  const data = remote.data
  const versionHistory = mergeHistory(data.history, olderHistory)
  const outputs = mergeOutputs(olderOutputs, data.outputs)
  const compareWorkspace = { ...data, nodes: mergeNodes(olderNodes, data.nodes) }
  const canGenerate = Boolean(content && contentHasMinimumForGeneration(content))
  const hasPrivateResolution = Boolean(privateDraft.candidate) || privateDraft.conflict !== undefined
  const candidateBaseChanged = Boolean(privateDraft.candidate && privateDraft.candidate.base_stamp !== baseStamp)

  return <div className='space-y-5'>
    <div className='flex flex-wrap items-start justify-between gap-3'>
      <div><h1 className='text-2xl font-semibold'>{data.material.title} · 逐题解析</h1><p className='mt-1 text-sm text-muted-foreground'>按步骤整理讲义解法。解析文档与学习者真实作答分别记录，生成答案不会认定已经掌握。</p></div>
      <Button type='button' variant='outline' onClick={onBack}>返回文档中心</Button>
    </div>

    {!writable ? <p className='rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground'>当前为只读访问；可以浏览历史版本和已生成文档。</p> : null}
    {data.revision?.confirmed && !dirty ? <p className='rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-950'>当前正式版本已明确确认。修改并保存后会形成新的版本。</p> : null}

    {writable && privateDraft.loadError ? <p role='alert' className='rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950'>私人草稿暂时无法读取：{privateDraft.loadError}。当前页面内容仍保留；请先重试页面，解决后再编辑或正式保存。</p> : null}
    {privateDraft.message ? <p role={privateDraft.message.includes('未保存') || privateDraft.message.includes('未清理') ? 'alert' : 'status'} className='text-sm'>{privateDraft.message}</p> : null}

    {writable && privateDraft.candidate ? <Card className='border-amber-300'>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>发现未处理的私人草稿</CardTitle><CardDescription>这份内容不会进入正式历史。请比较后选择恢复或丢弃；页面暂不自动覆盖它。</CardDescription></CardHeader>
      <CardContent className='space-y-3 pt-4'>
        <p className='text-sm'>保存时间：{privateDraft.candidate.updated_at}{privateDraftReason(privateDraft.candidate) ? ` · ${privateDraftReason(privateDraft.candidate)}` : ''}</p>
        {candidateBaseChanged ? <p className='text-sm text-amber-900'>保存这份私人草稿后，正式版本或原图来源已有变化。建议先比较，再决定是否恢复。</p> : null}
        {!privateCandidateContent ? <p role='alert' className='text-sm text-destructive'>这份私人草稿内容无法识别；可以将它清理后继续。</p> : null}
        <div className='flex flex-wrap gap-2'>
          {privateCandidateContent ? <Button type='button' size='sm' variant='outline' onClick={() => setDraftCompare({ title: `私人草稿 · ${privateDraft.candidate?.updated_at || ''}`, content: privateCandidateContent })}>比较内容</Button> : null}
          {privateCandidateContent ? <Button type='button' size='sm' onClick={() => restorePrivateDraft(privateDraft.candidate!)}>恢复私人草稿</Button> : null}
          <Button type='button' size='sm' variant='outline' onClick={() => void privateDraft.tombstone(privateDraft.candidate || undefined)}>丢弃这份私人草稿</Button>
        </div>
      </CardContent>
    </Card> : null}

    {writable && privateDraft.conflict !== undefined ? <Card className='border-amber-300'>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>私人草稿有另一个窗口的更新</CardTitle><CardDescription>本页内容仍保留。选择比较、恢复较新的内容，或明确保留本页继续。</CardDescription></CardHeader>
      <CardContent className='space-y-3 pt-4'>
        {!privateDraft.conflict ? <p role='alert' className='text-sm text-amber-900'>另一个窗口的私人草稿已清理或暂时不可读取。</p> : null}
        <div className='flex flex-wrap gap-2'>
          {privateConflictContent && privateDraft.conflict ? <Button type='button' size='sm' variant='outline' onClick={() => setDraftCompare({ title: `另一个窗口的草稿 · ${privateDraft.conflict?.updated_at || ''}`, content: privateConflictContent })}>比较内容</Button> : null}
          {privateDraft.conflict && privateConflictContent ? <Button type='button' size='sm' onClick={() => restorePrivateDraft(privateDraft.conflict!)}>恢复较新的私人草稿</Button> : null}
          {privateDraft.conflict ? <Button type='button' size='sm' variant='outline' onClick={() => void privateDraft.tombstone(privateDraft.conflict || undefined)}>丢弃另一个窗口的草稿</Button> : null}
          <Button type='button' size='sm' variant='outline' onClick={() => {
            if (!dirty && privateDraft.conflict) void privateDraft.tombstone(privateDraft.conflict)
            else privateDraft.keepCurrent()
          }}>保留本页内容并继续</Button>
        </div>
      </CardContent>
    </Card> : null}

    {draftCompare && content ? <Card><CardHeader className='flex flex-wrap items-start justify-between gap-3'><div><CardTitle className='text-base'>私人草稿比较</CardTitle><CardDescription>确认要恢复哪一侧；比较不会修改历史或当前输入。</CardDescription></div><Button type='button' size='sm' variant='outline' onClick={() => setDraftCompare(null)}>关闭比较</Button></CardHeader><CardContent><ContentCompare leftTitle={draftCompare.title} left={draftCompare.content} rightTitle='当前页面内容' right={content} workspace={compareWorkspace} /></CardContent></Card> : null}

    <nav aria-label='解析工作区' className='flex flex-wrap gap-2 rounded-xl border bg-muted/10 p-2'>
      {([['editor', '编辑讲解'], ['outputs', '生成文件'], ['history', '历史版本']] as const).map(([panel, label]) => <Button key={panel} type='button' size='sm' variant={activePanel === panel ? 'default' : 'outline'} aria-pressed={activePanel === panel} onClick={() => setActivePanel(panel)}>{label}</Button>)}
    </nav>

    <section id='solution-editor-panel' aria-label='编辑讲解' hidden={activePanel !== 'editor'} className='space-y-5'>
    {writable ? <Card>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>检查并保存</CardTitle><CardDescription>编辑时只自动保存私人草稿。选择“保存为新版本”才写入正式历史；确认或生成会先保存当前内容，再继续操作。</CardDescription></CardHeader>
      <CardContent className='flex flex-wrap items-end gap-3 p-4'>
        <label className='min-w-56 flex-1 text-sm font-medium'>本次保存依据<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <Button type='button' variant='outline' disabled={saveState === 'saving' || !reason.trim() || hasPrivateResolution || Boolean(privateDraft.loadError)} onClick={() => void saveOfficialVersion(reason, undefined, true)}>{saveState === 'saving' ? '正在保存正式版本…' : '保存为新版本'}</Button>
        <Button type='button' variant='outline' disabled={action !== null || saveState === 'saving' || !content.questions.length || !reason.trim() || hasPrivateResolution || Boolean(privateDraft.loadError)} onClick={() => void runSolutionAction('confirm')}>{action === 'confirm' ? '正在保存并确认…' : '明确确认解析'}</Button>
        <Button type='button' disabled={action !== null || saveState === 'saving' || !canGenerate || !reason.trim() || hasPrivateResolution || Boolean(privateDraft.loadError)} onClick={() => void runSolutionAction('generate')}>{action === 'generate' ? '正在保存并创建文档…' : '生成 PDF / Word'}</Button>
        <p className='w-full text-xs text-muted-foreground'>生成需要每题至少有一个小问和原图来源，并选择输出格式；确认与生成请求仍会检查题目、知识和方法是否属于当前已发布版本。</p>
        {saveState === 'saving' ? <p role='status' className='w-full text-sm'>正在保存正式解析版本…</p> : null}
        {saveState === 'saved' ? <p role='status' className='w-full text-sm text-emerald-800'>已保存为版本 {data.revision?.version || 0}。{dirty ? '保存后有新的输入，仍在作为私人草稿保存。' : ''}</p> : null}
        {saveState === 'failed' ? <p role='alert' className='w-full text-sm text-amber-900'>{saveError} 本地输入仍保留；可修改后重试或再次保存。</p> : null}
        {saveState === 'conflict' ? <div role='alert' className='w-full space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950'>
          <p>{saveError} 本地输入仍保留，未被服务器内容覆盖。</p>
          <div className='flex flex-wrap gap-2'><Button type='button' size='sm' variant='outline' disabled={conflictLoading} onClick={() => void loadConflict()}>{conflictLoading ? '读取最新版本…' : '读取最新版本作对照'}</Button>
            {conflict?.revision ? <Button type='button' size='sm' variant='outline' onClick={() => void saveOfficialVersion('基于最新版本继续整理', conflict.revision?.version, true)}>保留本页输入，另存为版本 {conflict.revision.version + 1}</Button> : null}</div>
        </div> : null}
        {actionError ? <p role='alert' className='w-full text-sm text-destructive'>{actionError}</p> : null}
      </CardContent>
    </Card> : null}

    {showConflictCompare && conflict?.revision?.content && content ? <Card className='border-amber-300'><CardHeader className='flex flex-wrap items-start justify-between gap-3'><div><CardTitle className='text-base'>本页输入与服务器最新版本</CardTitle><CardDescription>先检查差异，再决定是否将本页输入另存为下一版本；历史内容不会被覆盖。</CardDescription></div><Button type='button' size='sm' variant='outline' onClick={() => setShowConflictCompare(false)}>关闭比较</Button></CardHeader><CardContent><ContentCompare leftTitle='服务器版本' left={conflict.revision.content} rightTitle='本页输入' right={content} workspace={compareWorkspace} /></CardContent></Card> : null}

    <section aria-labelledby='solution-edit-heading' className='space-y-3'><div><h2 id='solution-edit-heading' className='text-xl font-semibold'>一、整理解析</h2><p className='mt-1 text-sm text-muted-foreground'>先核对题干和原图来源，再按步骤填写文字、公式与图示。</p></div>
      <SolutionEditor content={content} workspace={data} materialId={materialId} csrfToken={csrfToken} canWrite={writable && action === null} onChange={changeContent} onAssetsChanged={(assets) => setRemote((current) => current.status === 'loaded' ? { status: 'loaded', data: { ...current.data, assets: mergeAssets(current.data.assets, assets) } } : current)} onUnauthorized={onUnauthorized} />
    </section>
    </section>

    <section id='solution-history-panel' aria-label='历史版本' hidden={activePanel !== 'history'} className='space-y-5'>
    {historyId !== null ? <Card><CardHeader className='flex flex-wrap items-start justify-between gap-3'><div><CardTitle className='text-base'>历史版本对照</CardTitle><CardDescription>{history.status === 'loading' ? '正在读取该版本的完整内容…' : history.status === 'loaded' ? `版本 ${history.revision?.version} · ${history.revision?.author} · ${history.revision?.reason}` : history.message || '读取失败'}</CardDescription></div><Button type='button' variant='outline' size='sm' onClick={() => setHistoryId(null)}>关闭</Button></CardHeader><CardContent>{history.status === 'loaded' && history.revision?.content ? <ContentCompare leftTitle={`历史版本 ${history.revision.version}`} left={history.revision.content} rightTitle='当前编辑内容' right={content} workspace={compareWorkspace} /> : null}</CardContent></Card> : null}
    <Card>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>二、版本历史</CardTitle><CardDescription>历史列表只显示摘要；打开版本可对照完整题目内容。历史版本保持原样。</CardDescription></CardHeader>
      <CardContent className='space-y-3 pt-4'>
        {versionHistory.length === 0 ? <EmptyState title='还没有保存版本' detail='首次保存后会在这里保留版本和依据。' /> : <div className='space-y-2'>
          {versionHistory.map((item) => <div key={item.id} className='flex flex-wrap items-center justify-between gap-3 rounded-md border p-3'>
            <div><p className='font-medium'>版本 {item.version} · {item.author}</p><p className='mt-1 text-xs text-muted-foreground'>{item.created_at} · {item.reason}{item.confirmed ? ' · 已确认' : ''}</p></div>
            <Button type='button' size='sm' variant='outline' onClick={() => setHistoryId(item.id)}>打开并对照</Button>
          </div>)}
        </div>}
        {historyPageError ? <div className='flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950' role='alert'><p className='min-w-0 flex-1'>读取更早版本失败：{historyPageError}</p><Button type='button' size='sm' variant='outline' disabled={historyPageLoading} onClick={() => void loadEarlierHistory()}>重试读取更早版本</Button></div> : null}
        {historyBefore !== null ? <Button type='button' size='sm' variant='outline' disabled={historyPageLoading} onClick={() => void loadEarlierHistory()}>{historyPageLoading ? '正在读取更早版本…' : '读取更早版本'}</Button> : null}
      </CardContent>
    </Card>
    </section>

    <section id='solution-outputs-panel' aria-label='生成文件' hidden={activePanel !== 'outputs'} className='space-y-5'>
    <Card>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>三、生成与检查</CardTitle><CardDescription>生成任务会检查进度；完成后可预览文档并记录内容、公式与版式检查。</CardDescription></CardHeader>
      <CardContent className='space-y-4 pt-4'>
        {outputActionError ? <p role='alert' className='rounded-md bg-amber-50 p-3 text-sm text-amber-950'>{outputActionError}</p> : null}
        {pollError ? <div role='alert' className='flex flex-wrap items-center gap-3 rounded-md bg-amber-50 p-3 text-sm text-amber-950'><p className='min-w-0 flex-1'>读取输出任务状态失败：{pollError}。自动轮询已暂停。</p><Button type='button' size='sm' variant='outline' onClick={() => { setPollError(''); setPollRetry((value) => value + 1) }}>重试读取状态</Button></div> : null}
        {outputs.length === 0 ? <EmptyState title='还没有生成文档' detail='先在“编辑讲解”中保存解析草稿并生成文档。' /> : outputs.map((output) => <OutputCard key={output.id} output={output} expanded={expandedOutputId === output.id} onToggleExpanded={() => setExpandedOutputId((current) => current === output.id ? null : output.id)} checks={checksDraft[output.id] || output.checks} writable={writable} onCheckChange={(name, patch) => updateOutputCheck(output, name, patch)} onAction={(nextAction, checks) => void outputAction(output, nextAction, checks)} />)}
        {outputPageError ? <div className='flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950' role='alert'><p className='min-w-0 flex-1'>读取更早文档失败：{outputPageError}</p><Button type='button' size='sm' variant='outline' disabled={outputPageLoading} onClick={() => void loadEarlierOutputs()}>重试读取更早文档</Button></div> : null}
        {outputBefore !== null ? <Button type='button' size='sm' variant='outline' disabled={outputPageLoading} onClick={() => void loadEarlierOutputs()}>{outputPageLoading ? '正在读取更早文档…' : '读取更早文档'}</Button> : null}
      </CardContent>
    </Card>
    </section>
  </div>
}

function OutputCard({ output, expanded, onToggleExpanded, checks, writable, onCheckChange, onAction }: {
  output: SolutionOutput
  expanded: boolean
  onToggleExpanded: () => void
  checks: SolutionOutput['checks']
  writable: boolean
  onCheckChange: (name: keyof SolutionOutput['checks'], patch: Partial<SolutionOutput['checks'][keyof SolutionOutput['checks']]>) => void
  onAction: (action: SolutionOutputActionInput['action'], checks?: SolutionOutput['checks']) => void
}) {
  const allNotesPresent = Object.values(checks).every((check) => check.status === 'not_tested' || Boolean(check.notes.trim()))
  const checkNames: Array<[keyof SolutionOutput['checks'], string]> = [
    ['content', '内容与来源'], ['math', '数学正确性'], ['pdf_visual', 'PDF 页面版式'], ['word_pc', 'Windows Word 实机'], ['word_macos', 'macOS Word 实机'],
  ]
  return <article className='rounded-lg border'>
    <header className='flex flex-wrap items-start justify-between gap-3 border-b p-3'>
      <div><h3 className='font-semibold'>{output.state_label} · 版本 {output.revision_version}</h3><p className='mt-1 text-sm text-muted-foreground'>{output.message || `创建于 ${output.created_at}`}</p></div>
      <div className='flex flex-wrap gap-2'>
        <Button type='button' size='sm' variant='outline' onClick={onToggleExpanded}>{expanded ? '收起输出' : '查看输出'}</Button>
        {writable && ['queued', 'running'].includes(output.state) ? <Button type='button' size='sm' variant='outline' onClick={() => onAction('cancel')}>取消生成</Button> : null}
        {writable && output.state === 'failed' ? <Button type='button' size='sm' variant='outline' onClick={() => onAction('retry')}>重试生成</Button> : null}
      </div>
    </header>
    {expanded ? <div className='space-y-4 p-3'>
      {output.state === 'queued' || output.state === 'running' ? <p role='status' className='text-sm text-muted-foreground'>文档仍在后台生成；本页会每 3 秒读取一次状态。离开页面后轮询将停止。</p> : null}
      {output.documents.map((document) => <section key={document.id} className='space-y-3 rounded-md border p-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'><div><h4 className='font-medium'>{document.title}</h4><p className='text-xs text-muted-foreground'>{organizationLabel(document.organization)} · {document.page_count} 页</p></div>
          {document.docx_url ? <a className='rounded-md border px-3 py-2 text-sm font-medium underline-offset-4 hover:bg-muted hover:underline' href={safeLink(document.docx_url) || undefined} download>下载 Word</a> : null}</div>
        {document.pdf_url ? <div className='space-y-2'><h5 className='text-sm font-medium'>PDF 预览</h5><iframe title={`${document.title} PDF 预览`} src={safeLink(document.pdf_url) || undefined} className='h-[32rem] w-full rounded-md border bg-muted' /></div> : null}
        {document.previews.length ? <div className='grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>{document.previews.map((preview, index) => <figure key={`${preview}:${index}`} className='overflow-hidden rounded-md border'><img src={safeLink(preview) || undefined} alt={`${document.title} 第 ${index + 1} 页预览`} className='h-auto w-full' loading='lazy' /><figcaption className='px-2 py-1 text-xs text-muted-foreground'>第 {index + 1} 页</figcaption></figure>)}</div> : null}
      </section>)}
      {output.documents.length === 0 && !outputIsProcessing(output.state) ? <p className='text-sm text-muted-foreground'>当前输出没有可预览的文档。</p> : null}
      {output.zip_url ? <a className='inline-flex rounded-md border px-3 py-2 text-sm font-medium underline-offset-4 hover:bg-muted hover:underline' href={safeLink(output.zip_url) || undefined} download>下载全部 ZIP</a> : null}
      {writable && output.state === 'output_check' ? <Disclosure title='逐项检查输出' description='五项检查独立记录；Word 的 Windows 与 macOS 实机检查保持“未测试”，除非确实打开验证。' className='border-primary/30 bg-primary/[0.03]'>
        <div className='grid gap-3 lg:grid-cols-2'>{checkNames.map(([name, label]) => <div key={name} className='rounded-md border bg-background p-3'>
          <label className='text-sm font-medium'>{label}<select className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' value={checks[name].status} onChange={(event) => onCheckChange(name, { status: event.target.value as typeof checks[typeof name]['status'] })}><option value='not_tested'>未测试</option><option value='pass'>通过</option><option value='fail'>未通过</option></select></label>
          <label className='mt-2 block text-xs font-medium'>检查依据或备注<textarea className='mt-1 min-h-16 w-full rounded-md border bg-background px-3 py-2 text-sm' maxLength={2000} value={checks[name].notes} onChange={(event) => onCheckChange(name, { notes: event.target.value })} /></label>
        </div>)}</div>
        <Button type='button' disabled={!allNotesPresent} onClick={() => onAction('check', checks)}>保存检查记录</Button>
        {!allNotesPresent ? <p className='text-xs text-amber-900'>标为“通过”或“未通过”时请填写检查依据；“未测试”可以保留空备注。</p> : null}
      </Disclosure> : null}
    </div> : null}
  </article>
}

type CompareWorkspace = Pick<SolutionWorkspaceResponse, 'pages' | 'nodes' | 'assets' | 'questions'>

function ContentCompare({ left, leftTitle, right, rightTitle, workspace }: { left: AnySolutionContent; leftTitle: string; right: AnySolutionContent; rightTitle: string; workspace: CompareWorkspace }) {
  const rightById = new Map(right.questions.map((question) => [question.id, question]))
  const leftById = new Map(left.questions.map((question) => [question.id, question]))
  const questionIds = Array.from(new Set([...left.questions.map((question) => question.id), ...right.questions.map((question) => question.id)]))
  return <div className='space-y-3'>
    <div className='grid gap-3 md:grid-cols-2'><ReviewColumn title={leftTitle} content={left} /><ReviewColumn title={rightTitle} content={right} /></div>
    {questionIds.map((id) => {
      const old = leftById.get(id)
      const current = rightById.get(id)
      return <section key={id} className='rounded-md border p-3'>
        <h4 className='font-semibold'>{old?.number || current?.number || '未编号题目'}{old?.title || current?.title ? ` · ${old?.title || current?.title}` : ''}</h4>
        <div className='mt-2 grid gap-3 md:grid-cols-2'><QuestionReview title={leftTitle} question={old} content={left} workspace={workspace} /><QuestionReview title={rightTitle} question={current} content={right} workspace={workspace} /></div>
      </section>
    })}
  </div>
}

function ReviewColumn({ title, content }: { title: string; content: AnySolutionContent }) {
  return <dl className='grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-md border bg-muted/10 p-3 text-sm'>
    <dt className='font-medium'>{title}</dt><dd>{content.title || '空标题'}</dd>
    <dt className='text-muted-foreground'>讲次</dt><dd>{content.lectures.map((lecture) => lecture.title).join('、') || '无'}</dd>
    <dt className='text-muted-foreground'>题目</dt><dd>{content.questions.length} 道</dd>
    <dt className='text-muted-foreground'>输出设置</dt><dd>{outputPreferenceSummary(content)}</dd>
  </dl>
}

function QuestionReview({ title, question, content, workspace }: { title: string; question: AnySolutionContent['questions'][number] | undefined; content: AnySolutionContent; workspace: CompareWorkspace }) {
  if (!question) return <div className='rounded-md bg-muted/20 p-3 text-sm text-muted-foreground'>{title}：此题不存在</div>
  const statusLabels: Record<AnySolutionContent['questions'][number]['statement']['status'], string> = { complete: '已核对完整', partial: '部分记录', unknown: '未知 / 待核对' }
  const relationLabels: Record<AnySolutionContent['questions'][number]['links'][number]['relation'], string> = { knowledge: '知识条目', primary_method: '主要方法', secondary_method: '辅助方法', question_type: '题型' }
  const roleLabels: Record<AnySolutionContent['questions'][number]['figures'][number]['role'], string> = { question: '题面图', method: '解法图', answer: '答案图' }
  const correctionLabels: Record<AnySolutionContent['questions'][number]['corrections'][number]['kind'], string> = { printing_error: '资料印刷错误', naming: '命名调整', draft_correction: '解析草稿订正' }
  const linkedQuestion = question.question_revision_id ? workspace.questions.find((item) => item.revision_id === question.question_revision_id) : undefined
  const linkedQuestionHref = linkedQuestion ? sameOriginHref(linkedQuestion.detail_url) : null
  const structuredQuestion = content.schema_version === 'swb.solution.v2' ? question as StructuredSolutionQuestion : null
  const stepRows: Array<{ label: string; text: string; formula: string | null; figure: SolutionFigure | null; newPage: boolean }> = structuredQuestion
    ? [...structuredQuestion.steps.map((step, index) => ({ label: `第 ${index + 1} 步`, text: step.text, formula: step.formula, figure: step.figure, newPage: step.new_page })), ...structuredQuestion.alternative_steps.map((step, index) => ({ label: `其他解法第 ${index + 1} 步`, text: step.text, formula: step.formula, figure: step.figure, newPage: step.new_page }))]
    : (question as SolutionQuestion).steps.map((text, index) => ({ label: `第 ${index + 1} 步`, text, formula: null, figure: null, newPage: false }))
  const stepFigures = stepRows.flatMap((step) => step.figure ? [step.figure] : [])
  const figures = [...question.figures, ...stepFigures]
  const rows: Array<[string, ReactNode]> = [
    ['讲次', content.lectures.find((lecture) => lecture.id === question.lecture_id)?.title || '讲次'],
    ['关联题目', linkedQuestion ? linkedQuestionHref
      ? <a className='text-primary underline underline-offset-2' href={linkedQuestionHref}>{linkedQuestion.label}</a>
      : linkedQuestion.label
      : question.question_revision_id ? '历史题目' : '未关联'],
    ['题干', <span>{solutionText(question.statement.text)} · {statusLabels[question.statement.status] || '未知状态'}</span>],
    ['原图来源', question.sources.length ? <ul className='space-y-1'>{question.sources.map((source, index) => {
      const page = workspace.pages.find((item) => item.id === source.page_id)
      const pageHref = page ? sameOriginHref(page.detail_url) : null
      return <li key={index}>{pageHref ? <a className='text-primary underline underline-offset-2' href={pageHref}>{page?.label || '资料页'}</a> : page?.label || '资料页'} · {source.region ? `原图区域 ${source.region.join(', ')} px` : '整页来源，区域未知'}</li>
    })}</ul> : '无'],
    ['小问/答案', question.parts.map((part) => `${part.label || '小问'}：${solutionText(part.statement)} → ${solutionText(part.answer)}（单位 ${solutionText(part.unit)}）`).join('；') || '无'],
    ['思路与解法', [question.thinking, question.lecture_method, question.alternative_method].map(solutionText).join(' / ')],
    ['步骤', stepRows.length ? <ol className='space-y-2'>{stepRows.map((step, index) => <li key={index} className='rounded border bg-background p-2'>
      <p className='font-medium'>{step.label}{step.newPage ? ' · 从新页开始' : ''}</p>
      {step.text ? <p className='mt-1 whitespace-pre-wrap'>{step.text}</p> : null}
      {step.formula ? <p className='mt-1 font-mono text-xs'>{step.formula}</p> : null}
      {step.figure ? <p className='mt-1 text-xs text-muted-foreground'>图示：{step.figure.caption || '已关联图示素材'}</p> : null}
    </li>)}</ol> : '无'],
    ['易错点', question.pitfalls.join('；') || '无'],
    ['公式', question.formulas.join('；') || '无'],
    ['知识关联', question.links.length ? <ul className='space-y-1'>{question.links.map((link, index) => {
      const node = workspace.nodes.find((item) => item.revision_id === link.revision_id)
      const nodeHref = node ? sameOriginHref(node.detail_url) : null
      return <li key={index}>{relationLabels[link.relation] || '其他关联'}：{nodeHref ? <a className='text-primary underline underline-offset-2' href={nodeHref}>{node?.label || '历史条目'}</a> : node?.label || '历史条目'}</li>
    })}</ul> : '无'],
    ['图示', figures.length ? <ul className='space-y-2'>{figures.map((figure, index) => {
      const asset = workspace.assets.find((item) => item.id === figure.asset_id)
      const src = asset ? sameOriginHref(asset.url) : null
      const caption = figure.caption || asset?.label || '图示素材'
      return <li key={index} className='space-y-1'>{src ? <img src={src} alt={caption} className='max-h-40 max-w-full rounded border bg-white object-contain' loading='lazy' /> : null}<span>{roleLabels[figure.role] || '其他用途'}：{caption} · {figure.width_mm} mm</span></li>
    })}</ul> : '无'],
    ['订正依据', question.corrections.map((item) => `${correctionLabels[item.kind] || '订正'}：${item.original} → ${item.replacement}（${item.basis}）`).join('；') || '无'],
    ['待核实事项', question.unknowns.join('；') || '无'],
  ]
  return <dl className='grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-2 rounded-md bg-muted/10 p-3 text-sm'>
    {rows.map(([label, value]) => <div key={label} className='contents'><dt className='font-medium'>{label}</dt><dd className='break-words whitespace-pre-wrap'>{value}</dd></div>)}
  </dl>
}

function mergeHistory(current: SolutionWorkspaceResponse['history'], incoming: SolutionWorkspaceResponse['history']) {
  const items = new Map<number, SolutionWorkspaceResponse['history'][number]>()
  for (const item of [...current, ...incoming]) items.set(item.id, item)
  return [...items.values()].sort((left, right) => right.version - left.version)
}

function mergeNodes(current: SolutionWorkspaceResponse['nodes'], incoming: SolutionWorkspaceResponse['nodes']) {
  const nodes = new Map<string, SolutionWorkspaceResponse['nodes'][number]>()
  for (const item of [...current, ...incoming]) nodes.set(item.revision_id, item)
  return [...nodes.values()]
}

function mergeOutputs(current: SolutionOutput[], incoming: SolutionOutput[]) {
  const outputs = new Map<string, SolutionOutput>()
  for (const item of [...current, ...incoming]) outputs.set(item.id, item)
  return [...outputs.values()].sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id.localeCompare(left.id))
}

function mergeAssets(current: SolutionWorkspaceResponse['assets'], incoming: SolutionWorkspaceResponse['assets']) {
  const assets = new Map<string, SolutionWorkspaceResponse['assets'][number]>()
  for (const asset of [...current, ...incoming]) assets.set(asset.id, asset)
  return [...assets.values()]
}

function privateDraftContent(draft: SolutionPrivateDraft | null) {
  const payload = draft?.payload
  if (!isRecord(payload) || !('content' in payload)) return null
  const content = payload.content
  if (!isAnySolutionContent(content)) return null
  return toStructuredSolutionContent(content)
}

function privateDraftReason(draft: SolutionPrivateDraft | null) {
  const payload: unknown = draft?.payload
  return isRecord(payload) && typeof payload.reason === 'string' ? payload.reason : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function outputPreferenceSummary(content: AnySolutionContent) {
  const labels: Record<keyof AnySolutionContent['outputs'], string> = { per_question: '逐题', per_lecture: '按讲次', combined: '合并' }
  return Object.entries(content.outputs).flatMap(([organization, formats]) => formats.map((format) => `${labels[organization as keyof AnySolutionContent['outputs']]} ${format.toUpperCase()}`)).join('、') || '无'
}

function organizationLabel(value: SolutionOutput['documents'][number]['organization']) {
  if (value === 'per_question') return '逐题'
  if (value === 'per_lecture') return '按讲次'
  return '合并'
}

function safeLink(value: string | null) {
  return sameOriginHref(value)
}
