import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { PdfPreview } from './pdf-preview'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('separates an unreadable PDF from the iframe and keeps retry/open/download available', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response('not PDF',{status:404})).mockResolvedValueOnce(new Response('PDF',{headers:{'content-type':'application/pdf'}}))
  vi.stubGlobal('fetch', fetcher)
  const view = render(<PdfPreview title='合成文档' src='/prints/synthetic.pdf' />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(view.container.querySelector('iframe')).toBeNull()
  expect(screen.getByRole('link',{name:'打开 PDF'}).getAttribute('href')).toBe('/prints/synthetic.pdf')
  expect(screen.getByRole('link',{name:'下载 PDF'})).toBeTruthy()
  await userEvent.click(screen.getByRole('button',{name:'重试预览'}))
  await waitFor(() => expect(view.container.querySelector('iframe')).not.toBeNull())
  expect(fetcher).toHaveBeenCalledTimes(2)
})
it('rejects an external preview without sending a request', async () => {
  const fetcher=vi.fn(); vi.stubGlobal('fetch',fetcher)
  render(<PdfPreview title='无效文档' src='https://outside.test/document.pdf' />)
  await screen.findByRole('alert')
  expect(fetcher).not.toHaveBeenCalled()
})
it('does not interpret iframe load as visible PDF and preserves paging on image retry', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('PDF', { headers: { 'content-type': 'application/pdf' } })))
  const view = render(<PdfPreview title='两页文档' src='/prints/synthetic.pdf' previews={['/prints/page-1.png', '/prints/page-2.png', 'https://outside.test/image.png']} />)
  await waitFor(() => expect(view.container.querySelector('iframe')).not.toBeNull())
  view.container.querySelector('iframe')!.dispatchEvent(new Event('load'))
  expect(screen.getByText(/PDF 响应可读取。若正文仍空白/)).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '预览空白？查看逐页图片' }))
  await userEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(screen.getByRole('img').getAttribute('src')).toBe('/prints/page-2.png')
  screen.getByRole('img').dispatchEvent(new Event('error'))
  await screen.findByRole('button', { name: '重试图片' })
  await userEvent.click(screen.getByRole('button', { name: '重试图片' }))
  expect(screen.getByRole('img').getAttribute('src')).toBe('/prints/page-2.png')
  expect(screen.getByText('第 2 / 2 页')).toBeTruthy()
})
it('reports a response timeout without losing open and download paths', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
  render(<PdfPreview title='慢响应' src='/prints/slow.pdf' />)
  const { act } = await import('@testing-library/react')
  await act(async () => { vi.advanceTimersByTime(12000) })
  expect(screen.getByRole('alert').textContent).toContain('PDF 响应超时')
  expect(screen.getByRole('link', { name: '下载 PDF' })).toBeTruthy()
  vi.useRealTimers()
})
