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
