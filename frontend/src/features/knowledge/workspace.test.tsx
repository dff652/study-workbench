import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { newKnowledgeItem } from './model'
import type { KnowledgeContent, KnowledgeOutput, KnowledgeRevision, KnowledgeWorkspaceResponse } from './types'
import { KnowledgeWorkspace } from './workspace'

function content(): KnowledgeContent {
  const item = newKnowledgeItem('lecture-1', 1)
  item.id = 'even-sum'; item.title = '偶数之和'; item.kind = 'theorem'
  item.original = item.statement = '两个偶整数的和仍为偶整数。'
  item.definitions = '偶整数可以写成二乘整数。'; item.conditions = ['两个加数均为偶整数。']
  item.sources = [{ page_id: 'page-1', region: null, printed_page: '1' }]
  item.steps = item.steps.map((step) => ({ ...step, text: step.section === 'conclusion' ? item.statement : '按定义写成二乘整数，并逐步说明整数封闭性。' }))
  return { schema_version: 'swb.knowledge.v1', title: '匿名知识讲解', school_subject: 'mathematics', learner_level: '初中',
    lectures: [{ id: 'lecture-1', title: '偶数', rule_profile: 'mathematics' }], knowledge: [item],
    outputs: { inventory: ['pdf'], per_knowledge: ['pdf'], per_lecture: [], combined: ['pdf', 'docx'] } }
}
function revision(value: KnowledgeContent, version = 1): KnowledgeRevision {
  return { id: version, mode: 'knowledge', version, author: 'parent', created_at: '2026-10-05T00:00:00Z', reason: '人工知识整理', confirmed: false, content: value, gaps: [] }
}
function response(patch: Partial<KnowledgeWorkspaceResponse> = {}): KnowledgeWorkspaceResponse {
  return { schema_version: 'swb.api.v1', mode: 'knowledge', material: { id: 'material-1', title: '测试资料', subject: 'unknown', version: 0 },
    writable: true, revision: null, initial_content: content(), source_stamp: 'source-1', history: [], outputs: [],
    history_next_before: null, output_next_before: null, assets: [], nodes: [],
    pages: [{ id: 'page-1', label: '第 1 页', width: 100, height: 100, preview_url: '/page/preview/', detail_url: '/page/detail/' }], ...patch }
}
function json(value: unknown, status = 200) { return Response.json({ schema_version: 'swb.api.v1', ...value as object }, { status }) }
function privateReply(body: Record<string, unknown>) {
  return json({ draft: { key: 'knowledge:material-1', version: Number(body.expected_version) + 1, payload: body.payload, base_stamp: body.base_stamp, updated_at: '2026-10-05T00:00:01Z' } })
}
async function settings(user: ReturnType<typeof userEvent.setup>) { const title = await screen.findByText('讲解文档设置', { exact: true }); if (!title.closest('details')?.open) await user.click(title) }
const props = { materialId: 'material-1', householdId: 'home-1', csrfToken: 'csrf', canWrite: true, onUnauthorized: vi.fn(), onBack: vi.fn() }

describe('knowledge companion workspace', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); props.onUnauthorized.mockClear() })

  it('resolves the material household before enabling editing or reading a private draft', async () => {
    const scope = vi.fn(); const paths: string[] = []
    const data = response(); data.material.household_id = 'home-2'
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      paths.push(new URL(String(input), window.location.origin).pathname)
      return json(data)
    }))
    render(<KnowledgeWorkspace {...props} onScopeLoaded={scope} />)
    expect(await screen.findByText('这份资料属于另一个家庭，请切换到该家庭后重新打开。')).toBeTruthy()
    expect(scope).toHaveBeenCalledWith({ household_id: 'home-2', learner_id: '' }, '/__app__/knowledge-explanations/material-1/')
    expect(paths.some((path) => path.includes('/drafts/') || path.includes('/draft-save/'))).toBe(false)
    expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull()
  })

  it('labels the selected source image with its actual page position', async () => {
    const user = userEvent.setup(); const data = response({ revision: revision(content()) })
    data.pages.push({ id: 'page-2', label: '第 7 页', position: 7, sha256: 'synthetic-sha', width: 80, height: 60, preview_url: '/source-2/', detail_url: '/page-2/' })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => new URL(String(input), window.location.origin).pathname.includes('/drafts/') ? json({ draft: null }) : json(data)))
    render(<KnowledgeWorkspace {...props} />)
    await user.selectOptions(await screen.findByRole('combobox', { name: '对照原图' }), 'page-2')
    expect(screen.getByRole('img', { name: '资料页 7 原图' })).toBeTruthy()
  })

  it('ignores an expired-session response for history after the work area was left', async () => {
    const user = userEvent.setup(); let release: ((response: Response) => void) | undefined
    const current = revision(content())
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return json({ draft: null })
      if (url.pathname.endsWith('/solutions/revisions/1/')) return new Promise<Response>((resolve) => { release = resolve })
      return json(response({ revision: current, history: [{ id: current.id, mode: 'knowledge', version: 1, author: current.author, reason: current.reason, created_at: current.created_at, confirmed: false }] }))
    }))
    const view = render(<KnowledgeWorkspace {...props} />)
    await screen.findByRole('heading', { name: '测试资料 · 知识点讲解' })
    await user.click(screen.getByRole('tab', { name: /历史版本/ }))
    await user.click(screen.getByRole('button', { name: '打开并对照' }))
    await screen.findByText('正在读取该版本的完整内容…'); view.unmount()
    await act(async () => release?.(json({ error: { code: 'unauthorized', message: '旧请求的会话已过期' } }, 401)))
    expect(props.onUnauthorized).not.toHaveBeenCalled()
  })

  it('uses a separate private draft key and keeps input when changing panels', async () => {
    const user = userEvent.setup(); const writes: Array<Record<string, unknown>> = []; const keys: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) { keys.push(decodeURIComponent(url.pathname)); return json({ draft: null }) }
      if (url.pathname.includes('/draft-save/')) { const body = JSON.parse(String(init?.body)); writes.push(body); return privateReply(body) }
      return json(response())
    }))
    render(<KnowledgeWorkspace {...props} />)
    await settings(user); const title = screen.getByRole('textbox', { name: '文档标题' })
    await user.clear(title); await user.type(title, '保留输入')
    await user.click(screen.getByRole('tab', { name: /生成文件/ })); await user.click(screen.getByRole('tab', { name: '编辑讲解' }))
    expect((screen.getByRole('textbox', { name: '文档标题' }) as HTMLInputElement).value).toBe('保留输入')
    await waitFor(() => expect(writes.some((body) => (body.payload as { content?: KnowledgeContent }).content?.title === '保留输入')).toBe(true), { timeout: 2500 })
    expect(keys).toEqual(['/api/v1/drafts/knowledge:material-1/'])
  })

  it('preserves typed content on conflict and requires an explicit comparison before a new append', async () => {
    const user = userEvent.setup(); const official: Record<string, unknown>[] = []; let reads = 0
    const server = content(); server.title = '另一窗口内容'
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return json({ draft: null })
      if (url.pathname.includes('/draft-save/')) return privateReply(JSON.parse(String(init?.body)))
      if (url.pathname.endsWith('/knowledge-explanations/draft/')) {
        const body = JSON.parse(String(init?.body)); official.push(body)
        if (official.length === 1) return json({ error: { code: 'stale_solution', message: '另一窗口已更新' } }, 409)
        return json(response({ revision: revision(body.content, 3), saved_revision: revision(body.content, 3), saved_source_stamp: 'source-1' }))
      }
      reads += 1; return json(reads === 1 ? response({ revision: revision(content()) }) : response({ revision: revision(server, 2) }))
    }))
    render(<KnowledgeWorkspace {...props} />); await settings(user)
    const title = screen.getByRole('textbox', { name: '文档标题' }); await user.clear(title); await user.type(title, '本页草稿')
    await user.click(screen.getByRole('button', { name: '保存为新版本' }))
    expect(await screen.findByText(/本地输入仍保留/)).toBeTruthy()
    expect((title as HTMLInputElement).value).toBe('本页草稿')
    await user.click(await screen.findByRole('button', { name: '保留本页输入，另存为版本 3' }))
    expect(await screen.findByText(/已保存为版本 3/)).toBeTruthy()
    expect(official[1]).toMatchObject({ expected_version: 2, content: { title: '本页草稿' } })
  })

  it('does not confirm another window revision returned after a successful save', async () => {
    const user = userEvent.setup(); let actions = 0
    const server = content(); server.title = '其他窗口版本'
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return json({ draft: null })
      if (url.pathname.includes('/draft-save/')) return privateReply(JSON.parse(String(init?.body)))
      if (url.pathname.endsWith('/knowledge-explanations/draft/')) {
        const body = JSON.parse(String(init?.body)); return json(response({ revision: revision(server, 2), saved_revision: revision(body.content), saved_source_stamp: 'source-1' }))
      }
      if (url.pathname.endsWith('/knowledge-explanations/actions/')) { actions += 1; return json(response()) }
      return json(response())
    }))
    render(<KnowledgeWorkspace {...props} />); await settings(user)
    const title = screen.getByRole('textbox', { name: '文档标题' }); await user.clear(title); await user.type(title, '明确确认这份')
    await user.click(screen.getByRole('button', { name: '明确确认讲解' }))
    expect(await screen.findByText(/本页内容已保存为版本 1/)).toBeTruthy()
    expect(actions).toBe(0); expect((title as HTMLInputElement).value).toBe('明确确认这份')
    expect(await screen.findByRole('button', { name: '保留本页输入，另存为版本 3' })).toBeTruthy()
  })

  it('keeps newer local edits while an official save returns its earlier snapshot', async () => {
    const user = userEvent.setup(); let release: ((value: Response) => void) | undefined; let snapshot: KnowledgeContent | undefined
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.includes('/drafts/')) return json({ draft: null })
      if (url.pathname.includes('/draft-save/')) return privateReply(JSON.parse(String(init?.body)))
      if (url.pathname.endsWith('/knowledge-explanations/draft/')) { snapshot = JSON.parse(String(init?.body)).content; return new Promise<Response>((resolve) => { release = resolve }) }
      return json(response())
    }))
    render(<KnowledgeWorkspace {...props} />); await settings(user)
    const title = screen.getByRole('textbox', { name: '文档标题' }); await user.clear(title); await user.type(title, '保存快照')
    await user.click(screen.getByRole('button', { name: '保存为新版本' })); await screen.findByText('正在保存正式知识讲解版本…')
    await user.clear(title); await user.type(title, '后来的输入')
    await act(async () => release?.(json(response({ revision: revision(snapshot!), saved_revision: revision(snapshot!), saved_source_stamp: 'source-1' }))))
    expect((title as HTMLInputElement).value).toBe('后来的输入'); expect(await screen.findByText(/保存后有新的输入/)).toBeTruthy()
  })

  it('restores a read-only history as editable content without rewriting it', async () => {
    const user = userEvent.setup(); const current = content(); current.title = '当前正式版'
    const historical = content(); historical.title = '历史完整讲解'; const posts: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (init?.method === 'POST') posts.push(url.pathname)
      if (url.pathname.includes('/drafts/')) return json({ draft: null })
      if (url.pathname.includes('/draft-save/')) return privateReply(JSON.parse(String(init?.body)))
      if (url.pathname.endsWith('/solutions/revisions/1/')) return json({ revision: revision(historical) })
      return json(response({ revision: revision(current, 2), history: [{ ...revision(historical), content: undefined, gaps: undefined }].map(({ content: _content, gaps: _gaps, ...row }) => row) }))
    }))
    render(<KnowledgeWorkspace {...props} />); await screen.findByRole('heading', { name: '测试资料 · 知识点讲解' })
    await user.click(screen.getByRole('tab', { name: /历史版本/ })); await user.click(screen.getByRole('button', { name: '打开并对照' }))
    await user.click(await screen.findByRole('button', { name: '用此历史内容继续编辑' })); await settings(user)
    expect((screen.getByRole('textbox', { name: '文档标题' }) as HTMLInputElement).value).toBe('历史完整讲解')
    expect(posts.some((path) => path.endsWith('/knowledge-explanations/draft/'))).toBe(false)
  })

  it('keeps Word checks untested and shows the knowledge review dimensions', async () => {
    const user = userEvent.setup()
    const checks = Object.fromEntries(['content', 'subject', 'pdf_visual', 'word_pc', 'word_macos'].map((name) => [name, { status: 'not_tested', notes: '' }])) as KnowledgeOutput['checks']
    const output: KnowledgeOutput = { id: 'knowledge-output', mode: 'knowledge', revision_id: 1, revision_version: 1, version: 3, state: 'output_check', state_label: '待检查', message: '', created_at: '2026-10-05T00:00:00Z', checks, zip_url: '/knowledge.zip', documents: [] }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/drafts/') ? json({ draft: null }) : json(response({ outputs: [output] }))))
    render(<KnowledgeWorkspace {...props} initialPanel='outputs' />); await screen.findByText('待检查 · 版本 1')
    await user.click(screen.getByText('逐项检查输出', { exact: true }))
    expect((screen.getByRole('combobox', { name: '学科依据与完整讲解' }) as HTMLSelectElement).value).toBe('not_tested')
    expect((screen.getByRole('combobox', { name: 'Windows Word 实机' }) as HTMLSelectElement).value).toBe('not_tested')
    expect(screen.queryByRole('combobox', { name: '数学正确性' })).toBeNull()
  })

  it('redirects on unauthorized load and exposes no editor write controls to a viewer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ error: { code: 'not_authenticated', message: '请登录' } }, 401)))
    const first = render(<KnowledgeWorkspace {...props} />); await screen.findByText('请登录'); expect(props.onUnauthorized).toHaveBeenCalled(); first.unmount()
    vi.stubGlobal('fetch', vi.fn(async () => json(response({ writable: false, revision: revision(content()) }))))
    render(<KnowledgeWorkspace {...props} canWrite={false} />); await screen.findByText(/当前为只读访问/)
    expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull()
    expect((screen.getByRole('textbox', { name: '完整结论' }) as HTMLTextAreaElement).disabled).toBe(true)
  })
})
