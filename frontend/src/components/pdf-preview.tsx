import { useEffect, useState } from 'react'
import { sameOriginHref } from './shared'
import { Button } from './ui/button'

/** A valid PDF response and an iframe load do not prove native PDF rendering. */
export function PdfPreview({ src, title, previews = [] }: { src: string; title: string; previews?: string[] }) {
  const safe = sameOriginHref(src)
  const [responseState, setResponseState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [retry, setRetry] = useState(0)
  const [imageRetry, setImageRetry] = useState(0)
  const [images, setImages] = useState(false)
  const [page, setPage] = useState(0)
  const [snapshotImages, setSnapshotImages] = useState<string[]>([])
  const [imageError, setImageError] = useState(false)
  const pageImages = (previews.length ? previews : snapshotImages).map(sameOriginHref).filter((value): value is string => Boolean(value))
  useEffect(() => {
    setSnapshotImages([])
    const match = safe?.match(/^\/prints\/snapshots\/(\d+)\/document\.pdf\/?(?:\?.*)?$/)
    if (!match) return
    const controller = new AbortController()
    void fetch(`/prints/snapshots/${match[1]}/preview/`, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal })
      .then(async (response) => response.ok ? response.json() : null)
      .then((data: unknown) => {
        if (controller.signal.aborted || !data || typeof data !== 'object' || !('pages' in data) || !Array.isArray(data.pages)) return
        setSnapshotImages(data.pages.filter((value): value is string => typeof value === 'string' && Boolean(sameOriginHref(value))))
      }).catch(() => { /* PDF open/download remain available if images cannot be discovered. */ })
    return () => controller.abort()
  }, [safe, retry])
  useEffect(() => {
    const controller = new AbortController()
    setResponseState('loading'); setMessage(''); setPage(0); setImageError(false)
    if (!safe) { setMessage('文档地址不可用。'); setResponseState('error'); return }
    const timeout = window.setTimeout(() => {
      setMessage('PDF 响应超时，可重试、打开原文档或查看逐页图片。')
      setResponseState('error'); controller.abort()
    }, 12000)
    void fetch(safe, { signal: controller.signal, credentials: 'same-origin', cache: 'no-store' }).then(async (response) => {
      const valid = response.ok && response.headers.get('content-type')?.includes('application/pdf')
      await response.body?.cancel()
      if (controller.signal.aborted) return
      if (!valid) {
        setMessage(response.status === 401 || response.status === 403 ? '无法访问文档，请重新登录或检查家庭权限。' : response.status === 410 ? '这份文档已退役，历史记录仍保留。' : 'PDF 暂时无法读取，可重试或打开原文档。')
        setResponseState('error')
      } else setResponseState('ready')
    }).catch(() => { if (!controller.signal.aborted) { setMessage('PDF 读取失败，请检查连接后重试。'); setResponseState('error') } }).finally(() => window.clearTimeout(timeout))
    return () => { window.clearTimeout(timeout); controller.abort() }
  }, [safe, retry])
  return <section className='flex min-h-0 flex-1 flex-col gap-3' aria-label={`${title} PDF 预览`}>
    <div className='flex flex-wrap items-center gap-3 text-sm'>
      <span>{title}</span>
      {safe ? <><a href={safe} target='_blank' rel='noopener noreferrer' className='text-primary underline'>打开 PDF</a><a href={safe} download className='text-primary underline'>下载 PDF</a></> : null}
      {pageImages.length ? <Button type='button' size='sm' variant='outline' onClick={() => { setImages((value) => !value); setImageError(false) }}>{images ? '返回 PDF 预览' : '预览空白？查看逐页图片'}</Button> : null}
    </div>
    {responseState === 'loading' ? <p role='status' className='text-sm text-muted-foreground'>正在读取 PDF 响应…</p> : null}
    {responseState === 'error' ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm'><span>{message}</span><Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试预览</Button></div> : null}
    {images && pageImages.length ? <div className='space-y-3'>
      {imageError ? <p role='alert'>这一页图片暂时无法读取，可重试或打开 PDF。</p> : null}
      <img key={`${pageImages[page]}:${imageRetry}`} src={pageImages[page]} alt={`${title} 第 ${page + 1} 页`} className='h-auto max-w-full rounded-md border' onError={() => setImageError(true)} />
      <div className='flex items-center gap-3'><Button type='button' variant='outline' disabled={!page} onClick={() => { setPage((value) => value - 1); setImageError(false) }}>上一页</Button><span>第 {page + 1} / {pageImages.length} 页</span><Button type='button' variant='outline' disabled={page === pageImages.length - 1} onClick={() => { setPage((value) => value + 1); setImageError(false) }}>下一页</Button>{imageError ? <Button type='button' variant='outline' onClick={() => { setImageRetry((value) => value + 1); setImageError(false) }}>重试图片</Button> : null}</div>
    </div> : safe && responseState === 'ready' ? <iframe tabIndex={-1} key={`${safe}:${retry}`} title={`${title} PDF 预览`} src={safe} className='min-h-[28rem] w-full flex-1 rounded-md border' onError={() => setMessage('浏览器未能显示预览，可切换逐页图片、打开或下载 PDF。')} /> : null}
    {responseState === 'ready' ? <p role='status' className='text-sm text-muted-foreground'>{message || 'PDF 响应可读取。若正文仍空白，请切换逐页图片，或打开／下载 PDF。'}</p> : null}
  </section>
}
