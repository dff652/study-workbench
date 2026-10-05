import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MaterialWorkspace } from './workspace'
import type { MaterialDetailResponse, WorkflowDetailResponse, WorkflowJob, WorkflowPreparationResponse } from '../../types'

const material = { id: 'material-1', title: '测试资料', page_count: 1, created_at: '2026-10-04T10:00:00Z', material_url: '/materials/material-1/', prepare_url: '/prepare/' }
const jobs: WorkflowJob[] = [1, 2].map((n) => ({
  id: `job-${n}`, material_id: material.id, state: 'ready', context: { version: 1, source_stamp: 'stamp' },
  created_at: `2026-10-04T0${3 - n}:00:00Z`, updated_at: '2026-10-04T10:00:00Z',
  error_code: null, record_count: 0, result: { learner_id: null },
}))
const detail: MaterialDetailResponse = {
  schema_version: 'swb.api.v1', material,
  pages: [{ id: 'page', position: 1, width: 100, height: 100, sha256: 'synthetic', page_url: '/page/', preview_url: '/preview/' }],
  readiness: { ready: true, gaps: [], content_gaps: [], questions: [] }, jobs,
}

function fixture(post?: () => Promise<Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && post) return post()
    const path = String(input)
    if (path.includes('/preparation/')) {
      const job = jobs.find((item) => path.includes(item.id))!
      const response: WorkflowPreparationResponse = {
        schema_version: 'swb.api.v1', job,
        config: { enabled: false, outbound_scope: null, max_requests: 0, max_seconds: 0, budget_usd: null },
        stages: [], limits: { used_requests: 0, max_requests: 0, max_seconds: 0 },
      }
      return Response.json(response)
    }
    if (path.includes('/workflows/')) {
      const job = jobs.find((item) => path.includes(item.id))!
      const response: WorkflowDetailResponse = {
        schema_version: 'swb.api.v1', job, sources: [], records: [], readiness: detail.readiness,
        events: [], links: { material_url: material.material_url, prepare_url: material.prepare_url, ai_url: '/ai/' },
      }
      return Response.json(response)
    }
    if (path.endsWith('/materials/material-1/content/')) {
      return Response.json({ schema_version: 'swb.api.v1', context: { source_stamp: 'stamp' }, questions: [], nodes: [] })
    }
    if (path.includes('/pages/page/reading/')) {
      return Response.json({ schema_version: 'swb.api.v1', context: { reading_version: 1 }, current: null, history: [] })
    }
    return Response.json(path.includes('/materials/material-1/') ? detail : { schema_version: 'swb.api.v1', items: [material], total: 1 })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={vi.fn()} />)
  return fetchMock
}

describe('MaterialWorkspace navigation', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('keeps the loaded material and selected task when clicking its current list row again', async () => {
    const user = userEvent.setup()
    fixture()
    await user.click(await screen.findByRole('tab', { name: /整理任务/ }))
    await screen.findByRole('button', { name: '加入处理队列' })
    await user.click(screen.getByRole('button', { name: /测试资料.*1 页/ }))
    expect(screen.getByRole('tab', { name: /整理任务/ }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('button', { name: '加入处理队列' })).toBeTruthy()
    expect(screen.queryByText('正在读取资料页、完整度和任务历史…')).toBeNull()
  })

  it('keeps visited tab inputs mounted and task selection opens the selected task', async () => {
    const user = userEvent.setup()
    const fetchMock = fixture()
    await user.click(await screen.findByRole('tab', { name: /整理任务/ }))
    await screen.findByRole('button', { name: '加入处理队列' })
    await user.click(screen.getByRole('button', { name: '新建整理任务' }))
    const choice = screen.getByLabelText(/所选学习者的全部历史记录/) as HTMLInputElement
    await user.click(choice)

    await user.click(screen.getByRole('tab', { name: /原图与进度/ }))
    expect(choice.isConnected).toBe(true)
    expect(choice.checked).toBe(true)
    await user.click(screen.getByRole('tab', { name: /整理任务/ }))
    expect(screen.getByLabelText(/所选学习者的全部历史记录/)).toBe(choice)

    await user.click(screen.getAllByRole('button', { name: '查看任务' })[0])
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/workflows/job-2/'))).toBe(true))
    expect(screen.getByRole('tab', { name: /整理任务/ }).getAttribute('aria-selected')).toBe('true')
  })

  it('keeps unsaved content input mounted while switching module tabs', async () => {
    const user = userEvent.setup()
    fixture()
    await user.click(await screen.findByRole('tab', { name: /题面核对/ }))
    const printed = await screen.findByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement
    await user.type(printed, '切换标签后仍保留')

    await user.click(screen.getByRole('tab', { name: /整理任务/ }))
    expect(printed.isConnected).toBe(true)
    await user.click(screen.getByRole('tab', { name: /题面核对/ }))
    expect(screen.getByLabelText('图中印刷题面转写（必填）')).toBe(printed)
    expect(printed.value).toBe('切换标签后仍保留')
  })

  it('confirms before changing materials or refreshing away from content input', async () => {
    const user = userEvent.setup()
    const other = { ...material, id: 'material-2', title: '第二份资料' }
    const onUnsavedChange = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/materials/') {
        return Response.json({ schema_version: 'swb.api.v1', items: [material, other], total: 2, page: 1, page_size: 20, has_next: false })
      }
      if (url.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      if (url.pathname === '/api/v1/materials/material-1/') return Response.json(detail)
      if (url.pathname === '/api/v1/materials/material-2/') return Response.json({ ...detail, material: other, jobs: [] })
      if (url.pathname.endsWith('/content/')) return Response.json({ schema_version: 'swb.api.v1', context: { source_stamp: 'stamp' }, questions: [], nodes: [] })
      if (url.pathname.endsWith('/reading/')) return Response.json({ schema_version: 'swb.api.v1', context: { reading_version: 1 }, current: null, history: [] })
      return Response.json({ schema_version: 'swb.api.v1' })
    }))
    render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={onUnsavedChange} />)
    const contentTab = await screen.findByRole('tab', { name: /题面核对/ })
    await user.click(contentTab)
    const printed = await screen.findByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement
    await user.type(printed, '尚未保存的题面')
    await waitFor(() => expect(onUnsavedChange).toHaveBeenLastCalledWith(true))

    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true).mockReturnValueOnce(false).mockReturnValueOnce(true)
    const otherRow = screen.getByRole('button', { name: /第二份资料/ })
    await user.click(otherRow)
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('尚未保存的题面')
    await user.click(otherRow)
    expect(await screen.findByRole('heading', { name: '第二份资料' })).toBeTruthy()

    await user.click(await screen.findByRole('tab', { name: /题面核对/ }))
    const otherInput = await screen.findByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement
    await user.type(otherInput, '第二份未保存题面')
    await waitFor(() => expect(onUnsavedChange).toHaveBeenLastCalledWith(true))
    await user.click(screen.getByRole('button', { name: '刷新资料' }))
    expect(otherInput.value).toBe('第二份未保存题面')
    await user.click(screen.getByRole('button', { name: '刷新资料' }))
    await screen.findByLabelText('图中印刷题面转写（必填）')
    expect((screen.getByLabelText('图中印刷题面转写（必填）') as HTMLTextAreaElement).value).toBe('')
    expect(confirm).toHaveBeenCalledTimes(4)
  })

  it('prevents task switching while a write is pending and restores navigation afterwards', async () => {
    const user = userEvent.setup()
    let finish!: (response: Response) => void
    const fetchMock = fixture(() => new Promise<Response>((resolve) => { finish = resolve }))
    await user.click(await screen.findByRole('tab', { name: /整理任务/ }))
    await user.click(await screen.findByRole('button', { name: '加入处理队列' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '查看任务' }).matches(':disabled')).toBe(true))
    await user.click(screen.getByRole('button', { name: '查看任务' }))
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/workflows/job-2/'))).toBe(false)
    await act(async () => finish(Response.json({ schema_version: 'swb.api.v1', job: { ...jobs[0], state: 'queued', context: { version: 2, source_stamp: 'stamp' } } })))
    await waitFor(() => expect(screen.getByRole('button', { name: '查看任务' }).matches(':disabled')).toBe(false))
  })

  it('sends search and pagination to the server', async () => {
    const user = userEvent.setup()
    const listRequests: URL[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/materials/') {
        listRequests.push(url)
        const page = Number(url.searchParams.get('page'))
        return Response.json({ schema_version: 'swb.api.v1', items: [material], total: 45, page, page_size: 20, has_next: page === 1 })
      }
      if (url.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      if (url.pathname === '/api/v1/materials/material-1/') return Response.json(detail)
      return Response.json({ schema_version: 'swb.api.v1', items: [] })
    }))
    render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={vi.fn()} />)
    await screen.findByRole('button', { name: /测试资料/ })
    await user.type(screen.getByPlaceholderText('输入资料名称'), '分数')
    await user.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(listRequests.some((url) => url.searchParams.get('q') === '分数' && url.searchParams.get('page') === '1' && url.searchParams.get('page_size') === '20')).toBe(true))

    await user.click(await screen.findByRole('button', { name: '下一页' }))
    await waitFor(() => expect(listRequests.some((url) => url.searchParams.get('q') === '分数' && url.searchParams.get('page') === '2' && url.searchParams.get('page_size') === '20')).toBe(true))
  })

  it('keeps a deep-linked material outside the current result page and reports location changes', async () => {
    const user = userEvent.setup()
    const deepMaterial = { ...material, id: 'private-material-key', title: '深链接资料' }
    const otherMaterial = { ...material, id: 'other-material', title: '列表中的资料' }
    const listRequests: URL[] = []
    const onLocationChange = vi.fn()
    const onTabChange = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/materials/') {
        listRequests.push(url)
        const page = Number(url.searchParams.get('page'))
        return Response.json({ schema_version: 'swb.api.v1', items: [otherMaterial], total: 45, page, page_size: 20, has_next: true })
      }
      if (url.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      if (url.pathname === `/api/v1/materials/${deepMaterial.id}/`) return Response.json({ ...detail, material: deepMaterial, jobs: [] })
      if (url.pathname === `/api/v1/materials/${otherMaterial.id}/`) return Response.json({ ...detail, material: otherMaterial, jobs: [] })
      return Response.json({ schema_version: 'swb.api.v1', items: [] })
    }))
    render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={vi.fn()} initialMaterialId={deepMaterial.id} initialQuery='关键字' initialPage={3} initialTab='pages' onLocationChange={onLocationChange} onTabChange={onTabChange} />)

    expect(await screen.findByRole('heading', { name: '深链接资料' })).toBeTruthy()
    await waitFor(() => expect(listRequests.some((url) => url.searchParams.get('q') === '关键字' && url.searchParams.get('page') === '3')).toBe(true))
    expect(screen.queryByText(deepMaterial.id)).toBeNull()
    expect(onLocationChange).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /列表中的资料/ }))
    expect(onLocationChange).toHaveBeenLastCalledWith({ materialId: otherMaterial.id, query: '关键字', page: 3 })
    expect(onTabChange).toHaveBeenLastCalledWith('pages')
    await screen.findByRole('heading', { name: '列表中的资料' })

    await user.type(screen.getByPlaceholderText('输入资料名称'), '补充')
    await user.click(screen.getByRole('button', { name: '搜索' }))
    expect(onLocationChange).toHaveBeenLastCalledWith({ materialId: otherMaterial.id, query: '关键字补充', page: 1 })
    await user.click(await screen.findByRole('button', { name: '下一页' }))
    expect(onLocationChange).toHaveBeenLastCalledWith({ materialId: otherMaterial.id, query: '关键字补充', page: 2 })
    await user.click(screen.getByRole('button', { name: '清除' }))
    expect(onLocationChange).toHaveBeenLastCalledWith({ materialId: otherMaterial.id, query: '', page: 1 })

    await user.click(screen.getByRole('tab', { name: /整理任务/ }))
    expect(onTabChange).toHaveBeenLastCalledWith('tasks')
  })

  it('ignores a delayed material list from a previous household', async () => {
    const oldMaterial = { ...material, id: 'old-material', title: '旧家庭资料' }
    const newMaterial = { ...material, id: 'new-material', title: '新家庭资料' }
    let resolveOld!: (response: Response) => void
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve })
    const listRequests: URL[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/materials/') {
        listRequests.push(url)
        if (url.searchParams.get('household') === 'home-a') return oldResponse
        return Response.json({ schema_version: 'swb.api.v1', items: [newMaterial], total: 1, page: 1, page_size: 20, has_next: false })
      }
      if (url.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      if (url.pathname === `/api/v1/materials/${newMaterial.id}/`) return Response.json({ ...detail, material: newMaterial, jobs: [] })
      return Response.json({ schema_version: 'swb.api.v1', items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    const props = { householdName: '家庭', csrfToken: 'synthetic', canWrite: true, learners: [], selectedLearnerId: '', onUnauthorized: vi.fn(), onOpenSolutions: vi.fn(), onUnsavedChange: vi.fn() }
    const view = render(<MaterialWorkspace {...props} householdId='home-a' />)
    await waitFor(() => expect(listRequests).toHaveLength(1))

    view.rerender(<MaterialWorkspace {...props} householdId='home-b' />)
    expect(await screen.findByRole('button', { name: /新家庭资料/ })).toBeTruthy()
    await act(async () => {
      resolveOld(Response.json({ schema_version: 'swb.api.v1', items: [oldMaterial], total: 1, page: 1, page_size: 20, has_next: false }))
      await oldResponse
    })
    expect(screen.queryByRole('button', { name: /旧家庭资料/ })).toBeNull()
    expect(screen.getByRole('button', { name: /新家庭资料/ })).toBeTruthy()
  })

  it('autosaves a material title once and settles after the saved state rerenders', async () => {
    const user = userEvent.setup()
    const draftSaves: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.startsWith('/api/v1/drafts/') || url.pathname.startsWith('/api/v1/draft-save/')) {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>
          draftSaves.push(body)
          return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'title-draft', version: Number(body.expected_version) + 1, base_stamp: 'material-title:v1', payload: body.payload, updated_at: '2026-10-05T00:00:00Z' } })
        }
        return Response.json({ schema_version: 'swb.api.v1', draft: null })
      }
      if (url.pathname === '/api/v1/materials/') return Response.json({ schema_version: 'swb.api.v1', items: [material], total: 1, page: 1, page_size: 20, has_next: false })
      if (url.pathname === '/api/v1/materials/material-1/') return Response.json(detail)
      return Response.json({ schema_version: 'swb.api.v1', items: [] })
    }))
    render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: '新建资料' }))
    await user.type(screen.getByLabelText('资料名称'), '数学周练')
    await waitFor(() => expect(draftSaves).toHaveLength(1), { timeout: 2500 })
    expect(draftSaves[0].payload).toEqual({ title: '数学周练' })
    await new Promise((resolve) => setTimeout(resolve, 900))
    expect(draftSaves).toHaveLength(1)
    expect(screen.getAllByText('私人草稿已保存。').length).toBeGreaterThan(0)
  })

  it('saves the new title when replacing a restored title immediately after clearing it', async () => {
    const user = userEvent.setup()
    const draftSaves: Array<Record<string, unknown>> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.startsWith('/api/v1/drafts/') || url.pathname.startsWith('/api/v1/draft-save/')) {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>
          draftSaves.push(body)
          return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'title-draft', version: Number(body.expected_version) + 1, base_stamp: 'material-title:v1', payload: body.payload, updated_at: '2026-10-05T00:00:00Z' } })
        }
        const titleDraft = url.pathname.includes('create-title')
          ? { key: 'materials:create-title', version: 3, base_stamp: 'material-title:v1', payload: { title: '旧名称' }, updated_at: '2026-10-05T00:00:00Z' }
          : null
        return Response.json({ schema_version: 'swb.api.v1', draft: titleDraft })
      }
      if (url.pathname === '/api/v1/materials/') return Response.json({ schema_version: 'swb.api.v1', items: [material], total: 1, page: 1, page_size: 20, has_next: false })
      if (url.pathname === '/api/v1/materials/material-1/') return Response.json(detail)
      return Response.json({ schema_version: 'swb.api.v1', items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<MaterialWorkspace householdId='household' householdName='我的家庭' csrfToken='synthetic' canWrite learners={[]} selectedLearnerId='' onUnauthorized={vi.fn()} onOpenSolutions={vi.fn()} onUnsavedChange={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: '恢复这份草稿' }))
    const titleInput = await screen.findByLabelText('资料名称')
    expect((titleInput as HTMLInputElement).value).toBe('旧名称')
    await user.clear(titleInput)
    await user.type(titleInput, '新名称')
    await waitFor(() => expect(draftSaves).toHaveLength(1), { timeout: 2500 })
    expect(draftSaves[0].expected_version).toBe(3)
    expect(draftSaves[0].payload).toEqual({ title: '新名称' })
    await new Promise((resolve) => setTimeout(resolve, 900))
    expect(draftSaves).toHaveLength(1)
  })
})
