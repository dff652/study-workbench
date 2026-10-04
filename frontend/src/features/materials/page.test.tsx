import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MaterialUploadQueue } from './page'

describe('MaterialUploadQueue', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('uploads multiple files in order and retries a failed image with its original idempotency key', async () => {
    const user = userEvent.setup()
    const calls: Array<{ name: string; key: string }> = []
    let failedFirst = true
    const onUploaded = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.body as FormData
      const file = body.get('file') as File
      const key = String(body.get('request_key'))
      calls.push({ name: file.name, key })
      if (file.name === 'first.png' && failedFirst) {
        failedFirst = false
        return Response.json({ schema_version: 'swb.api.v1', error: { code: 'upload_failed', message: '临时失败' } }, { status: 500 })
      }
      return Response.json({ schema_version: 'swb.api.v1', page_id: file.name, duplicate: false })
    }))

    render(<MaterialUploadQueue materialId='material-1' csrfToken='csrf' canWrite onUploaded={onUploaded} onUnauthorized={vi.fn()} onBusyChange={vi.fn()} />)
    const files = [new File(['one'], 'first.png', { type: 'image/png' }), new File(['two'], 'second.png', { type: 'image/png' })]
    fireEvent.change(screen.getByLabelText('选择多张原图'), { target: { files } })
    await user.click(screen.getByRole('button', { name: '上传待处理原图（2）' }))
    expect(await screen.findByText('临时失败')).toBeTruthy()
    expect(screen.getByText('second.png').closest('li')?.textContent).toContain('上传完成')
    expect(calls.map((call) => call.name)).toEqual(['first.png', 'second.png'])

    await user.click(screen.getByRole('button', { name: '重试此图' }))
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[2].name).toBe('first.png')
    expect(calls[2].key).toBe(calls[0].key)
    expect(onUploaded).toHaveBeenCalledTimes(2)
  })
})
