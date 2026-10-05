import { useEffect, useState, type FormEvent } from 'react'
import { api, getErrorMessage } from '../../api'
import { isUnauthorized } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Disclosure } from '../../components/disclosure'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import type { MaterialListResponse } from '../../types'

type Remote = { status: 'loading' } | { status: 'loaded'; data: MaterialListResponse } | { status: 'error'; message: string }

export function SolutionsLauncher({ householdId, onOpen, onPrepareDocuments, onMaterials, onUnauthorized }: { householdId: string; onOpen: (materialId: string) => void; onPrepareDocuments?: (materialId: string) => void; onMaterials: () => void; onUnauthorized: () => void }) {
  const [remote, setRemote] = useState<Remote>({ status: 'loading' })
  const [materialId, setMaterialId] = useState('')
  const [searchText, setSearchText] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.materials(householdId, controller.signal, { q: query, page, pageSize: 20 }).then((data) => {
      if (!active) return
      setRemote({ status: 'loaded', data })
      setMaterialId((current) => current && data.items.some((item) => item.id === current) ? current : data.items[0]?.id || '')
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, onUnauthorized, page, query, retry])

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPage(1)
    setQuery(searchText.trim())
  }
  const hasNext = remote.status === 'loaded' && (remote.data.has_next ?? page * (remote.data.page_size || 20) < remote.data.total)

  return <Card className='border-primary/20'>
    <CardHeader className='border-b pb-4'><CardTitle className='text-base'>逐题解析与文档</CardTitle><CardDescription>选择资料后可先查看已有讲解文档；进入下一页后可打开“编辑讲解”，整理讲义解法、答案、来源和订正，再生成 PDF / Word。</CardDescription></CardHeader>
    <CardContent className='space-y-3 pt-4'>
      <form className='flex flex-wrap items-end gap-3' onSubmit={submitSearch}>
        <label className='min-w-56 flex-1 text-sm font-medium'>按资料名称查找<input className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' value={searchText} onChange={(event) => setSearchText(event.target.value)} /></label>
        <Button type='submit' variant='outline'>查找资料</Button>
      </form>
      {remote.status === 'loading' ? <p role='status' className='text-sm text-muted-foreground'>正在读取家庭资料…</p> : null}
      {remote.status === 'error' ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm'><span>{remote.message}</span><Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试</Button></div> : null}
      {remote.status === 'loaded' && remote.data.items.length > 0 ? <>
        <div className='flex flex-wrap items-end gap-3'>
          <label className='min-w-56 flex-1 text-sm font-medium'>选择资料<select className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm' value={materialId} onChange={(event) => setMaterialId(event.target.value)}>{remote.data.items.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.page_count} 张原图</option>)}</select></label>
          <Button type='button' disabled={!materialId} onClick={() => onOpen(materialId)}>查看讲解文档</Button>
        </div>
        {onPrepareDocuments ? <Disclosure title='家长制作配套练习' description='使用所选资料制作五册内容，保留无答案练习与家长答案的不同用途。'>
          <Button type='button' variant='outline' disabled={!materialId} onClick={() => onPrepareDocuments(materialId)}>制作五册资料</Button>
        </Disclosure> : null}
        <div className='flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground'>
          <span>{remote.data.total} 份资料 · 第 {remote.data.page || page} 页</span>
          <div className='flex gap-2'>
            <Button type='button' size='sm' variant='outline' disabled={page <= 1 || remote.status !== 'loaded'} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</Button>
            <Button type='button' size='sm' variant='outline' disabled={!hasNext} onClick={() => setPage((value) => value + 1)}>下一页</Button>
          </div>
        </div>
      </> : null}
      {remote.status === 'loaded' && remote.data.items.length === 0 ? <div className='space-y-2 text-sm'><p>{query ? '没有找到符合名称的资料。' : '当前家庭还没有资料。新建资料并上传原图后即可整理解析。'}</p>{!query ? <Button type='button' variant='outline' onClick={onMaterials}>前往资料整理</Button> : null}</div> : null}
    </CardContent>
  </Card>
}
