import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SolutionWorkspace } from './workspace'
import type { AnySolutionContent, SolutionContent, SolutionOutput, SolutionWorkspaceResponse } from '../../types'

const content: SolutionContent = {
  schema_version: 'swb.solution.v1',
  title: '测试解析',
  lectures: [{ id: 'lecture-1', title: '第 1 讲' }],
  questions: [],
  outputs: { per_question: ['pdf'], per_lecture: [], combined: [] },
}

const generationContent: SolutionContent = {
  ...content,
  questions: [{
    id: 'question-1', question_revision_id: null, lecture_id: 'lecture-1', number: '1', title: '题目一',
    statement: { text: '已核对题干', status: 'complete' }, sources: [{ page_id: 'page-1', region: null }],
    parts: [{ id: 'part-1', parent_id: null, label: '(1)', statement: '小问', answer: '答案', unit: null }],
    thinking: '思路', lecture_method: '讲义解法', alternative_method: '', steps: ['第一步'], pitfalls: [], formulas: [],
    figures: [], links: [], corrections: [], unknowns: [],
  }],
}

function response(overrides: Partial<SolutionWorkspaceResponse> = {}): SolutionWorkspaceResponse {
  return {
    schema_version: 'swb.api.v1', material: { id: 'material-1', title: '测试资料' }, writable: true,
    revision: null, initial_content: content, history: [], outputs: [], assets: [],
    pages: [{ id: 'page-1', label: '第 1 页', width: 100, height: 100, preview_url: '/preview/', detail_url: '/page/' }],
    questions: [], nodes: [], ...overrides,
  }
}

function emptyPrivateDraft() {
  return Response.json({ schema_version: 'swb.api.v1', draft: null })
}

function savedPrivateDraft(body: Record<string, unknown>) {
  return Response.json({ schema_version: 'swb.api.v1', draft: {
    key: 'solution:material-1', version: Number(body.expected_version) + 1, base_stamp: String(body.base_stamp),
    payload: body.payload, updated_at: '2026-10-05T00:00:01Z',
  } })
}

async function selectPanel(user: ReturnType<typeof userEvent.setup>, name: '编辑讲解' | '生成文件' | '历史版本') {
  await user.click(screen.getByRole('tab', { name: new RegExp(name) }))
}

async function openDocumentSettings(user: ReturnType<typeof userEvent.setup>) {
  const title = await screen.findByText('文档设置', { exact: true })
  if (!title.closest('details')?.open) await user.click(title)
}

describe('SolutionWorkspace', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('shows a failed initial read and retries the workspace request', async () => {
    const user = userEvent.setup()
    let reads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      reads += 1
      if (reads === 1) return Response.json({ schema_version: 'swb.api.v1', error: { code: 'temporary', message: '临时读取失败' } }, { status: 503 })
      return Response.json(response())
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect((await screen.findByRole('alert')).textContent).toContain('临时读取失败')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    expect(reads).toBe(2)
  })

  it('surfaces transient output polling errors and retries only on request', async () => {
    const user = userEvent.setup()
    const runningOutput: SolutionWorkspaceResponse['outputs'][number] = {
      id: 'output-1', revision_id: 1, revision_version: 1, version: 1, state: 'queued', state_label: '等待中',
      message: '文档在队列中', created_at: '2026-10-05T00:00:00Z', documents: [],
      checks: { content: { status: 'not_tested', notes: '' }, math: { status: 'not_tested', notes: '' }, pdf_visual: { status: 'not_tested', notes: '' }, word_pc: { status: 'not_tested', notes: '' }, word_macos: { status: 'not_tested', notes: '' } }, zip_url: null,
    }
    let reads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      reads += 1
      if (reads === 1) return Response.json(response({ outputs: [runningOutput] }))
      return Response.json({ schema_version: 'swb.api.v1', error: { code: 'temporary', message: '状态读取失败' } }, { status: 503 })
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite initialPanel='outputs' onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    expect((await screen.findByRole('alert', {}, { timeout: 5000 })).textContent).toContain('状态读取失败')
    expect(reads).toBe(2)
    await user.click(screen.getByRole('button', { name: '重试读取状态' }))
    await waitFor(() => expect(reads).toBe(3))
  })

  it('shows generated page previews for Word-only documents without a PDF iframe', async () => {
    const output: SolutionOutput = {
      id: 'output-word-only', revision_id: 1, revision_version: 1, version: 1, state: 'complete', state_label: '已生成',
      message: 'Word 输出已生成', created_at: '2026-10-05T00:00:00Z',
      documents: [{ id: 'document-word-only', title: '仅 Word 文档', organization: 'combined', question_ids: [], page_count: 1, pdf_url: null, docx_url: '/downloads/solutions/word.docx', previews: ['/previews/word-page-1.png'] }],
      checks: { content: { status: 'not_tested', notes: '' }, math: { status: 'not_tested', notes: '' }, pdf_visual: { status: 'not_tested', notes: '' }, word_pc: { status: 'not_tested', notes: '' }, word_macos: { status: 'not_tested', notes: '' } },
      zip_url: null,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      return Response.json(response({ outputs: [output] }))
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite initialPanel='outputs' onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    const preview = await screen.findByRole('img', { name: '仅 Word 文档 第 1 页预览' })
    expect(preview.getAttribute('src')).toBe('/previews/word-page-1.png')
    expect(screen.queryByTitle('仅 Word 文档 PDF 预览')).toBeNull()
    expect(screen.getByRole('tab', { name: /生成文件/ }).getAttribute('aria-selected')).toBe('true')
    expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull()
  })

  it('keeps editor inputs mounted and unchanged while switching panels', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      return Response.json(response())
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    await openDocumentSettings(user)
    const title = screen.getByRole('textbox', { name: '文档标题' }) as HTMLInputElement
    await user.type(title, '暂存内容')
    await selectPanel(user, '生成文件')
    expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull()
    await selectPanel(user, '编辑讲解')
    expect(screen.getByRole('textbox', { name: '文档标题' })).toBe(title)
    expect(title.value).toBe('测试解析暂存内容')
  })

  it('syncs route tabs without resetting editor input and reports explicit changes', async () => {
    const user = userEvent.setup()
    const onTabChange = vi.fn()
    const props = { materialId: 'material-1', householdId: 'household-1', csrfToken: 'csrf', canWrite: true, onUnauthorized: vi.fn(), onBack: vi.fn(), onTabChange }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      return Response.json(response())
    }))

    const view = render(<SolutionWorkspace {...props} initialTab='history' />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: /历史版本/ }).getAttribute('aria-selected')).toBe('true')
    await selectPanel(user, '编辑讲解')
    await openDocumentSettings(user)
    const title = screen.getByRole('textbox', { name: '文档标题' }) as HTMLInputElement
    await user.clear(title)
    await user.type(title, '保留的编辑内容')
    await selectPanel(user, '历史版本')
    expect(onTabChange).toHaveBeenLastCalledWith('history')

    view.rerender(<SolutionWorkspace {...props} initialTab='outputs' />)
    await waitFor(() => expect(screen.getByRole('tab', { name: /生成文件/ }).getAttribute('aria-selected')).toBe('true'))
    await selectPanel(user, '编辑讲解')
    expect(screen.getByRole('textbox', { name: '文档标题' })).toBe(title)
    expect(title.value).toBe('保留的编辑内容')
  })

  it('reuses action keys after a lost generation response and output-action response', async () => {
    const user = userEvent.setup()
    const revision: NonNullable<SolutionWorkspaceResponse['revision']> = {
      id: 1, version: 1, created_at: '2026-10-05T00:00:00Z', author: 'parent', reason: '已核对题目',
      content: generationContent, confirmed: false, gaps: [],
    }
    const checks: SolutionOutput['checks'] = {
      content: { status: 'not_tested', notes: '' }, math: { status: 'not_tested', notes: '' },
      pdf_visual: { status: 'not_tested', notes: '' }, word_pc: { status: 'not_tested', notes: '' },
      word_macos: { status: 'not_tested', notes: '' },
    }
    const queued: SolutionOutput = {
      id: 'output-generated', revision_id: 1, revision_version: 1, version: 1, state: 'queued', state_label: '等待中',
      message: '服务端队列中已有文档', created_at: '2026-10-05T00:00:01Z', documents: [], checks, zip_url: null,
    }
    const cancelled: SolutionOutput = {
      ...queued, version: 2, state: 'cancelled', state_label: '已取消', message: '服务端队列文档已取消',
    }
    const generationRequests: Array<Record<string, unknown>> = []
    const outputActionRequests: Array<Record<string, unknown>> = []
    const queuedByKey = new Map<string, SolutionOutput>()
    const cancelledByKey = new Map<string, SolutionOutput>()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.includes('/draft-save/')) return savedPrivateDraft(JSON.parse(String(init?.body)) as Record<string, unknown>)
      if (url.pathname.endsWith('/solutions/draft/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        const savedContent = body.content as AnySolutionContent
        return Response.json(response({ revision: { ...revision, version: Number(body.expected_version) + 1, content: savedContent, reason: String(body.reason) }, initial_content: savedContent }))
      }
      if (url.pathname.endsWith('/solutions/actions/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        generationRequests.push(body)
        const key = String(body.request_key)
        if (!queuedByKey.has(key)) queuedByKey.set(key, queued)
        if (generationRequests.length === 1) throw new Error('生成结果响应丢失')
        return Response.json(response({ revision, initial_content: generationContent, outputs: [...queuedByKey.values()] }))
      }
      if (url.pathname.endsWith('/solutions/outputs/output-generated/actions/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        outputActionRequests.push(body)
        const key = String(body.request_key)
        if (!cancelledByKey.has(key)) cancelledByKey.set(key, cancelled)
        if (outputActionRequests.length === 1) throw new Error('取消结果响应丢失')
        return Response.json(response({ revision, initial_content: generationContent, outputs: [...cancelledByKey.values()] }))
      }
      if (url.pathname.endsWith('/solutions/')) return Response.json(response({ revision, initial_content: generationContent }))
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    const onTabChange = vi.fn()
    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} onTabChange={onTabChange} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '生成 PDF / Word' }))
    expect((await screen.findByRole('alert')).textContent).toContain('生成结果响应丢失')
    await user.click(screen.getByRole('button', { name: '生成 PDF / Word' }))
    expect(await screen.findByText('服务端队列中已有文档')).toBeTruthy()
    expect(screen.getByRole('tab', { name: /生成文件/ }).getAttribute('aria-selected')).toBe('true')
    expect(onTabChange).toHaveBeenCalledWith('outputs')
    expect(generationRequests).toHaveLength(2)
    expect(generationRequests[0]).toMatchObject({ action: 'generate', expected_version: 1, reason: '整理逐题解析' })
    expect(generationRequests[1].request_key).toBe(generationRequests[0].request_key)
    expect(queuedByKey.size).toBe(1)

    await user.click(screen.getByRole('button', { name: '取消生成' }))
    expect((await screen.findByRole('alert')).textContent).toContain('取消结果响应丢失')
    await user.click(screen.getByRole('button', { name: '取消生成' }))
    expect(await screen.findByText('服务端队列文档已取消')).toBeTruthy()
    expect(outputActionRequests).toHaveLength(2)
    expect(outputActionRequests[0]).toMatchObject({ action: 'cancel', expected_version: 1, reason: '整理逐题解析' })
    expect(outputActionRequests[1].request_key).toBe(outputActionRequests[0].request_key)
    expect(cancelledByKey.size).toBe(1)
  })

  it('keeps an untouched v1 baseline stable after explicit confirmation', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    const revision: NonNullable<SolutionWorkspaceResponse['revision']> = {
      id: 1, version: 1, created_at: '2026-10-05T00:00:00Z', author: 'parent', reason: '已核对题目',
      content: generationContent, confirmed: false, gaps: [],
    }
    let current = response({ revision, initial_content: generationContent })
    let confirmation: Record<string, unknown> | null = null
    let privateContentWrites = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.includes('/draft-save/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        if ((body.payload as Record<string, unknown>).cleared !== true) privateContentWrites += 1
        return savedPrivateDraft(body)
      }
      if (url.pathname.endsWith('/solutions/actions/')) {
        confirmation = JSON.parse(String(init?.body)) as Record<string, unknown>
        current = response({ revision: { ...revision, confirmed: true }, initial_content: generationContent })
        return Response.json(current)
      }
      if (url.pathname.endsWith('/solutions/')) return Response.json(current)
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} onUnsavedChange={onUnsavedChange} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '明确确认解析' }))
    expect(await screen.findByText('当前正式版本已明确确认。修改并保存后会形成新的版本。')).toBeTruthy()
    await new Promise((resolve) => window.setTimeout(resolve, 800))

    expect(confirmation).toMatchObject({ action: 'confirm', expected_version: 1 })
    expect(privateContentWrites).toBe(0)
    expect(onUnsavedChange.mock.calls.some(([unsaved]) => unsaved === true)).toBe(false)
  })

  it('reuses a save key after a lost response for the unchanged draft payload', async () => {
    const user = userEvent.setup()
    const saves: Array<Record<string, unknown>> = []
    const committedByKey = new Map<string, SolutionWorkspaceResponse>()
    let releaseClear!: (response: Response) => void
    let clearBody: Record<string, unknown> | undefined
    const clearing = new Promise<Response>((resolve) => { releaseClear = resolve })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.includes('/draft-save/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        if ((body.payload as Record<string, unknown>).cleared === true) {
          clearBody = body
          return clearing
        }
        return savedPrivateDraft(body)
      }
      if (url.pathname.endsWith('/solutions/draft/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        saves.push(body)
        const key = String(body.request_key)
        if (!committedByKey.has(key)) {
          const savedContent = body.content as AnySolutionContent
          committedByKey.set(key, response({ revision: {
            id: 1, version: 1, created_at: '2026-10-05T00:00:01Z', author: 'parent', reason: String(body.reason),
            content: savedContent, confirmed: false, gaps: [],
          } }))
        }
        if (saves.length === 1) throw new Error('保存结果响应丢失')
        return Response.json(committedByKey.get(key))
      }
      if (url.pathname.endsWith('/solutions/')) return Response.json(response())
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: '保存为新版本' }))
    expect((await screen.findByRole('alert')).textContent).toContain('保存结果响应丢失')
    await user.click(screen.getByRole('button', { name: '保存为新版本' }))
    expect(await screen.findByText('已保存为版本 1。')).toBeTruthy()
    expect(saves).toHaveLength(2)
    expect(saves[0]).toMatchObject({ expected_version: 0, reason: '整理逐题解析' })
    expect(saves[1].request_key).toBe(saves[0].request_key)
    expect(committedByKey.size).toBe(1)
    await waitFor(() => expect(clearBody).toBeDefined())
    await act(async () => { releaseClear(savedPrivateDraft(clearBody!)); await clearing })
    expect(await screen.findByText('私人草稿已清理。')).toBeTruthy()
    expect(screen.queryByText('较早草稿已清理，正在保存最新内容…')).toBeNull()
  })

  it('loads older revisions and outputs with retryable cursors while preserving old outputs during polling', async () => {
    const user = userEvent.setup()
    const checks: SolutionOutput['checks'] = {
      content: { status: 'not_tested', notes: '' }, math: { status: 'not_tested', notes: '' },
      pdf_visual: { status: 'not_tested', notes: '' }, word_pc: { status: 'not_tested', notes: '' },
      word_macos: { status: 'not_tested', notes: '' },
    }
    const queued: SolutionOutput = {
      id: 'output-current', revision_id: 2, revision_version: 2, version: 1, state: 'queued', state_label: '排队中',
      message: '当前文档仍在生成', created_at: '2026-10-05T00:00:02Z', documents: [], checks, zip_url: null,
    }
    const completed: SolutionOutput = { ...queued, version: 2, state: 'complete', state_label: '已完成', message: '当前文档已完成' }
    const olderOutput: SolutionOutput = {
      ...queued, id: 'output-older', revision_id: 1, revision_version: 1, state: 'complete', state_label: '已完成',
      message: '更早文档保留', created_at: '2026-10-04T00:00:01Z',
    }
    const staleOverlap: SolutionOutput = { ...queued, state: 'running', message: '过期列表副本' }
    const olderSummary: SolutionWorkspaceResponse['history'][number] = {
      id: 1, version: 1, created_at: '2026-10-04T00:00:00Z', author: 'parent', reason: '旧版本', confirmed: false,
    }
    let solutionReads = 0
    let draftSaves = 0
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      calls.push(`${url.pathname}${url.search}`)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.includes('/draft-save/')) return savedPrivateDraft(JSON.parse(String(init?.body)) as Record<string, unknown>)
      if (url.pathname.endsWith('/solutions/history/')) return Response.json({
        schema_version: 'swb.api.v1', history: [olderSummary],
        nodes: [{ revision_id: 'node-old', kind: 'knowledge', label: '旧知识节点', detail_url: '/knowledge/entity/5/#revision-old' }],
        history_next_before: null,
      })
      if (url.pathname.endsWith('/solutions/outputs/')) return Response.json({ schema_version: 'swb.api.v1', outputs: [olderOutput, staleOverlap], output_next_before: null })
      if (url.pathname.endsWith('/solutions/draft/')) {
        draftSaves += 1
        return Response.json(response({ outputs: [completed], history_next_before: 2, output_next_before: 'output-older' }))
      }
      if (url.pathname.endsWith('/solutions/')) {
        solutionReads += 1
        return Response.json(response({ outputs: [solutionReads === 1 ? queued : completed], history_next_before: 2, output_next_before: 'output-older' }))
      }
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    await selectPanel(user, '历史版本')
    await user.click(screen.getByRole('button', { name: '读取更早版本' }))
    expect(await screen.findByText(/版本 1 · parent/)).toBeTruthy()
    expect(calls).toContain('/api/v1/materials/material-1/solutions/history/?before=2')

    await selectPanel(user, '生成文件')
    await user.click(screen.getByRole('button', { name: '读取更早文档' }))
    expect(await screen.findByText('更早文档保留')).toBeTruthy()
    expect(calls).toContain('/api/v1/materials/material-1/solutions/outputs/?before=output-older')
    await waitFor(() => expect(solutionReads).toBe(2), { timeout: 5000 })
    expect(screen.getByText('更早文档保留')).toBeTruthy()
    expect(screen.getByText('当前文档已完成')).toBeTruthy()
    expect(screen.queryByText('过期列表副本')).toBeNull()
    expect(screen.queryByRole('button', { name: '读取更早版本' })).toBeNull()
    expect(screen.queryByRole('button', { name: '读取更早文档' })).toBeNull()

    await selectPanel(user, '编辑讲解')
    await user.click(screen.getByRole('button', { name: '保存为新版本' }))
    await waitFor(() => expect(draftSaves).toBe(1))
    await selectPanel(user, '生成文件')
    expect(screen.getByText('更早文档保留')).toBeTruthy()
    expect(screen.getByText('当前文档已完成')).toBeTruthy()
    expect(screen.queryByText('过期列表副本')).toBeNull()
    expect(screen.queryByRole('button', { name: '读取更早版本' })).toBeNull()
    expect(screen.queryByRole('button', { name: '读取更早文档' })).toBeNull()
  })

  it('refreshes queued outputs from loaded older pages while polling the newest output page', async () => {
    const user = userEvent.setup()
    const checks: SolutionOutput['checks'] = {
      content: { status: 'not_tested', notes: '' }, math: { status: 'not_tested', notes: '' },
      pdf_visual: { status: 'not_tested', notes: '' }, word_pc: { status: 'not_tested', notes: '' },
      word_macos: { status: 'not_tested', notes: '' },
    }
    const latest: SolutionOutput = {
      id: 'output-latest', revision_id: 3, revision_version: 3, version: 1, state: 'complete', state_label: '已完成',
      message: '最新文档已完成', created_at: '2026-10-05T00:00:02Z', documents: [], checks, zip_url: null,
    }
    const queuedOlder: SolutionOutput = {
      ...latest, id: 'output-older-active', revision_id: 1, revision_version: 1, version: 1,
      state: 'queued', state_label: '等待中', message: '较早文档仍在生成', created_at: '2026-10-04T00:00:01Z',
    }
    const completedOlder: SolutionOutput = {
      ...queuedOlder, version: 2, state: 'complete', state_label: '已完成', message: '较早文档已生成完成',
    }
    let solutionReads = 0
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      calls.push(`${url.pathname}${url.search}`)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.endsWith('/solutions/outputs/')) return Response.json({ schema_version: 'swb.api.v1', outputs: [queuedOlder], output_next_before: null })
      if (url.pathname.endsWith('/solutions/outputs/output-older-active/')) return Response.json({ schema_version: 'swb.api.v1', output: completedOlder })
      if (url.pathname.endsWith('/solutions/')) {
        solutionReads += 1
        return Response.json(response({ outputs: [latest], output_next_before: 'output-older-active' }))
      }
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite initialPanel='outputs' onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: '测试资料 · 逐题讲解' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '读取更早文档' }))
    expect(await screen.findByText('较早文档仍在生成')).toBeTruthy()
    expect(await screen.findByText('较早文档已生成完成', {}, { timeout: 5000 })).toBeTruthy()
    expect(solutionReads).toBe(2)
    expect(calls).toContain('/api/v1/solutions/outputs/output-older-active/')
  })

  it('autosaves complete form fields privately without appending official history while retaining null source and unit values', async () => {
    const user = userEvent.setup()
    const onUnsavedChange = vi.fn()
    const saves: Array<Record<string, unknown>> = []
    let current = response()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.includes('/draft-save/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        saves.push(body)
        return savedPrivateDraft(body)
      }
      if (url.pathname.endsWith('/solutions/draft/')) throw new Error('private autosave must not create an official revision')
      if (url.pathname.endsWith('/solutions/')) return Response.json(current)
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} onUnsavedChange={onUnsavedChange} />)
    await user.click(await screen.findByRole('button', { name: '添加题目' }))
    await user.type(screen.getByLabelText('题号'), '3')
    await user.type(screen.getByLabelText('题目标题'), '整式计算')
    await user.click(screen.getByRole('button', { name: '加入整页来源（范围未知）' }))
    await user.click(screen.getByRole('button', { name: '添加顶层小问' }))
    await user.type(screen.getByLabelText('小问标记'), '(1)')

    await waitFor(() => expect(saves).toHaveLength(1), { timeout: 4000 })
    expect(await screen.findByText('私人草稿已保存。')).toBeTruthy()
    await waitFor(() => expect(onUnsavedChange).toHaveBeenLastCalledWith(false))
    expect(screen.queryByText('已保存为版本 1。')).toBeNull()
    const first = (saves[0].payload as { content: AnySolutionContent }).content
    expect(first.questions[0]).toMatchObject({
      number: '3', title: '整式计算',
      sources: [{ page_id: 'page-1', region: null }],
      parts: [{ label: '(1)', statement: null, answer: null, unit: null }],
      statement: { text: null, status: 'unknown' },
    })
    expect(saves[0].expected_version).toBe(0)

    await openDocumentSettings(user)
    await user.type(screen.getByRole('textbox', { name: '文档标题' }), ' 修订')
    await waitFor(() => expect(saves).toHaveLength(2), { timeout: 4000 })
    expect(saves[1].expected_version).toBe(1)
    expect(saves[1].request_key).not.toBe(saves[0].request_key)
    expect(current.revision).toBeNull()
  })

  it('keeps edits made during an official save in the private draft and restores them after reload', async () => {
    const user = userEvent.setup()
    let storedDraft: { key: string; version: number; base_stamp: string; payload: Record<string, unknown>; updated_at: string } | null = null
    let current = response()
    const officialSaveBody: { current: Record<string, unknown> | null } = { current: null }
    let resolveOfficialSave: (response: Response) => void = () => undefined
    const officialSave = new Promise<Response>((resolve) => { resolveOfficialSave = resolve })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: storedDraft })
      if (url.pathname.includes('/draft-save/')) {
        const body = JSON.parse(String(init?.body)) as { expected_version: number; base_stamp: string; payload: Record<string, unknown> }
        storedDraft = {
          key: 'solution:material-1', version: body.expected_version + 1, base_stamp: body.base_stamp,
          payload: body.payload, updated_at: '2026-10-05T00:00:02Z',
        }
        return Response.json({ schema_version: 'swb.api.v1', draft: storedDraft })
      }
      if (url.pathname.endsWith('/solutions/draft/')) {
        officialSaveBody.current = JSON.parse(String(init?.body)) as Record<string, unknown>
        return officialSave
      }
      if (url.pathname.endsWith('/solutions/')) return Response.json(current)
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    const props = { materialId: 'material-1', householdId: 'household-1', csrfToken: 'csrf', canWrite: true, onUnauthorized: vi.fn(), onBack: vi.fn() }
    const firstMount = render(<SolutionWorkspace {...props} />)
    await openDocumentSettings(user)
    const titleInput = await screen.findByRole('textbox', { name: '文档标题' })
    await user.clear(titleInput)
    await user.type(titleInput, '正式保存内容 A')
    await user.click(screen.getByRole('button', { name: '保存为新版本' }))
    await screen.findByText('正在保存正式解析版本…')
    await waitFor(() => expect(officialSaveBody.current).not.toBeNull())
    const saveBody = officialSaveBody.current
    if (!saveBody) throw new Error('official save request was not received')
    const savedContent = saveBody.content as AnySolutionContent
    expect(savedContent.title).toBe('正式保存内容 A')

    await user.clear(titleInput)
    await user.type(titleInput, '继续编辑内容 B')
    const revision: NonNullable<SolutionWorkspaceResponse['revision']> = {
      id: 1, version: 1, created_at: '2026-10-05T00:00:01Z', author: 'parent', reason: '整理逐题解析',
      content: savedContent, confirmed: false, gaps: [],
    }
    current = response({ revision, initial_content: savedContent })
    resolveOfficialSave(Response.json(current))
    await waitFor(() => {
      const payload = storedDraft?.payload
      expect(payload && 'content' in payload && (payload.content as AnySolutionContent).title).toBe('继续编辑内容 B')
    }, { timeout: 4000 })

    firstMount.unmount()
    render(<SolutionWorkspace {...props} />)
    expect(await screen.findByText('发现未处理的私人草稿')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '恢复私人草稿' }))
    await openDocumentSettings(user)
    expect((await screen.findByRole('textbox', { name: '文档标题' }) as HTMLInputElement).value).toBe('继续编辑内容 B')
  })

  it.each([
    ['incomplete v2 content', { content: { schema_version: 'swb.solution.v2' }, reason: '未完成的数据' }],
    ['non-object payload', null],
  ])('explains and allows clearing an unrecognized private draft (%s)', async (_description, payload) => {
    const user = userEvent.setup()
    let cleared = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: {
        key: 'solution:material-1', version: 2, base_stamp: JSON.stringify([0, '']), payload, updated_at: '2026-10-05T00:00:02Z',
      } })
      if (url.pathname.includes('/draft-save/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        cleared = (body.payload as Record<string, unknown>).cleared === true
        return savedPrivateDraft(body)
      }
      if (url.pathname.endsWith('/solutions/')) return Response.json(response())
      throw new Error(`unexpected request ${url.pathname}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    expect(await screen.findByText('发现未处理的私人草稿')).toBeTruthy()
    expect(await screen.findByText('这份私人草稿内容无法识别；可以将它清理后继续。')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '比较内容' })).toBeNull()
    expect(screen.queryByRole('button', { name: '恢复私人草稿' })).toBeNull()
    await user.click(screen.getByRole('button', { name: '丢弃这份私人草稿' }))
    expect(await screen.findByText('私人草稿已清理。')).toBeTruthy()
    expect(cleared).toBe(true)
  })

  it('keeps local form text visible after a stale save and loads full history content for comparison', async () => {
    const user = userEvent.setup()
    const reviewContent: SolutionContent = { ...content, questions: [{
      id: 'question-1', question_revision_id: 'question-revision-1', lecture_id: 'lecture-1', number: '3', title: '测试题',
      statement: { text: '已核对题干', status: 'complete' }, sources: [{ page_id: 'page-1', region: [0, 0, 20, 20] }],
      parts: [{ id: 'part-1', parent_id: null, label: '(1)', statement: '小问', answer: '答案', unit: null }],
      thinking: '思路', lecture_method: '讲义解法', alternative_method: '', steps: ['第一步'], pitfalls: [], formulas: [],
      figures: [], links: [{ revision_id: 'node-revision-1', relation: 'knowledge' }], corrections: [], unknowns: [],
    }] }
    const savedRevision = { id: 17, version: 4, created_at: '2026-10-05T00:00:00Z', author: 'other', reason: '并发更新', content: { ...reviewContent, title: '服务器版本' }, confirmed: false, gaps: [] }
    const initial = response({
      revision: { ...savedRevision, content: { ...reviewContent, title: '基础版本' } },
      history: [{ id: 17, version: 4, created_at: savedRevision.created_at, author: 'other', reason: '并发更新', confirmed: false }],
      questions: [{ revision_id: 'question-revision-1', label: '历史题目 3', statement: '测试题', sources: [], detail_url: '/catalogue/question/3/#revision-question' }],
      nodes: [{ revision_id: 'node-revision-1', kind: 'knowledge', label: '第 1 版（历史版本）', detail_url: '/knowledge/entity/44/#revision-node' }],
    })
    let requestedRevision = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return emptyPrivateDraft()
      if (url.pathname.includes('/draft-save/')) return savedPrivateDraft(JSON.parse(String(init?.body)) as Record<string, unknown>)
      if (url.pathname.endsWith('/solutions/draft/')) return Response.json({ schema_version: 'swb.api.v1', error: { code: 'stale_solution', message: '解析已在其他页面更新。' } }, { status: 409 })
      if (url.pathname.endsWith('/solutions/')) return Response.json(initial)
      if (url.pathname.endsWith('/solutions/revisions/17/')) {
        requestedRevision = true
        return Response.json({ schema_version: 'swb.api.v1', revision: savedRevision })
      }
      throw new Error(`unexpected request ${url.pathname} ${init?.method || ''}`)
    }))

    render(<SolutionWorkspace materialId='material-1' householdId='household-1' csrfToken='csrf' canWrite onUnauthorized={vi.fn()} onBack={vi.fn()} />)
    await openDocumentSettings(user)
    const titleInput = await screen.findByRole('textbox', { name: '文档标题' })
    await user.clear(titleInput)
    await user.type(titleInput, '我的本地草稿')
    await user.click(screen.getByRole('button', { name: '保存为新版本' }))
    expect(await screen.findByText(/本地输入仍保留/)).toBeTruthy()
    expect((screen.getByRole('textbox', { name: '文档标题' }) as HTMLInputElement).value).toBe('我的本地草稿')

    await selectPanel(user, '历史版本')
    await user.click(screen.getByRole('button', { name: '打开并对照' }))
    expect((await screen.findAllByText(/版本 4/)).length).toBeGreaterThan(0)
    await waitFor(() => expect(requestedRevision).toBe(true))
    expect((await screen.findAllByText(/服务器版本/)).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('我的本地草稿')).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: '历史题目 3' })[0].getAttribute('href')).toBe('/catalogue/question/3/#revision-question')
    expect(screen.getAllByRole('link', { name: '第 1 页' })[0].getAttribute('href')).toBe('/page/')
    expect(screen.getAllByRole('link', { name: '第 1 版（历史版本）' })[0].getAttribute('href')).toBe('/knowledge/entity/44/#revision-node')
    expect(requestedRevision).toBe(true)
  })
})
