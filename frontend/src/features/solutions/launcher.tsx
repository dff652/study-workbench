import { useEffect, useState } from 'react'
import { api, getErrorMessage } from '../../api'
import { isUnauthorized } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { MaterialListResponse } from '../../types'

type Remote = { status: 'loading' } | { status: 'loaded'; data: MaterialListResponse } | { status: 'error'; message: string }

export function SolutionsLauncher({ householdId, onOpen, onMaterials, onUnauthorized }: { householdId: string; onOpen: (materialId: string) => void; onMaterials: () => void; onUnauthorized: () => void }) {
  const [remote, setRemote] = useState<Remote>({ status: 'loading' })
  const [materialId, setMaterialId] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.materials(householdId, controller.signal).then((data) => {
      if (!active) return
      setRemote({ status: 'loaded', data })
      setMaterialId((current) => current && data.items.some((item) => item.id === current) ? current : data.items[0]?.id || '')
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, onUnauthorized, retry])

  return <Card className='border-primary/20'>
    <CardHeader className='border-b pb-4'><CardTitle className='text-base'>逐题解析与文档</CardTitle><CardDescription>从当前家庭选择一份资料，按题整理讲义解法、答案、来源和订正，再单独生成 PDF / Word。</CardDescription></CardHeader>
    <CardContent className='flex flex-wrap items-end gap-3 pt-4'>
      {remote.status === 'loading' ? <p role='status' className='text-sm text-muted-foreground'>正在读取家庭资料…</p> : null}
      {remote.status === 'error' ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm'><span>{remote.message}</span><Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试</Button></div> : null}
      {remote.status === 'loaded' && remote.data.items.length > 0 ? <>
        <label className='min-w-56 flex-1 text-sm font-medium'>选择资料<select className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' value={materialId} onChange={(event) => setMaterialId(event.target.value)}>{remote.data.items.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.page_count} 张原图</option>)}</select></label>
        <Button type='button' disabled={!materialId} onClick={() => onOpen(materialId)}>打开逐题解析</Button>
      </> : null}
      {remote.status === 'loaded' && remote.data.items.length === 0 ? <div className='space-y-2 text-sm'><p>当前家庭还没有资料。新建资料并上传原图后即可整理解析。</p><Button type='button' variant='outline' onClick={onMaterials}>前往资料整理</Button></div> : null}
      {remote.status === 'loaded' && remote.data.total > remote.data.items.length ? <p className='w-full text-xs text-muted-foreground'>这里只列出最近 {remote.data.items.length} 份资料；更早的资料可从资料整理页选择。</p> : null}
    </CardContent>
  </Card>
}
