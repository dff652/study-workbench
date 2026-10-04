import { useEffect, useRef, useState, type FormEvent } from 'react'
import { BookOpenCheck, CircleHelp } from 'lucide-react'
import { api } from '../../api'
import { errorText, isUnauthorized, LoadingState, RetryState } from '../../components/shared'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { PageReadingRecord, PageReadingResponse, MaterialPage, SavePageReadingInput } from '../../types'
import type { Remote } from '../../components/shared'
import { requestKeyFor, type RequestKeyState } from '../materials/request-keys'
import { ImageBoxPicker } from './image-box-picker'

type PartitionKind = PageReadingRecord['partitions'][number]['kind']
type ReadingState = SavePageReadingInput['reading']
type Coverage = SavePageReadingInput['coverage']

const READING_LABELS: Record<ReadingState, string> = {
  unread: '未读',
  read: '已阅读',
  needs_retake: '需要重拍',
}

const COVERAGE_LABELS: Record<Coverage, string> = {
  partial: '部分覆盖',
  complete: '完整覆盖',
}

const PARTITION_LABELS: Record<PartitionKind, string> = {
  theory: '知识讲解',
  question: '题目',
  diagram: '图形',
  handwriting: '笔迹或手写内容',
  unknown: '未知区域',
}

export function PageReading({
  page,
  csrfToken,
  canWrite,
  workspaceBusy,
  onUnauthorized,
  onBusyChange,
}: {
  page: MaterialPage
  csrfToken: string
  canWrite: boolean
  workspaceBusy: boolean
  onUnauthorized: () => void
  onBusyChange: (busy: boolean) => void
}) {
  const [remote, setRemote] = useState<Remote<PageReadingResponse>>({ status: 'loading' })
  const [refresh, setRefresh] = useState(0)
  const [reading, setReading] = useState<ReadingState>('unread')
  const [coverage, setCoverage] = useState<Coverage>('partial')
  const [partitions, setPartitions] = useState<PageReadingRecord['partitions']>([])
  const [partitionKind, setPartitionKind] = useState<PartitionKind>('question')
  const [pendingText, setPendingText] = useState('')
  const [basis, setBasis] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const requestKey = useRef<RequestKeyState>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.pageReading(page.id, controller.signal).then((data) => {
      if (!active) return
      setRemote({ status: 'loaded', data })
      setReading(data.current?.reading === 'read' || data.current?.reading === 'needs_retake' ? data.current.reading : 'unread')
      setCoverage(data.current?.coverage === 'complete' ? 'complete' : 'partial')
      setPartitions(data.current?.partitions || [])
      setPendingText((data.current?.pending_items || []).join('\n'))
      setBasis(data.current?.basis || '')
    }).catch((cause: unknown) => {
      if (!active || isAbortError(cause)) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: errorText(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [page.id, refresh, onUnauthorized])

  const pendingItems = pendingText.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
  const hasUnknown = partitions.some((partition) => partition.kind === 'unknown')
  const completeBlocked = reading !== 'read' || partitions.length === 0 || hasUnknown || pendingItems.length > 0

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (remote.status !== 'loaded' || !canWrite || busy || workspaceBusy || !basis.trim() || (coverage === 'complete' && completeBlocked)) return
    const payload = {
      expected: remote.data.context,
      reading,
      coverage,
      partitions,
      pending_items: pendingItems,
      basis: basis.trim(),
    }
    setBusy(true)
    onBusyChange(true)
    setError('')
    setNotice('')
    try {
      const key = requestKeyFor(requestKey, JSON.stringify([page.id, payload]))
      await api.savePageReading(page.id, { ...payload, request_key: key }, csrfToken)
      requestKey.current = null
      setNotice('本页阅读记录已保存，历史修订仍保留。')
      setRefresh((value) => value + 1)
    } catch (cause) {
      if (isUnauthorized(cause)) onUnauthorized()
      setError(errorText(cause))
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  return (
    <Card className='gap-0 py-0 shadow-sm'>
      <CardHeader className='border-b py-4'>
        <CardTitle className='flex items-center gap-2 text-base'><BookOpenCheck className='size-4 text-primary' aria-hidden='true' />资料页 {page.position} 整页阅读</CardTitle>
        <CardDescription>按原图分区记录已读内容、未知区域和待补事项。未知或待补内容会阻止标记为完整。</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4 px-5 py-5'>
        {remote.status === 'loading' ? <LoadingState label='正在读取本页阅读历史…' /> : null}
        {remote.status === 'error' ? <RetryState message={remote.message} onRetry={() => setRefresh((value) => value + 1)} /> : null}
        {remote.status === 'loaded' ? (
          <>
            {remote.data.current ? (
              <div className='flex flex-wrap items-center gap-2 rounded-md bg-muted/30 px-3 py-2 text-sm'>
                <Badge variant='outline'>{READING_LABELS[remote.data.current.reading as ReadingState] || '状态未知'}</Badge>
                <span>{COVERAGE_LABELS[remote.data.current.coverage as Coverage] || '覆盖情况未知'}</span>
                <span className='text-muted-foreground'>修订 {remote.data.current.revision_no} · 记录于 {remote.data.current.recorded_at}</span>
              </div>
            ) : <p className='rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground'>本页尚无整页阅读记录。</p>}
            <form className='space-y-4' onSubmit={(event) => void save(event)}>
              <div className='grid gap-3 sm:grid-cols-2'>
                <label className='block text-sm font-medium'>阅读状态
                  <select className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={reading} onChange={(event) => setReading(event.target.value as ReadingState)} disabled={!canWrite || busy || workspaceBusy}>
                    {Object.entries(READING_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label className='block text-sm font-medium'>阅读覆盖
                  <select className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={coverage} onChange={(event) => setCoverage(event.target.value as Coverage)} disabled={!canWrite || busy || workspaceBusy}>
                    {Object.entries(COVERAGE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
              </div>
              {coverage === 'complete' && completeBlocked ? (
                <p role='alert' className='flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950'><CircleHelp className='mt-0.5 size-4 shrink-0' aria-hidden='true' />尚未标记分区，或存在未读、未知区域或待补事项，不能标记为完整覆盖。</p>
              ) : null}
              <div className='space-y-3'>
                <label className='block max-w-xs text-sm font-medium'>新分区类型
                  <select className='mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal' value={partitionKind} onChange={(event) => setPartitionKind(event.target.value as PartitionKind)} disabled={!canWrite || busy || workspaceBusy}>
                    {Object.entries(PARTITION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <ImageBoxPicker
                  page={page}
                  boxes={partitions.map((partition, index) => ({ bbox: partition.bbox, label: `${PARTITION_LABELS[partition.kind]}分区 ${index + 1}`, color: partition.kind === 'unknown' ? '#b7791f' : '#356c3f' }))}
                  disabled={!canWrite || busy || workspaceBusy}
                  onAdd={(bbox) => setPartitions((current) => [...current, { kind: partitionKind, bbox }])}
                  addLabel={`确认添加${PARTITION_LABELS[partitionKind]}分区`}
                />
                {partitions.length ? <ul className='space-y-2'>
                  {partitions.map((partition, index) => (
                    <li key={`${partition.bbox.join('-')}:${index}`} className='flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm'>
                      <span>{PARTITION_LABELS[partition.kind]} · 原图区域 [{partition.bbox.join(', ')}] px</span>
                      {canWrite ? <button type='button' className='text-destructive underline' onClick={() => setPartitions((current) => current.filter((_, rowIndex) => rowIndex !== index))} disabled={busy || workspaceBusy}>移除分区</button> : null}
                    </li>
                  ))}
                </ul> : <p className='text-sm text-muted-foreground'>暂未标记页面分区；看不清的区域请标为未知。</p>}
              </div>
              <label className='block text-sm font-medium'>待补事项（每行一项）
                <textarea className='mt-1 min-h-24 w-full rounded-md border bg-background px-3 py-2 font-normal leading-6' value={pendingText} onChange={(event) => setPendingText(event.target.value)} disabled={!canWrite || busy || workspaceBusy} placeholder='例如：第 2 页右下角字迹待辨认' />
              </label>
              <label className='block text-sm font-medium'>阅读依据（必填）
                <textarea className='mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2 font-normal leading-6' value={basis} onChange={(event) => setBasis(event.target.value)} required disabled={!canWrite || busy || workspaceBusy} />
              </label>
              {error ? <p role='alert' className='text-sm text-destructive'>{error}</p> : null}
              {notice ? <p role='status' className='text-sm text-emerald-800'>{notice}</p> : null}
              {canWrite ? <Button type='submit' disabled={busy || workspaceBusy || !basis.trim() || (coverage === 'complete' && completeBlocked)}>{busy ? '正在保存…' : '保存本页阅读记录'}</Button> : <p className='text-sm text-muted-foreground'>当前为只读成员，可查看完整的历史修订。</p>}
            </form>
            <ReadingHistory history={remote.data.history} />
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ReadingHistory({ history }: { history: PageReadingRecord[] }) {
  return (
    <section className='border-t pt-4'>
      <h3 className='mb-3 text-sm font-semibold'>整页阅读历史</h3>
      {history.length === 0 ? <p className='text-sm text-muted-foreground'>还没有历史修订。</p> : (
        <ol className='space-y-3'>
          {history.map((entry) => (
            <li key={entry.revision_no} className='border-l-2 border-muted pl-3 text-sm'>
              <p className='font-medium'>第 {entry.revision_no} 次 · {READING_LABELS[entry.reading as ReadingState] || '状态未知'} · {COVERAGE_LABELS[entry.coverage as Coverage] || '覆盖情况未知'}</p>
              <p className='mt-1 text-muted-foreground'>分区 {entry.partitions.length} 个 · 待补 {entry.pending_items.length} 项</p>
              <p className='mt-1 text-muted-foreground'>依据：{entry.basis || '未记录'}</p>
              <p className='mt-1 text-xs text-muted-foreground'>记录时间：{entry.recorded_at || '未记录'}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
