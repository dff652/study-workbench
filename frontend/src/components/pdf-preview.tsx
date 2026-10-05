import { useEffect, useState } from 'react'
import { sameOriginHref } from './shared'
import { Button } from './ui/button'

/** Loading a response and rendering a PDF are separate states. */
export function PdfPreview({ src, title }: { src: string; title: string }) {
  const safe = sameOriginHref(src)
  const [status, setStatus] = useState<'loading' | 'ready' | 'loaded' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setStatus('loading')
    if (!safe) { setMessage('文档地址不可用。'); setStatus('error'); return }
    void fetch(safe, { signal: controller.signal, credentials: 'same-origin' }).then(async (response) => {
      const valid = response.ok && response.headers.get('content-type')?.includes('application/pdf')
      await response.body?.cancel()
      if (controller.signal.aborted) return
      if (!valid) { setMessage(response.status === 401 || response.status === 403 ? '无法访问文档，请重新登录或检查家庭权限。' : 'PDF 暂时无法读取，可重试或打开原文档。'); setStatus('error') }
      else setStatus('ready')
    }).catch(() => { if (!controller.signal.aborted) { setMessage('PDF 读取失败，请检查连接后重试。'); setStatus('error') } })
    return () => controller.abort()
  }, [safe, retry])
  return <section className='flex min-h-0 flex-1 flex-col gap-2' aria-label={`${title} PDF 预览`}>
    <div className='flex flex-wrap items-center gap-3 text-sm'>
      <span>{title}</span>
      {safe ? <><a href={safe} target='_blank' rel='noopener noreferrer' className='text-primary underline'>打开 PDF</a><a href={safe} download className='text-primary underline'>下载 PDF</a></> : null}
    </div>
    {status === 'loading' || status === 'ready' ? <p role='status' className='text-sm text-muted-foreground'>正在加载 PDF…</p> : null}
    {status === 'error' ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm'><span>{message}</span><Button type='button' size='sm' variant='outline' onClick={() => setRetry((value) => value + 1)}>重试预览</Button></div> : null}
    {safe && (status === 'ready' || status === 'loaded') ? <iframe key={`${safe}:${retry}`} title={`${title} PDF 预览`} src={safe} className='min-h-[32rem] w-full flex-1 rounded-md border' onLoad={() => setStatus('loaded')} onError={() => { setMessage('浏览器未能加载预览，可打开或下载 PDF。'); setStatus('error') }} /> : null}
    {status === 'loaded' ? <p className='text-xs text-muted-foreground'>如预览未显示，请打开或下载 PDF；也可查看下方逐页图片。请按实际文档核对内容和版式。</p> : null}
  </section>
}
