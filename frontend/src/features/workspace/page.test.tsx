import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkspacePage } from './page'

const initialPage = {
  schema_version: 'swb.api.v1',
  page: {
    url: '/members/?household_id=home-1',
    title: '家庭成员',
    html: '<main><h1>家庭成员</h1><form method="post" action=""><label for="display-name">姓名</label><input id="display-name" name="display_name" value=""><button name="action" value="save">保存</button></form></main>',
    widgets: [],
  },
}

describe('WorkspacePage', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('reloads the saved state when a form redirects to the current page', async () => {
    let accepted = false
    let reads = 0
    let clearing = false
    let finishClear: (() => void) | undefined
    const clear = new Promise<void>((resolve) => { finishClear = resolve })
    const onNavigate = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const endpoint = new URL(String(input), window.location.origin)
      if (endpoint.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      if (endpoint.pathname.startsWith('/api/v1/draft-save/')) {
        clearing = true
        await clear
        return Response.json({ schema_version: 'swb.api.v1', draft: {
          key: decodeURIComponent(endpoint.pathname.split('/')[4]), version: 1,
          base_stamp: 'saved', payload: { cleared: true }, updated_at: '2026-10-05T04:00:00Z',
        } })
      }
      if (init?.method === 'POST') {
        accepted = true
        return Response.json({ schema_version: 'swb.api.v1', redirect: initialPage.page.url })
      }
      reads += 1
      return Response.json({ ...initialPage, page: { ...initialPage.page,
        scope: { household_id: 'home-1', learner_id: '' },
        html: accepted ? '<main><h1>审核完成</h1><p>已审核</p></main>' : initialPage.page.html,
      } })
    }))
    render(<WorkspacePage url={initialPage.page.url} householdId='home-1' canWrite csrfToken='csrf-1'
      onNavigate={onNavigate} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    await screen.findByLabelText('姓名')
    await waitFor(() => expect(screen.queryByText('正在打开页面…')).toBeNull())
    fireEvent.submit(document.querySelector('form') as HTMLFormElement)
    await waitFor(() => expect(clearing).toBe(true))
    expect(reads).toBe(1)
    await act(async () => { finishClear?.(); await clear })
    expect(await screen.findByRole('heading', { name: '审核完成' })).toBeTruthy()
    expect(reads).toBe(2)
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('renders a same-origin page and posts multipart data, preserving a page returned with HTTP 400', async () => {
    const onUnsavedChange = vi.fn()
    const onScopeLoaded = vi.fn()
    const calls: Array<{ url: URL; init?: RequestInit }> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      calls.push({ url, init })
      if (init?.method === 'POST') {
        return Response.json({
          schema_version: 'swb.api.v1',
          page: {
            ...initialPage.page,
            scope: { household_id: 'home-1', learner_id: 'learner-a' },
            html: '<main><h1>家庭成员</h1><details><summary>更多提示</summary><p role="alert">姓名不能为空</p><ul class="errorlist"><li>请完善此项</li></ul></details><form method="post"><label for="display-name">姓名</label><input id="display-name" name="display_name" value=""><button name="action" value="save">保存</button></form></main>',
          },
        }, { status: 400 })
      }
      return Response.json({ ...initialPage, page: { ...initialPage.page, scope: { household_id: 'home-1', learner_id: 'learner-a' } } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage url='/members/?household_id=home-1' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={vi.fn()} onScopeLoaded={onScopeLoaded} onUnauthorized={vi.fn()} onUnsavedChange={onUnsavedChange} />)

    expect(await screen.findByRole('heading', { name: '家庭成员', level: 1 })).toBeTruthy()
    const nameInput = screen.getByLabelText('姓名')
    fireEvent.input(nameInput, { target: { value: '小林' } })
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
    const form = document.querySelector('form')
    expect(form).not.toBeNull()
    const submitter = form?.querySelector('button') || null
    await act(async () => { fireEvent(form as HTMLFormElement, new SubmitEvent('submit', { bubbles: true, cancelable: true, submitter })) })

    expect(await screen.findByText('姓名不能为空')).toBeTruthy()
    await waitFor(() => expect((document.querySelector('.workspace-page details') as HTMLDetailsElement).open).toBe(true))
    expect(screen.getByText('请检查表单中的提示并完成修改。')).toBeTruthy()
    const post = calls.find(({ init }) => init?.method === 'POST')
    expect(post?.url.pathname).toBe('/api/v1/workspace/submit/')
    expect(post?.url.searchParams.get('url')).toBe('/members/?household_id=home-1')
    expect(post?.init?.headers).toMatchObject({ 'X-CSRFToken': 'csrf-1' })
    expect(post?.init?.body).toBeInstanceOf(FormData)
    expect((post?.init?.body as FormData).get('display_name')).toBe('小林')
    expect((post?.init?.body as FormData).get('action')).toBe('save')
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
    await waitFor(() => expect(onScopeLoaded).toHaveBeenCalledTimes(2))
    expect(onScopeLoaded).toHaveBeenNthCalledWith(1, { household_id: 'home-1', learner_id: 'learner-a' }, '/members/?household_id=home-1')
    expect(onScopeLoaded).toHaveBeenNthCalledWith(2, { household_id: 'home-1', learner_id: 'learner-a' }, '/members/?household_id=home-1')
  })

  it('preserves typed form and canvas nodes when the loaded scope causes a parent rerender', async () => {
    const page = {
      ...initialPage,
      page: {
        ...initialPage.page,
        html: '<main><label for="draft-note">草稿</label><input id="draft-note" value=""><canvas id="diagram"></canvas></main>',
      },
    }
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      ...page,
      page: { ...page.page, scope: { household_id: 'home-1', learner_id: 'learner-a' } },
    })))
    const noop = () => {}
    function Harness() {
      const [revision, setRevision] = useState(0)
      const handleScopeLoaded = () => setRevision((value) => value + 1)
      return <>
        <button type='button' onClick={() => setRevision((value) => value + 1)}>刷新外层 {revision}</button>
        <WorkspacePage url='/members/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={noop} onScopeLoaded={handleScopeLoaded} onUnauthorized={noop} onUnsavedChange={noop} />
      </>
    }

    const user = userEvent.setup()
    render(<Harness />)
    const input = await screen.findByLabelText('草稿')
    const canvas = document.querySelector('#diagram')
    expect(canvas).not.toBeNull()
    const canvasEvent = vi.fn()
    canvas?.addEventListener('drawn', canvasEvent)
    fireEvent.input(input, { target: { value: '保留的草稿' } })

    await waitFor(() => expect(screen.getByRole('button', { name: '刷新外层 1' })).toBeTruthy())
    await user.click(screen.getByRole('button', { name: '刷新外层 1' }))

    expect(screen.getByLabelText('草稿')).toBe(input)
    expect((screen.getByLabelText('草稿') as HTMLInputElement).value).toBe('保留的草稿')
    expect(document.querySelector('#diagram')).toBe(canvas)
    canvas?.dispatchEvent(new Event('drawn'))
    expect(canvasEvent).toHaveBeenCalledOnce()
  })

  it('rejects a malformed scope without reporting it to the app', async () => {
    const onScopeLoaded = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      return Response.json({ ...initialPage, page: { ...initialPage.page, scope: { household_id: 'home-1', learner_id: null } } })
    }))
    render(<WorkspacePage url='/members/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={vi.fn()} onScopeLoaded={onScopeLoaded} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('页面内容暂时无法显示，请重试。')).toBeTruthy()
    expect(onScopeLoaded).not.toHaveBeenCalled()
  })

  it('ignores a delayed scope response after its requested page is obsolete', async () => {
    let resolveOld: ((response: Response) => void) | undefined
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve })
    const onScopeLoaded = vi.fn()
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const endpoint = new URL(String(input), window.location.origin)
      if (endpoint.searchParams.get('url') === '/old/') return oldResponse
      return Promise.resolve(Response.json({
        ...initialPage,
        page: { ...initialPage.page, url: '/new/', title: '新页面', html: '<main><h1>新页面</h1></main>', scope: { household_id: 'home-1', learner_id: 'learner-b' } },
      }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const noop = () => {}
    const view = render(<WorkspacePage url='/old/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={noop} onScopeLoaded={onScopeLoaded} onUnauthorized={noop} onUnsavedChange={noop} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())

    view.rerender(<WorkspacePage url='/new/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={noop} onScopeLoaded={onScopeLoaded} onUnauthorized={noop} onUnsavedChange={noop} />)
    expect(await screen.findByRole('heading', { name: '新页面' })).toBeTruthy()
    await waitFor(() => expect(onScopeLoaded).toHaveBeenCalledOnce())
    expect(onScopeLoaded).toHaveBeenCalledWith({ household_id: 'home-1', learner_id: 'learner-b' }, '/new/')

    await act(async () => {
      resolveOld?.(Response.json({
        ...initialPage,
        page: { ...initialPage.page, url: '/old/', title: '旧页面', html: '<main><h1>旧页面</h1></main>', scope: { household_id: 'home-1', learner_id: 'learner-a' } },
      }))
      await oldResponse
    })
    expect(screen.queryByRole('heading', { name: '旧页面' })).toBeNull()
    expect(screen.getByRole('heading', { name: '新页面' })).toBeTruthy()
    expect(onScopeLoaded).toHaveBeenCalledOnce()
  })

  it('submits GET filters through in-app navigation and signals expired sessions', async () => {
    const onNavigate = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      schema_version: 'swb.api.v1',
      page: { ...initialPage.page, html: '<main><form method="get" action="/knowledge/"><input type="hidden" name="household_id" value="home-1"><label for="q">搜索</label><input id="q" name="q" value=""><button>筛选</button></form></main>' },
    })))
    const view = render(<WorkspacePage url='/knowledge/?household_id=home-1' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={onNavigate} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    await screen.findByLabelText('搜索')
    fireEvent.input(screen.getByLabelText('搜索'), { target: { value: '分数' } })
    fireEvent.submit(document.querySelector('form') as HTMLFormElement)
    expect(onNavigate).toHaveBeenCalledWith('/knowledge/?household_id=home-1&q=%E5%88%86%E6%95%B0')

    view.unmount()
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', error: { code: 'login_required', message: '登录状态已失效' } }, { status: 401 })))
    const onUnauthorized = vi.fn()
    render(<WorkspacePage url='/knowledge/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={onNavigate} onUnauthorized={onUnauthorized} onUnsavedChange={vi.fn()} />)
    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledOnce())
    expect(await screen.findByText('登录状态已失效，请重新登录后继续。')).toBeTruthy()
  })

  it('accepts an unlinked household scope and never saves GET filter inputs', async () => {
    const calls: Array<{ url: URL; init?: RequestInit }> = []
    const onNavigate = vi.fn()
    const onScopeLoaded = vi.fn()
    const getPage = {
      schema_version: 'swb.api.v1',
      page: {
        ...initialPage.page,
        scope: { household_id: 'home-1', learner_id: '' },
        html: '<main><form method="get" action="/knowledge/"><label for="q">搜索</label><input id="q" name="q"><button>筛选</button></form></main>',
      },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      calls.push({ url, init })
      if (url.pathname.startsWith('/api/v1/drafts/') || url.pathname.startsWith('/api/v1/draft-save/')) return Response.json({ schema_version: 'swb.api.v1', draft: null })
      return Response.json(getPage)
    }))
    render(<WorkspacePage url='/knowledge/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={onNavigate} onScopeLoaded={onScopeLoaded} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    const query = await screen.findByLabelText('搜索')
    fireEvent.input(query, { target: { value: '分数' } })
    fireEvent.submit(document.querySelector('form') as HTMLFormElement)
    expect(onNavigate).toHaveBeenCalledWith('/knowledge/?q=%E5%88%86%E6%95%B0')
    await waitFor(() => expect(onScopeLoaded).toHaveBeenCalledWith({ household_id: 'home-1', learner_id: '' }, '/knowledge/'))
    await new Promise((resolve) => setTimeout(resolve, 750))
    expect(calls.some(({ init }) => init?.method === 'POST')).toBe(false)
  })

  it('restores only current select options and keeps local files out of private draft payloads', async () => {
    const user = userEvent.setup()
    const draftSaves: Array<{ url: URL; body: Record<string, unknown> }> = []
    const candidate = {
      key: 'old-draft', version: 4, base_stamp: 'old', updated_at: '2026-10-05T00:00:00Z',
      payload: {
        forms: [{ index: 0, actionPath: '/members/save/', fields: [
          { name: 'learner_id', label: '学习者', kind: 'select', ordinal: 0, values: ['learner-b', 'deleted-learner'], displayValues: ['小文'] },
          { name: 'unit_id', label: '单元', kind: 'select', ordinal: 0, values: ['deleted-unit'], displayValues: ['旧单元'] },
          { name: 'source_id', label: '来源甲', kind: 'radio', ordinal: 0, values: ['source-a'], displayValues: ['已选择'], checked: true },
          { name: 'source_id', label: '来源乙', kind: 'radio', ordinal: 1, values: ['source-b'], displayValues: ['未选择'], checked: false },
        ] }],
        filesNeedReselection: true,
      },
    }
    const page = {
      schema_version: 'swb.api.v1',
      page: {
        ...initialPage.page,
        scope: { household_id: 'home-1', learner_id: '' },
        html: '<main><details id="more-fields"><summary>展开填写</summary><form method="post" action="/members/save/"><label for="learner">学习者<select id="learner" name="learner_id"><option value="learner-a">小安</option><option value="learner-b">小文</option></select></label><label for="unit">单元<select id="unit" name="unit_id"><option value="unit-current" selected>当前单元</option><option value="unit-next">下一单元</option></select></label><label>来源乙<input type="radio" name="source_id" value="source-b"></label><label>来源甲<input type="radio" name="source_id" value="source-a"></label><label for="display">姓名<input id="display" name="display_name"></label><label for="pass">密码<input id="pass" type="password" name="password" value="private-password"></label><input type="hidden" name="request_key" value="private-request-key"><input name="access_token" value="private-token"><label for="file">附件<input id="file" type="file" name="attachment"></label><button>保存</button></form></details></main>',
      },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.startsWith('/api/v1/drafts/') || url.pathname.startsWith('/api/v1/draft-save/')) {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>
          draftSaves.push({ url, body })
          const saved = JSON.parse(JSON.stringify(body.payload)) as unknown
          return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'draft', version: 5, base_stamp: 'stamp', payload: saved, updated_at: '2026-10-05T00:01:00Z' } })
        }
        return Response.json({ schema_version: 'swb.api.v1', draft: candidate })
      }
      return Response.json(page)
    }))
    render(<WorkspacePage url='/members/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: '发现一份未完成的表单草稿' })).toBeTruthy()
    const recovery = screen.getByRole('region', { name: '私人草稿' })
    expect(recovery.textContent).toContain('学习者：小文')
    expect(recovery.textContent).not.toContain('learner-a')
    expect(recovery.textContent).not.toContain('deleted-learner')
    expect(recovery.textContent).toContain('此前选择的文件需要重新选择')

    await user.click(screen.getByRole('button', { name: '恢复这份草稿' }))
    await waitFor(() => expect((screen.getByLabelText('学习者') as HTMLSelectElement).value).toBe('learner-b'))
    expect((document.querySelector('#more-fields') as HTMLDetailsElement).open).toBe(true)
    expect((screen.getByLabelText('单元') as HTMLSelectElement).value).toBe('unit-current')
    expect((document.querySelector('input[name="source_id"][value="source-a"]') as HTMLInputElement).checked).toBe(true)
    expect((document.querySelector('input[name="source_id"][value="source-b"]') as HTMLInputElement).checked).toBe(false)
    const fileInput = screen.getByLabelText('附件') as HTMLInputElement
    expect(fileInput.files).toHaveLength(0)
    expect(screen.getByRole('status').textContent).toContain('请重新选择')
    await waitFor(() => expect(draftSaves).toHaveLength(1), { timeout: 2000 })
    const payload = draftSaves[0].body.payload as { forms: Array<{ fields: Array<{ name: string }>; }>; filesNeedReselection: boolean }
    expect(payload.filesNeedReselection).toBe(true)
    expect(payload.forms[0].fields.map((field) => field.name)).not.toContain('password')
    expect(payload.forms[0].fields.map((field) => field.name)).not.toContain('request_key')
    expect(payload.forms[0].fields.map((field) => field.name)).not.toContain('access_token')
    const serialized = JSON.stringify(draftSaves[0].body)
    expect(serialized).not.toContain('private-password')
    expect(serialized).not.toContain('private-request-key')
    expect(serialized).not.toContain('private-token')
  })

  it.each([
    { values: [] as string[], expected: [] as string[], label: 'an intentional empty selection' },
    { values: ['removed'], expected: ['a'], label: 'an unavailable saved selection' },
  ])('restores $label without confusing it with the other case', async ({ values, expected }) => {
    const candidate = { key: 'private-draft', version: 2, base_stamp: 'base', updated_at: '2026-10-05T00:00:00Z', payload: {
      forms: [{ index: 0, actionPath: '/members/', fields: [{ name: 'topics', label: '关联知识', kind: 'select-multiple', ordinal: 0, values, displayValues: [] }] }], filesNeedReselection: false,
    } }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const endpoint = new URL(String(input), window.location.origin)
      if (endpoint.pathname.startsWith('/api/v1/drafts/')) return Response.json({ schema_version: 'swb.api.v1', draft: candidate })
      return Response.json({ schema_version: 'swb.api.v1', page: {
        ...initialPage.page, scope: { household_id: 'home-1', learner_id: '' },
        html: '<main><details id="topics-details"><summary>关联设置</summary><form method="post" action="/members/"><label for="topics">关联知识</label><select id="topics" name="topics" multiple><option value="a" selected>原有知识</option><option value="b">另一知识</option></select></form></details></main>',
      } })
    }))
    render(<WorkspacePage url='/members/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    await screen.findByRole('heading', { name: '发现一份未完成的表单草稿' })
    await userEvent.click(screen.getByRole('button', { name: '恢复这份草稿' }))
    const selected = Array.from((screen.getByLabelText('关联知识') as HTMLSelectElement).selectedOptions, (option) => option.value)
    expect(selected).toEqual(expected)
    expect((document.querySelector('#topics-details') as HTMLDetailsElement).open).toBe(values.length === 0)
  })

  it('keeps the current page intact and offers cleanup for an unrecognized private draft', async () => {
    const cleared: Array<Record<string, unknown>> = []
    const page = {
      schema_version: 'swb.api.v1',
      page: {
        ...initialPage.page,
        scope: { household_id: 'home-1', learner_id: '' },
        html: '<main><form method="post"><label for="name">姓名</label><input id="name" name="display_name" value="当前页面"></form></main>',
      },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname.startsWith('/api/v1/drafts/') || url.pathname.startsWith('/api/v1/draft-save/')) {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>
          cleared.push(body)
          return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'draft', version: 2, base_stamp: 'stamp', payload: body.payload, updated_at: '2026-10-05T00:01:00Z' } })
        }
        return Response.json({ schema_version: 'swb.api.v1', draft: { key: 'draft', version: 1, base_stamp: 'stamp', payload: 'broken-payload', updated_at: '2026-10-05T00:00:00Z' } })
      }
      return Response.json(page)
    }))
    render(<WorkspacePage url='/members/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    expect(await screen.findByText('这份私人草稿格式无法识别，当前页面内容没有被替换。')).toBeTruthy()
    expect((screen.getByLabelText('姓名') as HTMLInputElement).value).toBe('当前页面')
    await userEvent.click(screen.getByRole('button', { name: '清理不可恢复草稿' }))
    await waitFor(() => expect(cleared).toHaveLength(1), { timeout: 2000 })
    expect(cleared[0].payload).toEqual({ cleared: true })
  })

  it('reports a failed widget script and retries the page', async () => {
    const user = userEvent.setup()
    const appendChild = HTMLElement.prototype.appendChild
    const appendSpy = vi.spyOn(HTMLElement.prototype, 'appendChild').mockImplementation(function <T extends Node>(this: HTMLElement, node: T): T {
      const appended = appendChild.call(this, node) as T
      if (node instanceof HTMLScriptElement) node.dispatchEvent(new Event('error'))
      return appended
    })
    const fetchMock = vi.fn(async () => Response.json({
      ...initialPage,
      page: { ...initialPage.page, widgets: ['regions'] },
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage url='/materials/page/' householdId='home-1' canWrite csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)

    expect((await screen.findByRole('alert')).textContent).toContain('原图区域框选')
    await user.click(screen.getByRole('button', { name: '重试页面' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('alert').textContent).toContain('页面交互功能加载失败')
    expect(appendSpy).toHaveBeenCalled()
  })

  it('scrolls to an anchor after business page content is mounted', async () => {
    const original = HTMLElement.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
    try {
      vi.stubGlobal('fetch', vi.fn(async () => Response.json({
        schema_version: 'swb.api.v1',
        page: { ...initialPage.page, html: '<main><h1>版本历史</h1><details id="history"><summary>展开历史</summary><section id="revision-7">第七版</section></details></main>' },
      })))
      render(<WorkspacePage url='/learning/attempt/abc/' householdId='home-1' canWrite anchor='#revision-7' csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
      expect(await screen.findByText('第七版')).toBeTruthy()
      await waitFor(() => expect((document.querySelector('#history') as HTMLDetailsElement).open).toBe(true))
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' }))
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: original })
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
    }
  })
  it.each([true, false])('offers definition formula insertion only when a definition field exists: %s', async (hasDefinition) => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...initialPage, page: { ...initialPage.page,
      html: `<main><h1>合成内容表单</h1>${hasDefinition ? '<textarea id="id_definition" name="definition"></textarea>' : ''}<label for="id_display_markup">排版文本</label><textarea id="id_display_markup" name="display_markup"></textarea></main>`,
    } })))
    render(<WorkspacePage url='/synthetic-content/' householdId='home-1' canWrite={false} csrfToken='csrf-1'
      onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    await screen.findByLabelText('排版文本')
    await waitFor(() => expect(screen.queryByLabelText('公式辅助') !== null).toBe(hasDefinition))
  })

})
