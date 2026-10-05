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
  const [searchText, setSearchText] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [retry, setRetry] = useState(0)
  const [subject, setSubject] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setRemote({ status: 'loading' })
    api.materials(householdId, controller.signal, { q: query, subject, page, pageSize: 20, documentMode: mode }).then((data) => {
      if (!active) return
      setRemote({ status: 'loaded', data })
    }).catch((cause: unknown) => {
      if (!active || (cause instanceof DOMException && cause.name === 'AbortError')) return
      if (isUnauthorized(cause)) onUnauthorized()
      setRemote({ status: 'error', message: getErrorMessage(cause) })
    })
    return () => { active = false; controller.abort() }
  }, [householdId, onUnauthorized, page, query, retry, subject, mode])

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPage(1)
    setQuery(searchText.trim())
  }
  const hasNext = remote.status === 'loaded' && (remote.data.has_next ?? page * (remote.data.page_size || 20) < remote.data.total)

  return <section className='min-w-0 space-y-4' aria-label='讲解资料'>
      <WorkspaceHeading title={mode === 'knowledge' ? '知识讲解文档' : '家长逐题解析'} />
      <form className='flex flex-wrap items-end gap-2 border-b pb-3' role='search' onSubmit={submitSearch}>
        <label className='min-w-[min(100%,16rem)] flex-1 text-sm font-medium'>搜索资料与文档<input type='search' placeholder='输入资料或文档名称' className='mt-1 h-10 w-full rounded-md border bg-background px-3 text-sm font-normal' value={searchText} onChange={(event) => setSearchText(event.target.value)} /></label>
        <SubjectSelect value={subject} all label='资料学科' onChange={(value) => { setSubject(value); setPage(1) }} />
        <Button type='submit' variant='outline' size='sm'><Search className='size-4' aria-hidden='true' />搜索</Button>
        {query ? <Button type='button' variant='ghost' size='sm' onClick={() => { setSearchText(''); setPage(1); setQuery('') }}>清除</Button> : null}
      </form>
      {remote.status === 'loading' ? <p role='status' className='text-sm text-muted-foreground'>正在读取家庭资料…</p> : null}
      {remote.status === 'error' ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm'><span>{remote.message}</span><Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试</Button></div> : null}
      {remote.status === 'loaded' && remote.data.items.length > 0 ? <>
        <p className='text-sm text-muted-foreground'>已有文档可直接预览或下载；每份资料显示该类型最近一批可用输出。历史版本仍可从文档工作区查看。</p>
        {!onPrepareDocuments ? <p className='text-sm text-muted-foreground'>当前成员可查看讲解文档；制作练习册由家庭所有者或审核成员操作。</p> : null}
        <ul className='divide-y'>
          {[...remote.data.items].sort((a, b) => (b.available_outputs?.find((o) => o.mode === mode)?.created_at || '').localeCompare(a.available_outputs?.find((o) => o.mode === mode)?.created_at || '')).map((item) => {
            const output = item.available_outputs?.find((entry) => entry.mode === mode)
            return <li key={item.id} className='space-y-3 py-4'>
              <div className='flex flex-wrap items-center justify-between gap-3'><div><h3 className='font-semibold'>{item.title}</h3><p className='mt-1 text-xs text-muted-foreground'>{item.page_count} 页原图 · {output ? `文档版本 ${output.revision_version} · ${output.state === 'complete' ? '检查已记录' : '输出待审校'} · ${new Date(output.created_at).toLocaleString('zh-CN')}` : '尚无可用文档'}</p></div><Button type='button' size='sm' variant='outline' onClick={() => onOpen(item.id)}>{output ? '查看文档与历史' : mode === 'knowledge' ? '整理知识讲解' : '整理家长解析'}</Button></div>
              {output?.documents.map((doc) => <div key={doc.id} className='flex flex-wrap items-center gap-3 text-sm'><span>{doc.title} · {doc.page_count} 页</span>{doc.pdf_url ? <a href={doc.pdf_url} data-preview-title={doc.title} className="text-primary underline">预览 PDF</a> : null}{doc.docx_url ? <a href={doc.docx_url} download className='font-medium text-primary underline'>下载 Word</a> : null}</div>)}
              {output?.zip_url ? <a href={output.zip_url} download className='inline-block text-sm text-primary underline'>下载这批 ZIP</a> : null}
              {onPrepareDocuments ? <Button type='button' size='sm' variant='ghost' onClick={() => onPrepareDocuments(item.id)}>制作整套五册</Button> : null}
            </li>
          })}
        </ul>
        <div className='flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm text-muted-foreground'>
          <span>{remote.data.total} 份资料 · 第 {remote.data.page || page} 页</span>
          <div className='flex gap-2'>
            <Button type='button' size='sm' variant='outline' disabled={page <= 1 || remote.status !== 'loaded'} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft className='size-4' aria-hidden='true' />上一页</Button>
            <Button type='button' size='sm' variant='outline' disabled={!hasNext} onClick={() => setPage((value) => value + 1)}>下一页<ChevronRight className='size-4' aria-hidden='true' /></Button>
          </div>
        </div>
      </> : null}
      {remote.status === 'loaded' && remote.data.items.length === 0 ? <div className='space-y-2 text-sm'><p>{query || subject ? '没有找到符合筛选条件的资料。' : '当前家庭还没有资料。新建资料并上传原图后即可整理讲解。'}</p>{query || subject ? <Button type='button' size='sm' variant='outline' onClick={() => { setSearchText(''); setQuery(''); setSubject(''); setPage(1) }}>清除筛选</Button> : null}{!query && !subject ? <Button type='button' size='sm' variant='outline' onClick={onMaterials}>前往资料整理</Button> : null}</div> : null}
    </section>
}
