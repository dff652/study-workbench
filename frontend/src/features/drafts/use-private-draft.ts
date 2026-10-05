import { useCallback, useEffect, useRef, useState } from 'react'
import { loadPrivateDraft, savePrivateDraft, type PrivateDraft } from './client'
import { makeRequestKey } from '../materials/request-keys'
import { userMessage } from '../../lib/user-message'

type DraftPayload<T> = T | { cleared: true }

export function usePrivateDraft<T>({ key, householdId, csrfToken, baseStamp, enabled, dirty, payload, onUnauthorized }: {
  key: string
  householdId: string
  csrfToken: string
  baseStamp: string
  enabled: boolean
  dirty: boolean
  payload: T
  onUnauthorized: () => void
}) {
  const scopeRef = useRef({ key, householdId, generation: 0 })
  if (scopeRef.current.key !== key || scopeRef.current.householdId !== householdId) {
    scopeRef.current = { key, householdId, generation: scopeRef.current.generation + 1 }
  }
  const version = useRef(0)
  const loaded = useRef(false)
  const loadedScope = useRef(-1)
  const loadFailed = useRef(false)
  const candidateRef = useRef<PrivateDraft<DraftPayload<T>> | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const inFlight = useRef<Promise<void> | null>(null)
  const pending = useRef(false)
  const tombstoning = useRef(false)
  const clearing = useRef<{ scope: number; promise: Promise<boolean> } | null>(null)
  const sequence = useRef(0)
  const suppressedThrough = useRef(0)
  const conflictRef = useRef<PrivateDraft<DraftPayload<T>> | null | undefined>(undefined)
  const writeLatestRef = useRef<() => Promise<void>>(async () => {})
  const latest = useRef({ payload, baseStamp, enabled, dirty })
  latest.current = { payload, baseStamp, enabled, dirty }

  const [candidate, setCandidate] = useState<PrivateDraft<DraftPayload<T>> | null>(null)
  const [conflict, setConflict] = useState<PrivateDraft<DraftPayload<T>> | null | undefined>(undefined)
  const [message, setMessage] = useState('')
  const [loadError, setLoadError] = useState('')
  const [generation, setGeneration] = useState(0)

  const setCandidateValue = useCallback((value: PrivateDraft<DraftPayload<T>> | null) => {
    candidateRef.current = value
    setCandidate(value)
  }, [])

  const setConflictValue = useCallback((value: PrivateDraft<DraftPayload<T>> | null | undefined) => {
    conflictRef.current = value
    setConflict(value)
  }, [])

  useEffect(() => { sequence.current += 1 }, [payload, baseStamp])

  const canAutosave = useCallback(() => latest.current.enabled
    && latest.current.dirty
    && loaded.current
    && !loadFailed.current
    && loadedScope.current === scopeRef.current.generation
    && candidateRef.current === null
    && conflictRef.current === undefined
    && !tombstoning.current
    && sequence.current > suppressedThrough.current,
  [])

  const schedule = useCallback((delay = 650) => {
    window.clearTimeout(timer.current)
    if (!canAutosave() || tombstoning.current) return
    timer.current = window.setTimeout(() => {
      timer.current = undefined
      void writeLatestRef.current()
    }, delay)
  }, [canAutosave])

  const writeLatest = useCallback(async () => {
    // Recheck every write boundary. A candidate can arrive after a timer was
    // scheduled, and an old callback must never save across a scope change.
    if (!canAutosave() || scopeRef.current.key !== key || scopeRef.current.householdId !== householdId) return
    if (inFlight.current) { pending.current = true; return }

    const requestScope = scopeRef.current.generation
    const sequenceAtStart = sequence.current
    const snapshot = latest.current
    setMessage('正在保存私人草稿…')
    const request = savePrivateDraft<T>(key, householdId, {
      expected_version: version.current,
      base_stamp: snapshot.baseStamp,
      payload: snapshot.payload,
      request_key: makeRequestKey(),
    }, csrfToken).then((result) => {
      if (scopeRef.current.generation !== requestScope) return
      if (result.kind === 'conflict') {
        setConflictValue(result.draft)
        setMessage('另一窗口已保存较新版本，请比较后处理。')
      } else {
        version.current = result.draft.version
        setMessage(sequence.current === sequenceAtStart ? '私人草稿已保存。' : '较早编辑已保存，正在保存最新内容…')
      }
    }).catch((cause: unknown) => {
      if (scopeRef.current.generation !== requestScope) return
      if (isUnauthorizedError(cause)) onUnauthorized()
      setMessage('私人草稿未保存，请稍后重试；当前输入仍保留。')
    })
    inFlight.current = request
    try {
      await request
    } finally {
      if (inFlight.current === request) inFlight.current = null
      const changedScope = scopeRef.current.generation !== requestScope
      const shouldSaveLatest = pending.current && (changedScope || sequence.current > sequenceAtStart) && canAutosave() && !tombstoning.current
      pending.current = false
      if (shouldSaveLatest) schedule()
    }
  }, [canAutosave, csrfToken, householdId, key, onUnauthorized, schedule, setConflictValue])
  writeLatestRef.current = writeLatest

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const requestScope = scopeRef.current.generation
    loaded.current = false
    loadedScope.current = -1
    loadFailed.current = false
    version.current = 0
    candidateRef.current = null
    conflictRef.current = undefined
    pending.current = false
    tombstoning.current = false
    setCandidateValue(null); setConflictValue(undefined); setLoadError(''); setMessage('')
    if (!enabled) { loaded.current = true; loadedScope.current = requestScope; setGeneration((value) => value + 1); return () => controller.abort() }
    loadPrivateDraft<DraftPayload<T>>(key, householdId, controller.signal).then((draft) => {
      if (!active || scopeRef.current.generation !== requestScope) return
      version.current = draft?.version || 0
      if (draft && !isCleared(draft.payload)) setCandidateValue(draft)
      loaded.current = true
      loadedScope.current = requestScope
      setGeneration((value) => value + 1)
    }).catch((cause: unknown) => {
      if (!active || scopeRef.current.generation !== requestScope || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorizedError(cause)) onUnauthorized()
      loadFailed.current = true
      loaded.current = false
      loadedScope.current = -1
      setLoadError(userMessage(cause instanceof Error ? cause.message : '', '私人草稿暂时无法读取，请保留当前输入，稍后重试。'))
      setGeneration((value) => value + 1)
    })
    return () => {
      active = false
      controller.abort()
      window.clearTimeout(timer.current)
      pending.current = false
    }
  }, [key, householdId, enabled, onUnauthorized, setCandidateValue, setConflictValue])

  useEffect(() => {
    window.clearTimeout(timer.current)
    if (!enabled || !dirty || !loaded.current || candidate !== null || conflict !== undefined || !canAutosave()) return
    schedule()
    return () => window.clearTimeout(timer.current)
  }, [key, householdId, csrfToken, baseStamp, enabled, dirty, payload, candidate, conflict, generation, onUnauthorized, canAutosave, schedule])

  const accept = useCallback((draft: PrivateDraft<DraftPayload<T>>) => {
    version.current = draft.version
    setCandidateValue(null)
    conflictRef.current = undefined
    setConflict(undefined)
  }, [setCandidateValue])

  const clearDraft = useCallback(async (draft?: PrivateDraft<DraftPayload<T>>) => {
    const requestScope = scopeRef.current.generation
    if (scopeRef.current.key !== key || scopeRef.current.householdId !== householdId) return false
    tombstoning.current = true
    pending.current = false
    window.clearTimeout(timer.current)
    const sequenceAtStart = sequence.current
    try {
      await inFlight.current
      if (scopeRef.current.generation !== requestScope
        || scopeRef.current.key !== key
        || scopeRef.current.householdId !== householdId) return false
      if ((candidateRef.current !== null || conflictRef.current !== undefined) && !draft) return false
      const expected = Math.max(version.current, draft?.version ?? 0)
      const result = await savePrivateDraft<DraftPayload<T>>(key, householdId, {
        expected_version: expected,
        base_stamp: latest.current.baseStamp,
        payload: { cleared: true },
        request_key: makeRequestKey(),
      }, csrfToken)
      if (scopeRef.current.generation !== requestScope) return false
      if (result.kind === 'conflict') {
        setConflictValue(result.draft)
        return false
      }
      version.current = result.draft.version
      suppressedThrough.current = sequenceAtStart
      setCandidateValue(null); conflictRef.current = undefined; setConflict(undefined)
      setMessage(sequence.current === sequenceAtStart || !latest.current.dirty
        ? '私人草稿已清理。'
        : '较早草稿已清理，正在保存最新内容…')
      return true
    } catch (cause) {
      if (scopeRef.current.generation !== requestScope) return false
      if (isUnauthorizedError(cause)) onUnauthorized()
      setMessage('私人草稿未清理；当前输入仍保留。')
      return false
    } finally {
      if (scopeRef.current.generation === requestScope) {
        tombstoning.current = false
        if (sequence.current > sequenceAtStart && canAutosave()) schedule()
      }
    }
  }, [canAutosave, csrfToken, householdId, key, onUnauthorized, schedule, setCandidateValue, setConflictValue])

  const tombstone = useCallback((draft?: PrivateDraft<DraftPayload<T>>) => {
    const scope = scopeRef.current.generation
    // Saving and immediately confirming can both request cleanup. They must
    // share one CAS write rather than conflict with this window's own write.
    if (clearing.current?.scope === scope) return clearing.current.promise
    const operation = { scope, promise: clearDraft(draft) }
    clearing.current = operation
    void operation.promise.finally(() => {
      if (clearing.current === operation) clearing.current = null
    })
    return operation.promise
  }, [clearDraft])

  const keepCurrent = useCallback(() => {
    const pendingCandidate = candidateRef.current
    const pendingConflict = conflictRef.current
    version.current = pendingConflict?.version ?? pendingCandidate?.version ?? version.current
    setCandidateValue(null)
    conflictRef.current = undefined
    setConflict(undefined)
    sequence.current += 1
    setGeneration((value) => value + 1)
    if (latest.current.dirty) {
      setMessage('已选择保留当前内容，正在写入私人草稿。')
      schedule()
    } else if (pendingCandidate) {
      setMessage('已保留当前内容，正在清除未采用的私人草稿。')
      void tombstone(pendingCandidate)
    } else if (pendingConflict !== undefined) {
      setMessage('已保留当前内容，正在清除未采用的私人草稿。')
      void tombstone(pendingConflict ?? undefined)
    } else {
      setMessage('已选择保留当前内容。')
    }
  }, [schedule, setCandidateValue, tombstone])

  return { candidate, conflict, message, loadError, accept, keepCurrent, tombstone, setMessage }
}

function isCleared(payload: unknown): payload is { cleared: true } {
  return Boolean(payload && typeof payload === 'object' && 'cleared' in payload && (payload as { cleared: unknown }).cleared === true)
}

function isUnauthorizedError(cause: unknown) {
  return Boolean(cause && typeof cause === 'object' && 'status' in cause && (cause as { status: unknown }).status === 401)
}
