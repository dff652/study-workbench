import { useRef, useState, type ChangeEvent } from 'react'
import { api, getErrorMessage } from '../../api'
import { isUnauthorized } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { makeRequestKey, requestKeyFor, type RequestKeyState } from './request-keys'

type UploadItem = {
  id: string
  file: File
  status: 'queued' | 'uploading' | 'done' | 'failed'
  error: string
  duplicate: boolean
}

export function MaterialUploadQueue({ materialId, csrfToken, canWrite, onUploaded, onUnauthorized, onBusyChange }: {
  materialId: string
  csrfToken: string
  canWrite: boolean
  onUploaded: () => void
  onUnauthorized: () => void
  onBusyChange: (busy: boolean) => void
}) {
  const [queue, setQueue] = useState<UploadItem[]>([])
  const queueRef = useRef(queue)
  const keysRef = useRef(new Map<string, { current: RequestKeyState }>())
  const busyRef = useRef(false)
  const [busy, setBusy] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const updateQueue = (update: (current: UploadItem[]) => UploadItem[]) => {
    setQueue((current) => {
      const next = update(current)
      queueRef.current = next
      return next
    })
  }

  const addFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const incoming = Array.from(event.currentTarget.files || [])
    updateQueue((current) => {
      const existing = new Set(current.map((item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`))
      const next = [...current]
      for (const file of incoming) {
        const signature = `${file.name}:${file.size}:${file.lastModified}`
        if (existing.has(signature)) continue
        existing.add(signature)
        try {
          next.push({ id: makeRequestKey(), file, status: 'queued', error: '', duplicate: false })
        } catch (cause) {
          next.push({ id: `local-${Date.now()}-${next.length}`, file, status: 'failed', error: getErrorMessage(cause), duplicate: false })
        }
      }
      return next
    })
    event.currentTarget.value = ''
  }

  const process = async (requestedIds?: string[]) => {
    if (busyRef.current || !canWrite) return
    const ids = requestedIds || queueRef.current.filter((item) => item.status === 'queued').map((item) => item.id)
    if (!ids.length) return
    busyRef.current = true
    setBusy(true)
    onBusyChange(true)
    let succeeded = false
    try {
      for (const id of ids) {
        const item = queueRef.current.find((candidate) => candidate.id === id)
        if (!item || (item.status !== 'queued' && item.status !== 'failed')) continue
        updateQueue((current) => current.map((candidate) => candidate.id === id ? { ...candidate, status: 'uploading', error: '' } : candidate))
        try {
          let keyState = keysRef.current.get(id)
          if (!keyState) {
            keyState = { current: null }
            keysRef.current.set(id, keyState)
          }
          const signature = `${materialId}:${item.file.name}:${item.file.size}:${item.file.lastModified}`
          const requestKey = requestKeyFor(keyState, signature)
          const result = await api.uploadPage(materialId, item.file, requestKey, csrfToken)
          keysRef.current.delete(id)
          updateQueue((current) => current.map((candidate) => candidate.id === id ? { ...candidate, status: 'done', duplicate: result.duplicate, error: '' } : candidate))
          succeeded = true
        } catch (cause) {
          if (isUnauthorized(cause)) onUnauthorized()
          updateQueue((current) => current.map((candidate) => candidate.id === id ? { ...candidate, status: 'failed', error: getErrorMessage(cause) } : candidate))
        }
      }
    } finally {
      busyRef.current = false
      setBusy(false)
      onBusyChange(false)
      if (succeeded) onUploaded()
    }
  }

  const queuedCount = queue.filter((item) => item.status === 'queued').length
  const failedCount = queue.filter((item) => item.status === 'failed').length
  const doneCount = queue.filter((item) => item.status === 'done').length

  return <Card>
    <CardHeader className='border-b pb-4'><CardTitle className='text-base'>原图上传向导</CardTitle><CardDescription>可一次选择多张图片。文件按队列逐张原样上传，失败项可单独重试；已成功项目不重复提交。</CardDescription></CardHeader>
    <CardContent className='space-y-3 pt-4'>
      <div className='flex flex-wrap items-center gap-3'>
        <input ref={fileInput} aria-label='选择多张原图' type='file' accept='image/*' multiple disabled={!canWrite || busy} onChange={addFiles} className='block max-w-full text-sm file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-2 file:text-sm file:font-medium' />
        <Button type='button' disabled={!canWrite || busy || queuedCount === 0} onClick={() => void process()}>{busy ? '正在处理上传队列…' : `上传待处理原图${queuedCount ? `（${queuedCount}）` : ''}`}</Button>
        {doneCount ? <span className='text-xs workspace-inline-state--success'>已完成 {doneCount} 张</span> : null}
        {failedCount ? <span className='text-xs workspace-inline-state--danger'>失败 {failedCount} 张</span> : null}
      </div>
      {!canWrite ? <p className='text-sm text-muted-foreground'>当前账号不能向此资料上传原图。</p> : null}
      {queue.length ? <ul className='space-y-2'>
        {queue.map((item) => <li key={item.id} className='flex flex-wrap items-center justify-between gap-3 rounded-md border p-3'>
          <div className='min-w-0 flex-1'><p className='truncate text-sm font-medium'>{item.file.name}</p><p className='mt-1 text-xs text-muted-foreground'>{(item.file.size / 1024 / 1024).toFixed(2)} MiB · {uploadStatus(item)}</p>
            {item.error ? <p role='alert' className='mt-1 text-xs workspace-inline-state--danger'>{item.error}</p> : null}</div>
          <div className='flex gap-2'>
            {item.status === 'failed' ? <Button type='button' size='sm' variant='outline' disabled={busy || !canWrite} onClick={() => void process([item.id])}>重试此图</Button> : null}
            {item.status !== 'uploading' ? <Button type='button' size='sm' variant='outline' disabled={busy || item.status === 'done'} onClick={() => updateQueue((current) => current.filter((candidate) => candidate.id !== item.id))}>移出队列</Button> : null}
          </div>
        </li>)}
      </ul> : <p className='rounded-md border border-dashed p-4 text-sm text-muted-foreground'>选择一张或多张照片后，可先检查队列再明确上传。</p>}
      <p className='text-xs text-muted-foreground'>原图按收到的文件保存。上传后可在资料页核对页序、题面与阅读状态，再进入“整理解析”补充讲义内容。</p>
    </CardContent>
  </Card>
}

function uploadStatus(item: UploadItem) {
  if (item.status === 'queued') return '等待上传'
  if (item.status === 'uploading') return '正在上传'
  if (item.status === 'failed') return '上传失败'
  return item.duplicate ? '服务端已有相同原图' : '上传完成'
}
