import { useEffect, useState, type FormEvent } from 'react'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { api, getErrorMessage } from '../../api'
import { isUnauthorized } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { WorkspaceHeading } from '../../components/workspace-tabs'
import type { MaterialListResponse } from '../../types'
import { SubjectSelect } from '../materials/subjects'

type Remote = { status: 'loading' } | { status: 'loaded'; data: MaterialListResponse } | { status: 'error'; message: string }

export function SolutionsLauncher({ householdId, onOpen, onPrepareDocuments, onMaterials, onUnauthorized, mode = 'solution' }: { householdId: string; onOpen: (materialId: string) => void; onPrepareDocuments?: (materialId: string) => void; onMaterials: () => void; onUnauthorized: () => void; mode?: 'solution' | 'knowledge' }) {
  const [remote, setRemote] = useState<Remote>({ status: 'loading' })
  const [materialId, setMaterialId] = useState('')
  const [searchText, setSearchText] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [retry, setRetry] = useState(0)
  const [subject, setSubject] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.materials(householdId, controller.signal, { q: query, subject, page, pageSize: 20 }).then((data) => {
      if (!active) return
      setRemote({ status: 'loaded', data })
      setMaterialId((current) => current && data.items.some((item) => item.id === current) ? current : data.items[0]?.id || '')
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, onUnauthorized, page, query, retry, subject])

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPage(1)
    setQuery(searchText.trim())
  }
  const hasNext = remote.status === 'loaded' && (remote.data.has_next ?? page * (remote.data.page_size || 20) < remote.data.total)
  const selectedMaterial = remote.status === 'loaded' ? remote.data.items.find((item) => item.id === materialId) : undefined

  return <section className='min-w-0 space-y-4' aria-label='讲解资料'>
      <WorkspaceHeading title='选择资料' />
      <form className='flex flex-wrap items-end gap-2 border-b pb-3' role='search' onSubmit={submitSearch}>
        <label className='min-w-[min(100%,16rem)] flex-1 text-sm font-medium'>按名称搜索<input type='search' placeholder='输入资料名称' className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm font-normal' value={searchText} onChange={(event) => setSearchText(event.target.value)} /></label>
        <SubjectSelect value={subject} all label='资料学科' onChange={(value) => { setSubject(value); setPage(1) }} />
        <Button type='submit' variant='outline' size='sm'><Search className='size-4' aria-hidden='true' />搜索</Button>
        {query ? <Button type='button' variant='ghost' size='sm' onClick={() => { setSearchText(''); setPage(1); setQuery('') }}>清除</Button> : null}
      </form>
      {remote.status === 'loading' ? <p role='status' className='text-sm text-muted-foreground'>正在读取家庭资料…</p> : null}
      {remote.status === 'error' ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm'><span>{remote.message}</span><Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试</Button></div> : null}
      {remote.status === 'loaded' && remote.data.items.length > 0 ? <>
        <div className='grid min-w-0 gap-3 md:grid-cols-[minmax(16rem,0.7fr)_minmax(0,1fr)]'>
          <label className='text-sm font-medium'>当前资料<select aria-label='选择资料' className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm font-normal' value={materialId} onChange={(event) => setMaterialId(event.target.value)}>{remote.data.items.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.page_count} 页</option>)}</select></label>
          <div className='min-w-0 border-l-2 border-primary/40 py-1 pl-3' aria-live='polite'>
            <p className='text-xs text-muted-foreground'>已选资料</p>
            <p className='mt-1 break-words font-medium'>{selectedMaterial?.title || '请选择资料'}</p>
            {selectedMaterial ? <p className='mt-1 text-xs text-muted-foreground'>{selectedMaterial.page_count} 张原图</p> : null}
          </div>
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <Button type='button' size='sm' disabled={!materialId} onClick={() => onOpen(materialId)}>{mode === 'knowledge' ? '打开知识点讲解' : '查看讲解文档'}</Button>
          {onPrepareDocuments ? <Button type='button' size='sm' variant='outline' disabled={!materialId} onClick={() => onPrepareDocuments(materialId)}>制作五册资料</Button> : <p className='text-xs text-muted-foreground'>{mode === 'knowledge' ? '选好资料后，对照原图整理知识结论、条件和完整依据。' : '当前成员可查看讲解文档；制作练习册由家庭所有者或审核成员操作。'}</p>}
        </div>
        <div className='flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm text-muted-foreground'>
          <span>{remote.data.total} 份资料 · 第 {remote.data.page || page} 页</span>
          <div className='flex gap-2'>
            <Button type='button' size='sm' variant='outline' disabled={page <= 1 || remote.status !== 'loaded'} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft className='size-4' aria-hidden='true' />上一页</Button>
            <Button type='button' size='sm' variant='outline' disabled={!hasNext} onClick={() => setPage((value) => value + 1)}>下一页<ChevronRight className='size-4' aria-hidden='true' /></Button>
          </div>
        </div>
      </> : null}
      {remote.status === 'loaded' && remote.data.items.length === 0 ? <div className='space-y-2 text-sm'><p>{query || subject ? '没有找到符合筛选条件的资料。' : '当前家庭还没有资料。新建资料并上传原图后即可整理讲解。'}</p>{!query && !subject ? <Button type='button' size='sm' variant='outline' onClick={onMaterials}>前往资料整理</Button> : null}</div> : null}
    </section>
}
