import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, getErrorMessage } from '../../api'
import { EmptyState, isUnauthorized, LoadingState, RetryState } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { WorkspaceHeading, WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import type { CompanionConfig, CompanionOutput, CompanionResponse, CompanionWorkspaceProps, RevisionSummary } from './types'
import { OutputCard } from './output-card'
import type { SolutionWorkspaceResponse } from '../../types'
import type { PrivateDraft } from '../drafts/client'
import { usePrivateDraft } from '../drafts/use-private-draft'
import { requestKeyFor, type RequestKeyState } from '../materials/request-keys'
import { outputIsProcessing } from '../solutions/model'

type Remote<T> = { status: 'loading' } | { status: 'loaded'; data: T } | { status: 'error'; message: string }
type SaveState = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict'
type ActionName = 'confirm' | 'generate'
type SolutionTab = 'editor' | 'outputs' | 'history'

function normalizeSolutionTab(value: string | undefined, legacyPanel: 'editor' | 'outputs'): SolutionTab {
  if (value === 'outputs' || value === 'history' || value === 'editor') return value
  return legacyPanel
}

export function CompanionWorkspace<C, O extends CompanionOutput, W extends CompanionResponse<C, O>>({
  materialId, householdId, csrfToken, canWrite, onUnauthorized, onBack, onUnsavedChange,
  initialPanel = 'editor', initialTab, onTabChange, onScopeLoaded, config,
}: CompanionWorkspaceProps & { config: CompanionConfig<C, O, W> }) {
  type SolutionDraftPayload = { content: C; reason: string }
  type SolutionPrivateDraft = PrivateDraft<SolutionDraftPayload | { cleared: true }>
  const ContentCompare = config.compare
  const Editor = config.editor
  const privateDraftContent = (draft: SolutionPrivateDraft | null) => {
    const payload: unknown = draft?.payload
    return isRecord(payload) && config.isContent(payload.content) ? config.normalize(payload.content) : null
  }
  const [remote, setRemote] = useState<Remote<W>>({ status: 'loading' })
  const [content, setContent] = useState<C | null>(null)
  const [baseline, setBaseline] = useState<C | null>(null)
  const [draftCompare, setDraftCompare] = useState<{ title: string; content: C } | null>(null)
  const contentRef = useRef<C | null>(null)
  const baselineRef = useRef<C | null>(null)
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
  const [focusItem, setFocusItem] = useState<{ id: string } | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [saveError, setSaveError] = useState('')
  const [conflict, setConflict] = useState<W | null>(null)
  const [showConflictCompare, setShowConflictCompare] = useState(false)
  const [conflictLoading, setConflictLoading] = useState(false)
  const [reason, setReason] = useState(config.defaultReason)
  const [editorBusy, setEditorBusy] = useState(false)
  const actionBusyRef = useRef(false)
  const [action, setAction] = useState<ActionName | null>(null)
  const [actionError, setActionError] = useState('')
  const [retry, setRetry] = useState(0)
  const [historyId, setHistoryId] = useState<number | null>(null)
  const [activePanel, setActivePanel] = useState<SolutionTab>(() => normalizeSolutionTab(initialTab, initialPanel))
  const [expandedOutputId, setExpandedOutputId] = useState<string | null>(null)
  const [history, setHistory] = useState<{ status: 'idle' | 'loading' | 'loaded' | 'error'; revision?: W['revision']; message?: string }>({ status: 'idle' })
  const [olderHistory, setOlderHistory] = useState<W['history']>([])
  const [olderNodes, setOlderNodes] = useState<W['nodes']>([])
  const [historyBefore, setHistoryBefore] = useState<number | null>(null)
  const [historyPageLoading, setHistoryPageLoading] = useState(false)
  const [historyPageError, setHistoryPageError] = useState('')
  const [olderOutputs, setOlderOutputs] = useState<O[]>([])
  const [outputBefore, setOutputBefore] = useState<string | null>(null)
  const [outputPageLoading, setOutputPageLoading] = useState(false)
  const [outputPageError, setOutputPageError] = useState('')
  const [checksDraft, setChecksDraft] = useState<Record<string, O['checks']>>({})
  const [outputActionError, setOutputActionError] = useState('')
  const [pollError, setPollError] = useState('')
  const [pollRetry, setPollRetry] = useState(0)

  useEffect(() => {
    setActivePanel(normalizeSolutionTab(initialTab, initialPanel))
  }, [initialPanel, initialTab])

  const changeTab = (value: SolutionTab) => {
    setActivePanel(value)
    onTabChange?.(value)
  }

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      historyPageControllerRef.current?.abort()
      outputPageControllerRef.current?.abort()
    }
  }, [])

  const setLoadedWorkspace = useCallback((data: W, resetPageCursors = false) => {
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
    config.api.workspace(materialId, controller.signal).then((data) => {
      if (!active) return
      if (data.material.household_id && data.material.household_id !== householdId) {
        setRemote({ status: 'error', message: '这份资料属于另一个家庭，请切换到该家庭后重新打开。' })
        const prefix = config.mode === 'knowledge' ? 'knowledge-explanations' : 'solutions'
        onScopeLoaded?.({ household_id: data.material.household_id, learner_id: '' }, `/__app__/${prefix}/${encodeURIComponent(materialId)}/`)
        return
      }
      const current = config.normalize(data.revision?.content || data.initial_content)
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
  }, [config, householdId, materialId, onScopeLoaded, onUnauthorized, retry, setLoadedWorkspace])

  const dirty = useMemo(() => Boolean(content && baseline && JSON.stringify(content) !== JSON.stringify(baseline)), [baseline, content])
  const writable = canWrite && remote.status === 'loaded' && remote.data.writable
  const baseStamp = remote.status === 'loaded'
    ? JSON.stringify([remote.data.revision?.version || 0, remote.data.source_stamp || ''])
    : ''
  const privateDraftPayload = useMemo(() => ({ content: content || config.empty, reason }), [content, reason])
  const privateDraftPayloadRef = useRef(privateDraftPayload)
  privateDraftPayloadRef.current = privateDraftPayload
  const privateDraft = usePrivateDraft<SolutionDraftPayload>({
    key: `${config.mode}:${materialId}`,
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
    onUnsavedChange?.(editorBusy || saveState === 'saving' || locallyUnpersisted || saveState === 'failed' || saveState === 'conflict' || Boolean(privateDraft.loadError))
    return () => onUnsavedChange?.(false)
  }, [editorBusy, dirty, onUnsavedChange, privateDraft.loadError, privateDraft.message, privateDraftPayloadSignature, saveState])

  const changeContent = (next: C) => {
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
    setReason(privateDraftReason(draft)  || config.defaultReason)
    privateDraft.accept(draft)
    setDraftCompare(null)
    if (sameAsSaved) void privateDraft.tombstone(draft)
  }

  const loadConflict = useCallback(async () => {
    setConflictLoading(true)
    try {
      const data = await config.api.workspace(materialId, new AbortController().signal)
      if (!mountedRef.current) return
      setConflict(data)
      setShowConflictCompare(true)
    } catch (cause) {
      if (!mountedRef.current) return
      if (isUnauthorized(cause)) onUnauthorized()
      setSaveError(getErrorMessage(cause))
    } finally {
      if (mountedRef.current) setConflictLoading(false)
    }
  }, [config, materialId, onUnauthorized])

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
    const normalizedReason = saveReason.trim()  || config.defaultReason
    const signature = JSON.stringify([materialId, expectedVersion, snapshot, normalizedReason])
    const requestKey = requestKeyFor(saveRequestKeyRef, signature)
    try {
      const data = await config.api.save(materialId, {
        expected_version: expectedVersion,
        request_key: requestKey,
        content: snapshot,
        reason: normalizedReason,
      }, csrfToken)
      if (!mountedRef.current) return false
      if (saveRequestKeyRef.current?.signature === signature) saveRequestKeyRef.current = null
      const saved = data.saved_revision || data.revision
      expectedVersionRef.current = saved?.version || expectedVersionRef.current
      baselineRef.current = snapshot
      setBaseline(snapshot)
      setLoadedWorkspace(data)
      if (saved && (saved.id !== data.revision?.id || (data.saved_source_stamp && data.saved_source_stamp !== data.source_stamp))) {
        setConflict(data)
        setShowConflictCompare(true)
        setSaveState('conflict')
        saveStateRef.current = 'conflict'
        setSaveError(`本页内容已保存为版本 ${saved.version}，随后服务器版本或来源已有变化。请对照后再继续。`)
        return false
      }
      setConflict(null)
      setShowConflictCompare(false)
      setSaveState('saved')
      saveStateRef.current = 'saved'
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
        setSaveState('conflict')
        saveStateRef.current = 'conflict'
        void loadConflict()
      } else {
        setSaveState('failed')
        saveStateRef.current = 'failed'
      }
      setSaveError(getErrorMessage(cause))
      return false
    } finally {
      saveBusyRef.current = false
    }
  }, [config, csrfToken, loadConflict, materialId, onUnauthorized, privateDraft.candidate, privateDraft.conflict, privateDraft.tombstone, setLoadedWorkspace, writable])

  useEffect(() => {
    if (historyId === null) {
      setHistory({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    setHistory({ status: 'loading' })
    config.api.revision(historyId, controller.signal).then((response) => {
      if (!mountedRef.current || controller.signal.aborted) return
      setHistory({ status: 'loaded', revision: response.revision })
    }).catch((cause: unknown) => {
      if (!mountedRef.current || controller.signal.aborted) return
      if (cause instanceof DOMException && cause.name === 'AbortError') return
      if (isUnauthorized(cause)) onUnauthorized()
      setHistory({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => controller.abort()
  }, [config, historyId, onUnauthorized])

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
        const latest = await config.api.workspace(materialId, controller.signal)
        if (!active) return
        const latestIds = new Set(latest.outputs.map((output) => output.id))
        const olderProcessing = olderOutputs.filter((output) => outputIsProcessing(output.state) && !latestIds.has(output.id))
        const refreshedOlder = await Promise.all(olderProcessing.map(async (output) => {
          const response = await config.api.output(output.id, controller.signal)
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
  }, [config, materialId, onUnauthorized, olderOutputs, pollRetry, processing])

  const runSolutionAction = async (nextAction: ActionName) => {
    if (!content || !writable || actionBusyRef.current || editorBusy || !reason.trim()) return
    if (nextAction === 'confirm' && !config.hasItems(content)) return
    if (nextAction === 'generate' && !config.canGenerate(content)) return
    actionBusyRef.current = true
    setActionError('')
    const actionReason = reason.trim()
    setAction(nextAction)
    try {
      const saved = await saveOfficialVersion(actionReason, undefined, false)
      if (!saved) return
      const expectedVersion = expectedVersionRef.current
      const signature = JSON.stringify([materialId, nextAction, expectedVersion, contentRef.current, actionReason])
      const requestKey = requestKeyFor(actionRequestKeyRef, signature)
      const data = await config.api.action(materialId, {
        action: nextAction,
        expected_version: expectedVersion,
        request_key: requestKey,
        reason: actionReason,
      }, csrfToken)
      if (!mountedRef.current) return
      if (actionRequestKeyRef.current?.signature === signature) actionRequestKeyRef.current = null
      setLoadedWorkspace(data)
      if (data.command_result && data.command_result.revision_id !== data.revision?.id) {
        setConflict(data); setShowConflictCompare(true); setSaveState('conflict'); saveStateRef.current = 'conflict'
        setSaveError('本次操作已记录，随后服务器已有新版本。当前输入仍保留，请对照后再继续。')
      }
      if (nextAction === 'generate') {
        setExpandedOutputId(data.command_result?.output_id || mergeOutputs(olderOutputs, data.outputs)[0]?.id || null)
        changeTab('outputs')
      }
    } catch (cause) {
      if (!mountedRef.current) return
      if (isUnauthorized(cause)) onUnauthorized()
      if (cause instanceof ApiError && ['stale_solution', 'source_changed'].includes(cause.code)) {
        setSaveState('conflict'); saveStateRef.current = 'conflict'; setSaveError(getErrorMessage(cause)); void loadConflict()
      }
      setActionError(getErrorMessage(cause))
    } finally {
      actionBusyRef.current = false
      if (mountedRef.current) setAction(null)
    }
  }

  const outputAction = async (output: O, nextAction: 'cancel' | 'retry' | 'check', checks?: O['checks']) => {
    if (!writable) return
    setOutputActionError('')
    let keyState = outputActionKeysRef.current.get(output.id)
    if (!keyState) {
      keyState = { current: null }
      outputActionKeysRef.current.set(output.id, keyState)
    }
    const actionReason = reason.trim()  || `检查${config.title}输出`
    const expectedVersion = output.version
    const signature = JSON.stringify([output.id, nextAction, expectedVersion, actionReason, checks ?? null])
    const requestKey = requestKeyFor(keyState, signature)
    try {
      const data = await config.api.outputAction(output.id, {
        action: nextAction,
        expected_version: expectedVersion,
        request_key: requestKey,
        reason: actionReason,
        ...(checks ? { checks } : {}),
      }, csrfToken)
      if (!mountedRef.current) return
      if (keyState.current?.signature === signature) keyState.current = null
      setLoadedWorkspace(data)
    } catch (cause) {
      if (!mountedRef.current) return
      if (isUnauthorized(cause)) onUnauthorized()
      setOutputActionError(getErrorMessage(cause))
    }
  }

  const updateOutputCheck = (output: O, name: keyof O['checks'], patch: Partial<CompanionOutput['checks'][string]>) => {
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
      const result = await config.api.history(materialId, historyBefore, controller.signal)
      if (!mountedRef.current) return
      setOlderHistory((current) => mergeHistory(current, result.history))
      setOlderNodes((current) => mergeNodes(current, result.nodes))
      setHistoryBefore(result.history_next_before ?? null)
    } catch (cause) {
      if (!mountedRef.current || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setHistoryPageError(getErrorMessage(cause))
    } finally {
      if (historyPageControllerRef.current === controller) historyPageControllerRef.current = null
      historyPageBusyRef.current = false
      if (mountedRef.current) setHistoryPageLoading(false)
    }
  }, [config, historyBefore, materialId, onUnauthorized])

  const loadEarlierOutputs = useCallback(async () => {
    if (outputBefore === null || outputPageBusyRef.current) return
    outputPageBusyRef.current = true
    setOutputPageLoading(true)
    setOutputPageError('')
    const controller = new AbortController()
    outputPageControllerRef.current = controller
    try {
      const result = await config.api.outputs(materialId, outputBefore, controller.signal)
      if (!mountedRef.current) return
      setOlderOutputs((current) => mergeOutputs(current, result.outputs))
      setOutputBefore(result.output_next_before ?? null)
    } catch (cause) {
      if (!mountedRef.current || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setOutputPageError(getErrorMessage(cause))
    } finally {
      if (outputPageControllerRef.current === controller) outputPageControllerRef.current = null
      outputPageBusyRef.current = false
      if (mountedRef.current) setOutputPageLoading(false)
    }
  }, [config, materialId, onUnauthorized, outputBefore])

  if (remote.status === 'loading') return <LoadingState label={`正在读取${config.title}草稿、原图来源和文档历史…`} />
  if (remote.status === 'error') return <RetryState title={`无法读取${config.title}`} message={remote.message} onRetry={() => setRetry((value) => value + 1)} />
  if (content === null) return <LoadingState label={`正在读取${config.title}草稿、原图来源和文档历史…`} />

  const data = remote.data
  const versionHistory = mergeHistory(data.history, olderHistory)
  const outputs = mergeOutputs(olderOutputs, data.outputs)
  const compareWorkspace = { ...data, nodes: mergeNodes(olderNodes, data.nodes) }
  const canGenerate = Boolean(content && config.canGenerate(content))
  const outputSummary = content ? config.outputSummary(content) : { label: '先选择输出格式', detail: '尚未选择输出。' }
  const hasPrivateResolution = Boolean(privateDraft.candidate) || privateDraft.conflict !== undefined
  const candidateBaseChanged = Boolean(privateDraft.candidate && privateDraft.candidate.base_stamp !== baseStamp)

  return <div className='space-y-5'>
    <WorkspaceHeading title={<span className='break-words'>{data.material.title} · {config.title}</span>} actions={<Button type='button' variant='outline' onClick={onBack}>{config.mode === 'knowledge' ? '返回资料选择' : '返回文档中心'}</Button>} />
    <p className='-mt-3 text-sm text-muted-foreground'>{config.introduction}</p>

    {!writable ? <p className='rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground'>当前为只读访问；可以浏览历史版本和已生成文档。</p> : null}
    {data.revision?.confirmed && !dirty ? <p className='rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-950'>当前正式版本已明确确认。修改并保存后会形成新的版本。</p> : null}

    {writable && privateDraft.loadError ? <p role='alert' className='rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950'>私人草稿暂时无法读取，自动保存和正式保存已暂停；当前页面内容仍保留。请刷新页面后重试。</p> : null}
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

    <WorkspaceTabs id={config.mode} label='讲解工作区' tabs={[
      { value: 'editor', label: '编辑讲解' },
      { value: 'outputs', label: '生成文件', count: outputs.length },
      { value: 'history', label: '历史版本', count: versionHistory.length },
    ]} value={activePanel} onChange={(value) => changeTab(value as SolutionTab)} />

    <WorkspacePanel id={config.mode} value='editor' active={activePanel}>
    {showConflictCompare && conflict?.revision?.content && content ? <Card className='border-amber-300'><CardHeader className='flex flex-wrap items-start justify-between gap-3'><div><CardTitle className='text-base'>本页输入与服务器最新版本</CardTitle><CardDescription>先检查差异，再决定是否将本页输入另存为下一版本；历史内容不会被覆盖。</CardDescription></div><Button type='button' size='sm' variant='outline' onClick={() => setShowConflictCompare(false)}>关闭比较</Button></CardHeader><CardContent><ContentCompare leftTitle='服务器版本' left={conflict.revision.content} rightTitle='本页输入' right={content} workspace={compareWorkspace} /></CardContent></Card> : null}

    <section aria-labelledby={`${config.mode}-edit-heading`} className='space-y-3'><div><h2 id={`${config.mode}-edit-heading`} className='text-xl font-semibold'>一、整理讲解</h2><p className='mt-1 text-sm text-muted-foreground'>{config.generationHint}</p></div>
      <Editor focusItem={focusItem || undefined} content={content} workspace={data} materialId={materialId} csrfToken={csrfToken} writable={writable && action === null} onChange={changeContent} onBusyChange={setEditorBusy} onAssetsChanged={(assets) => mountedRef.current && setRemote((current) => current.status === 'loaded' ? { status: 'loaded', data: { ...current.data, assets: mergeAssets(current.data.assets, assets) } } : current)} onUnauthorized={onUnauthorized} />
    </section>
    {data.revision?.gaps?.length ? <section className='space-y-2 rounded-md border border-amber-300 p-3' aria-label='保存版本的内容检查'>
      <h3 className='font-semibold'>上次保存版本的待补项</h3><p className='text-xs text-muted-foreground'>当前输入有变化时，先保存新版本刷新检查；生成时服务端还会再次核对。</p>
      <ul className='space-y-2'>{data.revision.gaps.map((gap, index) => <li key={index} className='flex flex-wrap items-center justify-between gap-3 text-sm'><span>{gap.message}</span><Button type='button' size='sm' variant='outline' disabled={editorBusy || action !== null} onClick={() => { const id=gap.question_id || gap.knowledge_id || ''; setFocusItem({id}); if (!id) { const summary=[...document.querySelectorAll('summary')].find((item) => item.textContent?.includes('文档设置')); summary?.closest('details')?.setAttribute('open','') }; document.getElementById(`${config.mode}-edit-heading`)?.scrollIntoView({block:'start'}) }}>定位条目或文档设置</Button></li>)}</ul>
    </section> : null}
    {writable ? <Card>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>检查并保存</CardTitle><CardDescription>编辑时只自动保存私人草稿。选择“保存为新版本”才写入正式历史；确认或生成会先保存当前内容，再继续操作。</CardDescription></CardHeader>
      <CardContent className='flex flex-wrap items-end gap-3 p-4'>
        <label className='min-w-56 flex-1 text-sm font-medium'>本次保存依据<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <Button type='button' variant='outline' disabled={editorBusy || action !== null || saveState === 'saving' || !reason.trim() || hasPrivateResolution || Boolean(privateDraft.loadError)} onClick={() => void saveOfficialVersion(reason, undefined, true)}>{saveState === 'saving' ? '正在保存正式版本…' : '保存为新版本'}</Button>
        <Button type='button' variant='outline' disabled={editorBusy || action !== null || saveState === 'saving' || !config.hasItems(content) || !reason.trim() || hasPrivateResolution || Boolean(privateDraft.loadError)} onClick={() => void runSolutionAction('confirm')}>{action === 'confirm' ? '正在保存并确认…' : config.mode === 'knowledge' ? '明确确认讲解' : '明确确认解析'}</Button>
        <Button type='button' disabled={editorBusy || action !== null || saveState === 'saving' || !canGenerate || !reason.trim() || hasPrivateResolution || Boolean(privateDraft.loadError)} onClick={() => void runSolutionAction('generate')}>{action === 'generate' ? '正在保存并创建文档…' : outputSummary.label}</Button>
        <p className='w-full text-sm'>本次输出：{outputSummary.detail}</p><p className='w-full text-xs text-muted-foreground'>{config.mode === 'solution' ? '家长解析含答案与方法，不能作为无提示独立练习。' : '知识讲解用于回看结论、条件与依据。'}生成后分别审校内容、来源和文件版式；Word 实开单独记录。</p>
        {saveState === 'saving' ? <p role='status' className='w-full text-sm'>{config.mode === 'knowledge' ? '正在保存正式知识讲解版本…' : '正在保存正式解析版本…'}</p> : null}
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

    </WorkspacePanel>

    <WorkspacePanel id={config.mode} value='history' active={activePanel}>
    {historyId !== null ? <Card><CardHeader className='flex flex-wrap items-start justify-between gap-3'><div><CardTitle className='text-base'>历史版本对照</CardTitle><CardDescription>{history.status === 'loading' ? '正在读取该版本的完整内容…' : history.status === 'loaded' ? `版本 ${history.revision?.version} · ${history.revision?.author} · ${history.revision?.reason}` : history.message || '读取失败'}</CardDescription></div><Button type='button' variant='outline' size='sm' onClick={() => setHistoryId(null)}>关闭</Button></CardHeader><CardContent>{writable && history.status === 'loaded' && history.revision ? <Button type='button' size='sm' variant='outline' disabled={hasPrivateResolution || editorBusy || action !== null || saveState === 'saving'} onClick={() => { if (dirty && !window.confirm('当前页面有修改。用历史内容继续编辑会替换本页输入，仍要继续吗？')) return; changeContent(config.normalize(history.revision!.content)); setReason(`基于历史版本 ${history.revision!.version} 继续整理`); changeTab('editor') }}>用此历史内容继续编辑</Button> : null}{history.status === 'loaded' && history.revision?.content ? <ContentCompare leftTitle={`历史版本 ${history.revision.version}`} left={history.revision.content} rightTitle='当前编辑内容' right={content} workspace={compareWorkspace} /> : null}</CardContent></Card> : null}
    <Card>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>二、版本历史</CardTitle><CardDescription>历史列表只显示摘要；打开版本可对照完整讲解内容。历史版本保持原样。</CardDescription></CardHeader>
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
    </WorkspacePanel>

    <WorkspacePanel id={config.mode} value='outputs' active={activePanel}>
    <Card>
      <CardHeader className='border-b pb-4'><CardTitle className='text-base'>三、生成与检查</CardTitle><CardDescription>生成任务会检查进度；完成后可预览文档并分别记录内容、依据与版式检查。</CardDescription></CardHeader>
      <CardContent className='space-y-4 pt-4'>
        {outputActionError ? <p role='alert' className='rounded-md bg-amber-50 p-3 text-sm text-amber-950'>{outputActionError}</p> : null}
        {pollError ? <div role='alert' className='flex flex-wrap items-center gap-3 rounded-md bg-amber-50 p-3 text-sm text-amber-950'><p className='min-w-0 flex-1'>读取输出任务状态失败：{pollError}。自动轮询已暂停。</p><Button type='button' size='sm' variant='outline' onClick={() => { setPollError(''); setPollRetry((value) => value + 1) }}>重试读取状态</Button></div> : null}
        {outputs.length === 0 ? <div className='space-y-3'><EmptyState title='还没有生成文档' detail={`先在“编辑讲解”中保存${config.title}草稿并生成文档。`} /><Button type='button' variant='outline' onClick={() => changeTab('editor')}>前往编辑讲解</Button></div> : outputs.map((output) => <OutputCard checkNames={config.checkNames} key={output.id} output={output} expanded={expandedOutputId === output.id} onToggleExpanded={() => setExpandedOutputId((current) => current === output.id ? null : output.id)} checks={checksDraft[output.id] || output.checks} writable={writable} onCheckChange={(name, patch) => updateOutputCheck(output, name, patch)} onAction={(nextAction, checks) => void outputAction(output, nextAction, checks)} />)}
        {outputPageError ? <div className='flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950' role='alert'><p className='min-w-0 flex-1'>读取更早文档失败：{outputPageError}</p><Button type='button' size='sm' variant='outline' disabled={outputPageLoading} onClick={() => void loadEarlierOutputs()}>重试读取更早文档</Button></div> : null}
        {outputBefore !== null ? <Button type='button' size='sm' variant='outline' disabled={outputPageLoading} onClick={() => void loadEarlierOutputs()}>{outputPageLoading ? '正在读取更早文档…' : '读取更早文档'}</Button> : null}
      </CardContent>
    </Card>
    </WorkspacePanel>
  </div>
}

function mergeHistory<H extends RevisionSummary>(current: H[], incoming: H[]) {
  const items = new Map<number, H>()
  for (const item of [...current, ...incoming]) items.set(item.id, item)
  return [...items.values()].sort((left, right) => right.version - left.version)
}

function mergeNodes(current: SolutionWorkspaceResponse['nodes'], incoming: SolutionWorkspaceResponse['nodes']) {
  const nodes = new Map<string, SolutionWorkspaceResponse['nodes'][number]>()
  for (const item of [...current, ...incoming]) nodes.set(item.revision_id, item)
  return [...nodes.values()]
}

function mergeOutputs<O extends CompanionOutput>(current: O[], incoming: O[]) {
  const outputs = new Map<string, O>()
  for (const item of [...current, ...incoming]) outputs.set(item.id, item)
  return [...outputs.values()].sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id.localeCompare(left.id))
}

function mergeAssets(current: SolutionWorkspaceResponse['assets'], incoming: SolutionWorkspaceResponse['assets']) {
  const assets = new Map<string, SolutionWorkspaceResponse['assets'][number]>()
  for (const asset of [...current, ...incoming]) assets.set(asset.id, asset)
  return [...assets.values()]
}

function privateDraftReason(draft: { payload: unknown } | null) {
  const payload: unknown = draft?.payload
  return isRecord(payload) && typeof payload.reason === 'string' ? payload.reason : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
