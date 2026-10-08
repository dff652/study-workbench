import { useEffect, useState, type FormEvent } from 'react'
import { getJson } from '../../api'
import { ApiLink, EmptyState, errorText, isUnauthorized, LoadingState, RetryState, type Remote } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { useLearningUpdates } from '../../lib/learning-updates'

type DocumentItem = { id: string; category_label: string; title: string; created_at: string; state_label: string; detail_url: string; message: string; zip_url: string | null; checks: Record<string, { status: string }>; documents: Array<{ id: string; title: string; pdf_url?: string | null; docx_url?: string | null; preview_url?: string; previews?: string[] }> }
type Catalogue = { items: DocumentItem[]; total: number; page: number; has_next: boolean }

export function DocumentCatalogue({ householdId, onUnauthorized }: { householdId: string; onUnauthorized: () => void }) {
  const [remote, setRemote] = useState<Remote<Catalogue>>({ status: 'loading' })
  const [text, setText] = useState('')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [retry, setRetry] = useState(0)
  const updateVersion = useLearningUpdates(householdId)
  useEffect(() => {
    const controller = new AbortController()
    setRemote({ status: 'loading' })
    const params = new URLSearchParams({ household: householdId, q: query, category, page: String(page) })
    void getJson<Catalogue>(`/api/v1/documents/?${params}`, controller.signal).then((data) => {
      if (!controller.signal.aborted) setRemote({ status: 'loaded', data })
    }).catch((error) => {
      if (controller.signal.aborted) return
      if (isUnauthorized(error)) onUnauthorized()
      setRemote({ status: 'error', message: errorText(error) })
    })
    return () => controller.abort()
  }, [householdId, query, category, page, retry, updateVersion, onUnauthorized])
  const search = (event: FormEvent) => { event.preventDefault(); setQuery(text.trim()); setPage(1) }
  const emptyFilteredResult = remote.status === 'loaded' && remote.data.items.length === 0 && Boolean(query || category)
  return <section className='space-y-4' aria-label='最近成果'>
    <div><h2 className='text-lg font-semibold'>最近成果</h2><p className='mt-1 text-sm text-muted-foreground'>练习、讲解、家长解析与五册文档按生成时间排列。制作新文档请切换上方分类。</p></div>
    <form role='search' className='flex flex-wrap items-end gap-3' onSubmit={search}>
      <label className='min-w-0 flex-1 text-sm'>搜索全部成果<input type='search' className='mt-1 h-10 w-full rounded-md border bg-background px-3' value={text} onChange={(event) => setText(event.target.value)} /></label>
      <label className='text-sm'>成果类型<select className='mt-1 block h-10 rounded-md border bg-background px-3' value={category} onChange={(event) => { setCategory(event.target.value); setPage(1) }}><option value=''>全部类型</option><option value='practice'>练习与复测</option><option value='knowledge'>知识讲解</option><option value='solution'>家长解析</option><option value='snapshot'>五册与学习报告</option></select></label>
      <Button type='submit' variant='outline'>查找成果</Button>
      {query || category ? (emptyFilteredResult ? null : <Button type='button' variant='ghost' onClick={() => { setText(''); setQuery(''); setCategory(''); setPage(1) }}>清除筛选</Button>) : null}
    </form>
    {remote.status === 'loading' ? <LoadingState label='正在读取成果…' /> : remote.status === 'error' ? <RetryState title='无法读取成果' message={remote.message} onRetry={() => setRetry((value) => value + 1)} /> : <>
      {!remote.data.items.length ? <div className='space-y-3'>
        <EmptyState
          title={query || category ? '当前筛选没有匹配成果' : '还没有生成成果'}
          detail={query || category ? '已有文档仍保留。清除筛选可查看其他成果。' : '已有资料和生成文档会显示在这里。可从上方选择文档类型开始制作。'}
        />
        {query || category ? <Button type='button' variant='outline' onClick={() => { setText(''); setQuery(''); setCategory(''); setPage(1) }}>清除筛选查看全部成果</Button> : null}
      </div> : <ul className='divide-y'>{remote.data.items.map((item) => <li key={item.id} className='space-y-2 py-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'><div><h3 className='font-semibold'>{item.title}</h3><p className='mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground'><span>{item.category_label}</span><span className='workspace-status-badge'>{item.state_label}</span><span>{new Date(item.created_at).toLocaleString('zh-CN')}</span></p></div><ApiLink href={item.detail_url}>查看详情与历史</ApiLink></div>
        {item.documents.map((document) => <div key={document.id} className='flex flex-wrap gap-3 text-sm'><span>{document.title}</span>{document.pdf_url ? <a href={document.pdf_url} data-preview-title={document.title} data-preview-pages={JSON.stringify(document.previews || (document.preview_url ? [document.preview_url] : []))} className='text-primary underline'>预览 PDF</a> : null}{document.docx_url ? <a href={document.docx_url} download className='text-primary underline'>下载 Word</a> : null}</div>)}
        {item.zip_url ? <a href={item.zip_url} download className='text-sm text-primary underline'>下载这批 ZIP</a> : null}
        <p className='text-xs text-muted-foreground'>{item.message || '内容、版式及 Word 客户端检查请在详情中核对。'}{item.checks.word_pc?.status === 'not_tested' || item.checks.word_macos?.status === 'not_tested' ? ' Microsoft Word 尚未实开验收。' : ''}</p>
      </li>)}</ul>}
      <div className='flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-sm'><span>{remote.data.total} 项成果 · 第 {remote.data.page} 页</span><div className='flex gap-2'><Button type='button' variant='outline' disabled={page === 1} onClick={() => setPage((value) => value - 1)}>上一页</Button><Button type='button' variant='outline' disabled={!remote.data.has_next} onClick={() => setPage((value) => value + 1)}>下一页</Button></div></div>
    </>}
  </section>
}
