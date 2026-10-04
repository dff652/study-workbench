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
            html: '<main><h1>家庭成员</h1><p role="alert">姓名不能为空</p><form method="post"><label for="display-name">姓名</label><input id="display-name" name="display_name" value=""><button name="action" value="save">保存</button></form></main>',
          },
        }, { status: 400 })
      }
      return Response.json({ ...initialPage, page: { ...initialPage.page, scope: { household_id: 'home-1', learner_id: 'learner-a' } } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage url='/members/?household_id=home-1' csrfToken='csrf-1' onNavigate={vi.fn()} onScopeLoaded={onScopeLoaded} onUnauthorized={vi.fn()} onUnsavedChange={onUnsavedChange} />)

    expect(await screen.findByRole('heading', { name: '家庭成员', level: 1 })).toBeTruthy()
    const nameInput = screen.getByLabelText('姓名')
    fireEvent.input(nameInput, { target: { value: '小林' } })
    expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
    const form = document.querySelector('form')
    expect(form).not.toBeNull()
    const submitter = form?.querySelector('button') || null
    await act(async () => { fireEvent(form as HTMLFormElement, new SubmitEvent('submit', { bubbles: true, cancelable: true, submitter })) })

    expect(await screen.findByText('姓名不能为空')).toBeTruthy()
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
        <WorkspacePage url='/members/' csrfToken='csrf-1' onNavigate={noop} onScopeLoaded={handleScopeLoaded} onUnauthorized={noop} onUnsavedChange={noop} />
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
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      ...initialPage,
      page: { ...initialPage.page, scope: { household_id: 'home-1', learner_id: ' ' } },
    })))
    render(<WorkspacePage url='/members/' csrfToken='csrf-1' onNavigate={vi.fn()} onScopeLoaded={onScopeLoaded} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)

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
    const view = render(<WorkspacePage url='/old/' csrfToken='csrf-1' onNavigate={noop} onScopeLoaded={onScopeLoaded} onUnauthorized={noop} onUnsavedChange={noop} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())

    view.rerender(<WorkspacePage url='/new/' csrfToken='csrf-1' onNavigate={noop} onScopeLoaded={onScopeLoaded} onUnauthorized={noop} onUnsavedChange={noop} />)
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
    const view = render(<WorkspacePage url='/knowledge/?household_id=home-1' csrfToken='csrf-1' onNavigate={onNavigate} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
    await screen.findByLabelText('搜索')
    fireEvent.input(screen.getByLabelText('搜索'), { target: { value: '分数' } })
    fireEvent.submit(document.querySelector('form') as HTMLFormElement)
    expect(onNavigate).toHaveBeenCalledWith('/knowledge/?household_id=home-1&q=%E5%88%86%E6%95%B0')

    view.unmount()
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ schema_version: 'swb.api.v1', error: { code: 'login_required', message: '登录状态已失效' } }, { status: 401 })))
    const onUnauthorized = vi.fn()
    render(<WorkspacePage url='/knowledge/' csrfToken='csrf-1' onNavigate={onNavigate} onUnauthorized={onUnauthorized} onUnsavedChange={vi.fn()} />)
    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledOnce())
    expect(await screen.findByText('登录状态已失效，请重新登录后继续。')).toBeTruthy()
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
    render(<WorkspacePage url='/materials/page/' csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)

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
        page: { ...initialPage.page, html: '<main><h1>版本历史</h1><section id="revision-7">第七版</section></main>' },
      })))
      render(<WorkspacePage url='/learning/attempt/abc/' anchor='#revision-7' csrfToken='csrf-1' onNavigate={vi.fn()} onUnauthorized={vi.fn()} onUnsavedChange={vi.fn()} />)
      expect(await screen.findByText('第七版')).toBeTruthy()
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' }))
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: original })
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
    }
  })
})
