import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePrivateDraft } from './use-private-draft'

const onUnauthorized = vi.fn()

function Harness() {
  const [payload, setPayload] = useState('')
  const [dirty, setDirty] = useState(false)
  const draft = usePrivateDraft({ key: 'test-draft', householdId: 'home-1', csrfToken: 'csrf', baseStamp: 'base-1', enabled: true, dirty, payload, onUnauthorized })
  return <div><label>内容<input aria-label='内容' value={payload} onChange={(event) => { setPayload(event.currentTarget.value); setDirty(true) }} /></label><button type='button' onClick={() => { void draft.tombstone() }}>清理草稿</button><button type='button' onClick={draft.keepCurrent}>保留当前内容</button><p>{draft.candidate ? '发现已保存草稿' : ''}</p><p role='alert'>{draft.loadError}</p><p role='status'>{draft.message}</p></div>
}

function SwitchingHarness() {
  const [key, setKey] = useState('key-a')
  const [payload, setPayload] = useState('')
  const [dirty, setDirty] = useState(false)
  const draft = usePrivateDraft({ key, householdId: 'home-1', csrfToken: 'csrf', baseStamp: `${key}-base`, enabled: true, dirty, payload, onUnauthorized })
  return <div><label>内容<input aria-label='内容' value={payload} onChange={(event) => { setPayload(event.currentTarget.value); setDirty(true) }} /></label><button type='button' onClick={() => { void draft.tombstone() }}>清理草稿</button><button type='button' onClick={() => { setKey('key-b'); setPayload(''); setDirty(false) }}>切换键</button><p role='status'>{draft.message}</p></div>
}

function draftResponse(version: number, payload: unknown) {
  return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'test-draft', version, base_stamp: 'base-1', payload, updated_at: '2026-10-05T00:00:00Z' } })
}

describe('usePrivateDraft write ordering', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('serializes delayed writes and eventually saves the latest payload', async () => {
    const requests: Array<Record<string, unknown>> = []
    let releaseFirst!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== 'POST') return Response.json({ schema_version: 'swb.api.v1', draft: null })
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      requests.push(body)
      if (requests.length === 1) return new Promise<Response>((resolve) => { releaseFirst = resolve })
      return draftResponse(Number(body.expected_version) + 1, body.payload)
    }))
    render(<Harness />)
    const input = await screen.findByRole('textbox', { name: '内容' })
    fireEvent.change(input, { target: { value: '第一版' } })
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2000 })
    fireEvent.change(input, { target: { value: '最终版' } })
    await new Promise((resolve) => setTimeout(resolve, 750))
    expect(requests).toHaveLength(1)

    releaseFirst(draftResponse(1, requests[0].payload))
    await waitFor(() => expect(requests).toHaveLength(2), { timeout: 2000 })
    expect(requests[1].payload).toBe('最终版')
    expect(requests[1].expected_version).toBe(1)
  })

  it('writes a tombstone after the in-flight draft and does not resurrect the old payload', async () => {
    const requests: Array<Record<string, unknown>> = []
    let releaseFirst!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== 'POST') return Response.json({ schema_version: 'swb.api.v1', draft: null })
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      requests.push(body)
      if (requests.length === 1) return new Promise<Response>((resolve) => { releaseFirst = resolve })
      return draftResponse(Number(body.expected_version) + 1, body.payload)
    }))
    render(<Harness />)
    fireEvent.change(await screen.findByRole('textbox', { name: '内容' }), { target: { value: '正式提交前内容' } })
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: '清理草稿' }))
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(requests).toHaveLength(1)

    releaseFirst(draftResponse(1, requests[0].payload))
    await waitFor(() => expect(requests).toHaveLength(2), { timeout: 2000 })
    expect(requests[1].expected_version).toBe(1)
    expect(requests[1].payload).toEqual({ cleared: true })
    await new Promise((resolve) => setTimeout(resolve, 750))
    expect(requests).toHaveLength(2)
  })

  it('ignores a late response after the key changes and uses the new key version', async () => {
    const requests: Array<{ key: string; body: Record<string, unknown> }> = []
    let releaseFirst!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.origin).pathname
      const key = decodeURIComponent(path.split('/').at(-2) || '')
      if (init?.method !== 'POST') {
        const draft = key === 'key-b' ? { key, version: 7, base_stamp: 'key-b-base', payload: { cleared: true }, updated_at: '2026-10-05T00:00:00Z' } : null
        return Response.json({ schema_version: 'swb.api.v1', draft })
      }
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      requests.push({ key, body })
      if (requests.length === 1) return new Promise<Response>((resolve) => { releaseFirst = resolve })
      return draftResponse(Number(body.expected_version) + 1, body.payload)
    }))

    render(<SwitchingHarness />)
    fireEvent.change(await screen.findByRole('textbox', { name: '内容' }), { target: { value: 'A内容' } })
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: '切换键' }))
    fireEvent.change(screen.getByRole('textbox', { name: '内容' }), { target: { value: 'B内容' } })
    await new Promise((resolve) => setTimeout(resolve, 750))
    expect(requests).toHaveLength(1)

    releaseFirst(draftResponse(50, requests[0].body.payload))
    await waitFor(() => expect(requests).toHaveLength(2), { timeout: 2000 })
    expect(requests[1].key).toBe('key-b')
    expect(requests[1].body.payload).toBe('B内容')
    expect(requests[1].body.expected_version).toBe(7)
  })

  it('does not autosave when loading the private draft failed', async () => {
    const calls: RequestInit[] = []
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(init || {})
      return Response.json({ schema_version: 'swb.api.v1', error: { code: 'unavailable', message: '暂时无法读取' } }, { status: 503 })
    }))
    render(<Harness />)
    fireEvent.change(await screen.findByRole('textbox', { name: '内容' }), { target: { value: '当前输入' } })
    expect((await screen.findByRole('alert')).textContent).toContain('暂时无法读取')
    await new Promise((resolve) => setTimeout(resolve, 750))
    expect(calls.length).toBeGreaterThan(0)
    expect(calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('waits for an explicit choice before replacing a stored candidate', async () => {
    const requests: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== 'POST') return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'test-draft', version: 3, base_stamp: 'base-1', payload: '已保存内容', updated_at: '2026-10-05T00:00:00Z' } })
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      requests.push(body)
      return draftResponse(Number(body.expected_version) + 1, body.payload)
    }))
    render(<Harness />)
    fireEvent.change(await screen.findByRole('textbox', { name: '内容' }), { target: { value: '当前输入' } })
    expect(await screen.findByText('发现已保存草稿')).toBeTruthy()
    await new Promise((resolve) => setTimeout(resolve, 750))
    expect(requests).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: '保留当前内容' }))
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2000 })
    expect(requests[0].expected_version).toBe(3)
    expect(requests[0].payload).toBe('当前输入')
  })

  it('abandons a pending tombstone when its draft scope changes during the wait', async () => {
    const requests: Array<{ key: string; body: Record<string, unknown> }> = []
    const getKeys: string[] = []
    let releaseFirst!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.origin).pathname
      const key = decodeURIComponent(path.split('/').at(-2) || '')
      if (init?.method !== 'POST') {
        getKeys.push(key)
        return Response.json({ schema_version: 'swb.api.v1', draft: null })
      }
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      requests.push({ key, body })
      return new Promise<Response>((resolve) => { releaseFirst = resolve })
    }))

    render(<SwitchingHarness />)
    fireEvent.change(await screen.findByRole('textbox', { name: '内容' }), { target: { value: 'A内容' } })
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: '清理草稿' }))
    fireEvent.click(screen.getByRole('button', { name: '切换键' }))
    await waitFor(() => expect(getKeys).toContain('key-b'))

    releaseFirst(Response.json({ schema_version: 'swb.api.v1', draft: { key: 'key-a', version: 1, base_stamp: 'key-a-base', payload: 'A内容', updated_at: '2026-10-05T00:00:00Z' } }))
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(requests).toHaveLength(1)
    expect(requests[0].key).toBe('key-a')
  })
})
