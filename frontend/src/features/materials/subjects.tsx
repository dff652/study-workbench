import { useEffect, useRef, useState } from 'react'
import { getErrorMessage, getJson, postJson } from '../../api'
import { isUnauthorized } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { requestKeyFor } from './request-keys'

export const SUBJECTS = [['unknown', '未分类'], ['mathematics', '数学'], ['chinese', '语文'], ['english', '英语'],
  ['physics', '物理'], ['chemistry', '化学'], ['biology', '生物'], ['history', '历史'], ['geography', '地理'],
  ['politics', '道德与法治'], ['science', '科学'], ['other', '其他']] as const

export function SubjectSelect({ value, onChange, disabled, all = false, label = '学校学科' }: {
  value: string; onChange: (value: string) => void; disabled?: boolean; all?: boolean; label?: string
}) {
  return <label className='text-sm font-medium'>{label}<select className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm font-normal' value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
    {all ? <option value=''>全部学科</option> : null}{SUBJECTS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
  </select></label>
}

type Classification = { subject: string; version: number }
type History = Array<Classification & { reason: string; author: string; created_at: string }>

export function SubjectEditor({ materialId, csrfToken, writable, onUnauthorized, onSaved, onDirtyChange, onBusyChange }: {
  materialId: string; csrfToken: string; writable: boolean; onUnauthorized: () => void; onSaved?: () => void
  onDirtyChange?: (dirty: boolean) => void; onBusyChange?: (busy: boolean) => void
}) {
  const [loaded, setLoaded] = useState<Classification | null>(null)
  const [subject, setSubject] = useState('unknown')
  const [reason, setReason] = useState('')
  const [history, setHistory] = useState<History>([])
  const [historyBefore, setHistoryBefore] = useState<number | null>(null)
  const [historyBusy, setHistoryBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  const [stale, setStale] = useState<Classification | null>(null)
  const alive = useRef(true)
  const scope = useRef(materialId)
  scope.current = materialId
  const request = useRef<{ signature: string; key: string } | null>(null)
  const saveBusy = useRef(false)
  const historyController = useRef<AbortController | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false; historyController.current?.abort() } }, [])
  useEffect(() => { onDirtyChange?.(Boolean(loaded && (loaded.subject !== subject || reason.trim()))); return () => onDirtyChange?.(false) }, [loaded, subject, reason, onDirtyChange])
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false) }, [busy, onBusyChange])
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoaded(null); setHistory([]); setHistoryBefore(null); setStale(null); setStatus('')
    getJson<{ classification: Classification; history: History; history_next_before: number | null }>(`/api/v1/materials/${encodeURIComponent(materialId)}/classification/`, controller.signal).then((data) => {
      if (!active) return
      setLoaded(data.classification); setSubject(data.classification.subject); setHistory(data.history); setHistoryBefore(data.history_next_before ?? null); setError('')
    }).catch((cause) => { if (!active) return; if (isUnauthorized(cause)) onUnauthorized(); setError(getErrorMessage(cause)) })
    return () => { active = false; controller.abort() }
  }, [materialId, onUnauthorized, retry])
  const save = async () => {
    if (!writable || !loaded || saveBusy.current || !reason.trim() || stale) return
    saveBusy.current = true
    const requestMaterial = materialId
    setBusy(true); setError('')
    const signature = JSON.stringify([materialId, loaded.version, subject, reason])
    try {
      const data = await postJson<{ material: { classification: Classification }; saved_classification?: Classification }>(`/api/v1/materials/${encodeURIComponent(materialId)}/classification/save/`,
        { subject, expected_version: loaded.version, reason, request_key: requestKeyFor(request, signature) }, csrfToken)
      if (!alive.current || scope.current !== requestMaterial) return
      const saved = data.saved_classification || data.material.classification
      setLoaded(saved); setStatus(`学科分类已保存为第 ${saved.version} 版。`); request.current = null; onSaved?.()
      if (saved.version !== data.material.classification.version) {
        setStale(data.material.classification); setError('本次分类已保存，随后已有更新。请比较后再继续。')
      } else { setStale(null); setSubject(saved.subject); setReason('') }
      try {
        const next = await getJson<{ history: History; history_next_before: number | null }>(`/api/v1/materials/${encodeURIComponent(materialId)}/classification/`, new AbortController().signal)
        if (alive.current && scope.current === requestMaterial) { setHistory(next.history); setHistoryBefore(next.history_next_before ?? null) }
      } catch (cause) { if (alive.current && scope.current === requestMaterial) { if (isUnauthorized(cause)) onUnauthorized(); setError('分类已保存，历史暂时无法读取。请稍后重新打开分类。') } }
    } catch (cause) {
      if (!alive.current || scope.current !== requestMaterial) return
      if (isUnauthorized(cause)) onUnauthorized()
      setError(getErrorMessage(cause))
      if (cause && typeof cause === 'object' && 'code' in cause && cause.code === 'stale_subject') {
        try { const data = await getJson<{ classification: Classification }>(`/api/v1/materials/${encodeURIComponent(materialId)}/classification/`, new AbortController().signal); if (alive.current && scope.current === requestMaterial) setStale(data.classification) } catch (error) { if (alive.current && scope.current === requestMaterial && isUnauthorized(error)) onUnauthorized() }
      }
    } finally { saveBusy.current = false; if (alive.current && scope.current === requestMaterial) setBusy(false) }
  }
  const loadEarlier = async () => {
    if (historyBefore === null || historyController.current) return
    const requestMaterial = materialId
    const controller = new AbortController(); historyController.current = controller; setHistoryBusy(true)
    try {
      const next = await getJson<{ history: History; history_next_before: number | null }>(`/api/v1/materials/${encodeURIComponent(materialId)}/classification/?before=${historyBefore}`, controller.signal)
      if (!alive.current || scope.current !== requestMaterial) return
      setHistory((current) => [...new Map([...current, ...next.history].map((row) => [row.version, row])).values()].sort((left, right) => right.version - left.version))
      setHistoryBefore(next.history_next_before); setError('')
    } catch (cause) { if (alive.current && scope.current === requestMaterial && !controller.signal.aborted) { if (isUnauthorized(cause)) onUnauthorized(); setError(getErrorMessage(cause)) } }
    finally { if (historyController.current === controller) historyController.current = null; if (alive.current && scope.current === requestMaterial) setHistoryBusy(false) }
  }
  return <details className='rounded-md border p-3'>
    <summary className='cursor-pointer text-sm font-medium'>资料学科 · {SUBJECTS.find(([id]) => id === loaded?.subject)?.[1] || '未分类'}</summary>
    <div className='mt-3 space-y-3'>
      {error ? <p role='alert' className='text-sm'>{error}{!loaded ? <Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试读取分类</Button> : null}</p> : null}
      {status ? <p role='status' className='text-sm'>{status}</p> : null}
      <div className='grid gap-3 md:grid-cols-2'><SubjectSelect value={subject} onChange={setSubject} disabled={!writable || !loaded || busy} /><label className='text-sm font-medium'>分类依据<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm font-normal' maxLength={1000} value={reason} disabled={!writable || busy} onChange={(event) => setReason(event.target.value)} placeholder='按资料封面或已确认课程分类' /></label></div>
      {stale ? <div className='text-sm'>另一窗口当前分类：{SUBJECTS.find(([id]) => id === stale.subject)?.[1]}，第 {stale.version} 版。<Button type='button' size='sm' variant='outline' onClick={() => { setLoaded(stale); setStale(null); request.current = null }}>已比较，保留本页选择</Button></div> : null}
      {writable ? <Button type='button' size='sm' disabled={!loaded || busy || !reason.trim() || Boolean(stale)} onClick={() => void save()}>{busy ? '正在保存分类…' : '保存分类新版本'}</Button> : null}
      <p className='text-xs text-muted-foreground'>分类由人工确认；讲解依据类别另选。后来的分类不会改写旧文档。</p>
      {history.length ? <ol className='space-y-1 text-sm'>{history.map((item) => <li key={item.version}>第 {item.version} 版 · {SUBJECTS.find(([id]) => id === item.subject)?.[1]} · {item.reason} · {item.author}</li>)}</ol> : null}
      {historyBefore !== null ? <Button type='button' size='sm' variant='outline' disabled={historyBusy} onClick={() => void loadEarlier()}>{historyBusy ? '正在读取分类历史…' : '读取更早分类'}</Button> : null}
    </div>
  </details>
}
