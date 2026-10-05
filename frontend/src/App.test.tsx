import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { routeUrl } from './routing/routes'

const about = {
  schema_version: 'swb.api.v1', version: '0.2.0-dev', release_state: 'development',
  source_revision: 'private-revision', build_date: null, changelog: [], help_url: '',
}

const overview = {
  schema_version: 'swb.api.v1',
  scope: { household_id: 'home-b', learner_id: 'learner-b', date_from: null, date_to: null, source_kind: null, metric_version: 'evidence.v1' },
  metrics: { attempt_count: 0, question_count: 0, source_counts: {}, unknown_date_count: 0, independent_success_count: 0, independent_success_rate: null, rate_state: 'not_provided', repeated_error_count: 0, insufficient_evidence_count: 0 },
  findings: { observed_correct_methods: [], insufficient_evidence: [], repeated_errors: [], known_actual_date_intervals: [] },
  links: { profile_url: null, report_url: null, schedule_url: null },
}

const attempts = {
  schema_version: 'swb.api.v1',
  scope: overview.scope,
  items: [], total: 0, page: 1, page_size: 20,
}

const routeLearners = [
  { id: 'learner-a', display_name: '小甲', grade: null, profile_url: '/learning/profile/learner-a/', report_url: '/study/learner/11/report/' },
  { id: 'learner-b', display_name: '小乙', grade: null, profile_url: '/learning/profile/learner-b/', report_url: '/study/learner/22/report/' },
]

const emptyProgress = {
  schema_version: 'swb.api.v1', scope: { household_id: 'home-1', metric_version: 'progress.v1', as_of: '2026-10-05' },
  counts: { material_count: 0, page_count: 0, pages_complete: 0, pages_unread: 0, pages_need_retake: 0, questions_confirmed: 0, questions_pending: 0, open_workflows: 0, completed_workflows: 0 },
  materials: [], total: 0,
}

function installRouteAppApi({
  pageHtml,
  pageScope,
  households = [{ id: 'home-1', name: '甲家庭', role: 'owner' }, { id: 'home-2', name: '乙家庭', role: 'reviewer' }],
  learners = routeLearners,
}: {
  pageHtml: (path: string) => string
  pageScope?: (path: string) => { household_id: string; learner_id: string } | undefined
  households?: Array<{ id: string; name: string; role: string }>
  learners?: typeof routeLearners
}) {
  const requestedPages: string[] = []
  const nativeLearnerRequests: string[] = []
  const learnerHouseholdRequests: string[] = []
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin)
    if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
      schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1', households,
    }))
    if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
    if (url.pathname === '/api/v1/learners/') {
      learnerHouseholdRequests.push(url.searchParams.get('household') || '')
      return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: learners }))
    }
    if (url.pathname === '/api/v1/workspace/page/') {
      const path = url.searchParams.get('url') || ''
      requestedPages.push(path)
      const scope = pageScope?.(path)
      return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: { url: path, title: '业务页面', html: pageHtml(path), widgets: [], ...(scope ? { scope } : {}) } }))
    }
    if (url.pathname.endsWith('/overview/')) return Promise.resolve(Response.json(overview))
    if (url.pathname === '/api/v1/progress/') return Promise.resolve(Response.json({ ...emptyProgress, scope: { ...emptyProgress.scope, household_id: url.searchParams.get('household') || '' } }))
    const learnerProgressMatch = url.pathname.match(/^\/api\/v1\/learners\/([^/]+)\/progress\/$/)
    if (learnerProgressMatch) {
      nativeLearnerRequests.push(learnerProgressMatch[1])
      return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', scope: { household_id: url.searchParams.get('household') || '', learner_id: learnerProgressMatch[1], metric_version: 'progress.v1', as_of: '2026-10-05' }, groups: [] }))
    }
    const scheduleMatch = url.pathname.match(/^\/api\/v1\/learners\/([^/]+)\/schedules\/$/)
    if (scheduleMatch) return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', scope: { household_id: url.searchParams.get('household') || '', learner_id: scheduleMatch[1] }, counts: { pending: 0, overdue: 0, completed: 0, cancelled: 0 }, items: [] }))
    throw new Error(`unexpected request: ${url.pathname}`)
  }))
  return { requestedPages, nativeLearnerRequests, learnerHouseholdRequests }
}

describe('App URL navigation', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    window.history.replaceState({}, '', '/app/')
  })

  it('starts with learning actions and reveals family navigation only when requested', async () => {
    const user = userEvent.setup()
    installRouteAppApi({ pageHtml: () => '<main><h1>业务页面</h1></main>' })
    render(<App />)
    expect(await screen.findByRole('heading', { name: '小甲，今天从哪里开始？' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '选题练习' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '查看讲解' })).toBeTruthy()
    const familyNavigation = screen.getByText('家长协助', { exact: true }).closest('details') as HTMLDetailsElement
    expect(familyNavigation.open).toBe(false)
    expect(familyNavigation.contains(screen.getByRole('button', { name: '资料整理' }))).toBe(true)
    expect((screen.getByText('查看学习记录与待核对项').closest('details') as HTMLDetailsElement).open).toBe(false)
    await user.click(screen.getByText('家长协助', { exact: true }))
    expect(familyNavigation.open).toBe(true)
    expect(screen.getByRole('button', { name: '资料整理' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '学习档案' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '设置' })).toBeTruthy()
  })

  it('keeps a direct URL selection, routes business links, restores popstate, and clears record context on household change', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/app/?view=knowledge&household=home-b&learner=learner-b&screen=%2Fknowledge%2F%3Fhousehold_id%3Dhome-b')
    let resolveLearners!: (response: Response) => void
    const pendingLearners = new Promise<Response>((resolve) => { resolveLearners = resolve })
    const requestedPages: string[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-a', name: '甲家庭', role: 'viewer' }, { id: 'home-b', name: '乙家庭', role: 'owner' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') {
        if (url.searchParams.get('household') === 'home-b') return pendingLearners
        return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [{ id: 'learner-a', display_name: '小甲', grade: null, profile_url: '/learning/', report_url: '/prints/' }] }))
      }
      if (url.pathname === '/api/v1/workspace/page/') {
        const path = url.searchParams.get('url') || ''
        requestedPages.push(path)
        return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
          url: path,
          title: '知识与题库',
          html: path.includes('/entity/')
            ? '<main><h1>知识条目详情</h1></main>'
            : '<main><h1>当前知识页</h1><a href="/knowledge/entity/12/?household_id=home-b">条目详情</a></main>',
          widgets: [],
        } }))
      }
      if (url.pathname.endsWith('/overview/')) return Promise.resolve(Response.json(overview))
      if (url.pathname.endsWith('/attempts/')) return Promise.resolve(Response.json(attempts))
      throw new Error(`unexpected request: ${url.pathname}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    expect(await screen.findByRole('heading', { name: '当前知识页' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-b')
    await act(async () => {
      resolveLearners(Response.json({ schema_version: 'swb.api.v1', items: [
        { id: 'learner-a', display_name: '小甲', grade: null, profile_url: '/learning/', report_url: '/prints/' },
        { id: 'learner-b', display_name: '小乙', grade: null, profile_url: '/learning/', report_url: '/prints/' },
      ] }))
    })
    await waitFor(() => expect(screen.getByRole('combobox', { name: '家庭' })).toBeTruthy())
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-b')

    await user.click(screen.getByRole('link', { name: '条目详情' }))
    expect(await screen.findByRole('heading', { name: '知识条目详情' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('screen')).toBe('/knowledge/entity/12/?household_id=home-b')
    await user.click(screen.getByRole('button', { name: '学习总览' }))
    expect(await screen.findByText('作答来源', { selector: '[data-slot="card-title"]' })).toBeTruthy()
    expect(window.location.search).toContain('learner=learner-b')

    await act(async () => { window.history.back() })
    expect(await screen.findByRole('heading', { name: '知识条目详情' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('view')).toBe('knowledge')

    await user.selectOptions(screen.getByRole('combobox', { name: '家庭' }), 'home-a')
    expect(await screen.findByRole('heading', { name: '当前知识页' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('household')).toBe('home-a')
    expect(new URLSearchParams(window.location.search).get('learner')).toBeNull()
    expect(new URLSearchParams(window.location.search).get('screen')).toBe('/knowledge/?household_id=home-a')
    expect(requestedPages).toContain('/knowledge/?household_id=home-a')
  })

  it('routes business report links under /study/ to the progress view', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/app/?view=knowledge&household=home-1&screen=%2Fknowledge%2F%3Fhousehold_id%3Dhome-1')
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-1', name: '甲家庭', role: 'owner' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [] }))
      if (url.pathname === '/api/v1/workspace/page/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
        url: url.searchParams.get('url'), title: '业务页面',
        html: '<main><h1>知识列表</h1><a href="/study/">学习报告</a></main>', widgets: [],
      } }))
      throw new Error(`unexpected request: ${url.pathname}`)
    }))

    render(<App />)
    expect(await screen.findByRole('heading', { name: '知识列表' })).toBeTruthy()
    await user.click(screen.getByRole('link', { name: '学习报告' }))
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('view')).toBe('progress'))
    expect(new URLSearchParams(window.location.search).get('screen')).toBe('/study/')
  })

  it.each([
    ['omitted', ''],
    ['stale', 'learner-a'],
  ])('maps report links to the learner API identity and restores a %s outer learner', async (_label, outerLearner) => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', routeUrl({
      view: 'progress', household: 'home-1', learner: outerLearner, screen: '/study/learner/22/report/',
    }))
    const { requestedPages } = installRouteAppApi({
      pageHtml: (path) => path === '/study/learner/22/report/'
        ? '<main><h1>小乙学习报告</h1><a href="/study/learner/11/report/">打开小甲报告</a></main>'
        : '<main><h1>小甲学习报告</h1></main>',
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '小乙学习报告' })).toBeTruthy()
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-b'))
    await user.click(screen.getByRole('link', { name: '打开小甲报告' }))
    expect(await screen.findByRole('heading', { name: '小甲学习报告' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a')
    expect(requestedPages).toContain('/study/learner/22/report/')
    expect(requestedPages).toContain('/study/learner/11/report/')
  })

  it('switches from a learner-specific study plan into the selected learner progress workspace', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', routeUrl({
      view: 'progress', household: 'home-1', learner: 'learner-a', screen: '/study/learner/11/schedule/new/',
    }))
    const { requestedPages, nativeLearnerRequests } = installRouteAppApi({
      pageHtml: () => '<main><h1>小甲复测计划</h1></main>',
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '小甲复测计划' })).toBeTruthy()
    await user.selectOptions(screen.getByRole('combobox', { name: '学习者' }), 'learner-b')
    expect(await screen.findByText('当前学习者：小乙')).toBeTruthy()
    await waitFor(() => expect(nativeLearnerRequests).toContain('learner-b'))
    const params = new URLSearchParams(window.location.search)
    expect(params.get('view')).toBe('progress')
    expect(params.get('learner')).toBe('learner-b')
    expect(params.get('screen')).toBeNull()
    expect(requestedPages).toContain('/study/learner/11/schedule/new/')
  })

  it('clears a schedule-detail screen without learner metadata when the learner changes', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', routeUrl({
      view: 'progress', household: 'home-1', learner: 'learner-a', screen: '/study/schedule/21/',
    }))
    const { requestedPages, nativeLearnerRequests } = installRouteAppApi({
      pageHtml: () => '<main><h1>小甲复测详情</h1></main>',
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '小甲复测详情' })).toBeTruthy()
    await user.selectOptions(screen.getByRole('combobox', { name: '学习者' }), 'learner-b')
    expect(await screen.findByText('当前学习者：小乙')).toBeTruthy()
    await waitFor(() => expect(nativeLearnerRequests).toContain('learner-b'))
    const params = new URLSearchParams(window.location.search)
    expect(params.get('view')).toBe('progress')
    expect(params.get('learner')).toBe('learner-b')
    expect(params.get('screen')).toBeNull()
    expect(requestedPages).toEqual(['/study/schedule/21/'])
  })

  it('adopts the learner scope for a linked schedule and still guards a later learner switch', async () => {
    const user = userEvent.setup()
    const confirmMock = vi.fn(() => false)
    vi.stubGlobal('confirm', confirmMock)
    window.history.replaceState({}, '', routeUrl({ view: 'progress', household: 'home-1', learner: 'learner-b', screen: '/study/' }))
    const { requestedPages, nativeLearnerRequests } = installRouteAppApi({
      pageHtml: (path) => path === '/study/'
        ? '<main><h1>家庭复测列表</h1><a href="/study/schedule/21/">打开小甲计划</a></main>'
        : '<main><h1>小甲计划</h1><label for="plan-note">复测备注</label><input id="plan-note" value=""></main>',
      pageScope: (path) => path === '/study/schedule/21/' ? { household_id: 'home-1', learner_id: 'learner-a' } : undefined,
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '家庭复测列表' })).toBeTruthy()
    await user.click(screen.getByRole('link', { name: '打开小甲计划' }))
    expect(await screen.findByRole('heading', { name: '小甲计划' })).toBeTruthy()
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a'))
    expect((screen.getByRole('combobox', { name: '学习者' }) as HTMLSelectElement).value).toBe('learner-a')

    const note = screen.getByLabelText('复测备注')
    fireEvent.input(note, { target: { value: '需要保留的手工备注' } })
    await user.selectOptions(screen.getByRole('combobox', { name: '学习者' }), 'learner-b')
    expect(confirmMock).toHaveBeenCalledOnce()
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a')
    expect(screen.getByLabelText('复测备注')).toBe(note)
    expect((screen.getByLabelText('复测备注') as HTMLInputElement).value).toBe('需要保留的手工备注')

    confirmMock.mockReturnValue(true)
    await user.selectOptions(screen.getByRole('combobox', { name: '学习者' }), 'learner-b')
    expect(await screen.findByText('当前学习者：小乙')).toBeTruthy()
    await waitFor(() => expect(nativeLearnerRequests).toContain('learner-b'))
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-b')
    expect(new URLSearchParams(window.location.search).get('screen')).toBeNull()
    expect(requestedPages).toEqual(['/study/', '/study/schedule/21/'])
  })

  it('restores a direct schedule URL with stale learner context, including after remount', async () => {
    const staleRoute = { view: 'progress' as const, household: 'home-1', learner: 'learner-b', screen: '/study/schedule/21/' }
    const renderDirectRoute = () => {
      window.history.replaceState({}, '', routeUrl(staleRoute))
      return render(<App />)
    }
    const { requestedPages } = installRouteAppApi({
      pageHtml: () => '<main><h1>小甲复测计划</h1></main>',
      pageScope: () => ({ household_id: 'home-1', learner_id: 'learner-a' }),
    })

    const first = renderDirectRoute()
    expect(await screen.findByRole('heading', { name: '小甲复测计划' })).toBeTruthy()
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a'))
    expect((screen.getByRole('combobox', { name: '学习者' }) as HTMLSelectElement).value).toBe('learner-a')

    first.unmount()
    renderDirectRoute()
    expect(await screen.findByRole('heading', { name: '小甲复测计划' })).toBeTruthy()
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a'))
    expect(requestedPages).toEqual(['/study/schedule/21/', '/study/schedule/21/'])
  })

  it('adopts the authorized household as well as learner from a cross-household schedule detail', async () => {
    window.history.replaceState({}, '', routeUrl({ view: 'progress', household: 'home-1', learner: 'learner-b', screen: '/study/schedule/21/' }))
    const { learnerHouseholdRequests } = installRouteAppApi({
      pageHtml: () => '<main><h1>乙家庭复测详情</h1></main>',
      pageScope: () => ({ household_id: 'home-2', learner_id: 'learner-a' }),
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '乙家庭复测详情' })).toBeTruthy()
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('household')).toBe('home-2'))
    await waitFor(() => expect((screen.getByRole('combobox', { name: '学习者' }) as HTMLSelectElement).value).toBe('learner-a'))
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a')
    expect((screen.getByRole('combobox', { name: '家庭' }) as HTMLSelectElement).value).toBe('home-2')
    expect(learnerHouseholdRequests).toContain('home-2')
  })

  it('adopts the learner from an authorized learning-attempt detail without URL identity hints', async () => {
    window.history.replaceState({}, '', routeUrl({ view: 'learning', household: 'home-1', learner: 'learner-b', screen: '/learning/attempt/attempt-9/' }))
    installRouteAppApi({
      pageHtml: () => '<main><h1>历史作答详情</h1></main>',
      pageScope: () => ({ household_id: 'home-1', learner_id: 'learner-a' }),
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '历史作答详情' })).toBeTruthy()
    await waitFor(() => expect((screen.getByRole('combobox', { name: '学习者' }) as HTMLSelectElement).value).toBe('learner-a'))
    const params = new URLSearchParams(window.location.search)
    expect(params.get('view')).toBe('learning')
    expect(params.get('learner')).toBe('learner-a')
    expect(params.get('screen')).toBe('/learning/attempt/attempt-9/')
  })

  it('switches a document learner report to the selected learner equivalent', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', routeUrl({ view: 'documents', household: 'home-1', learner: 'learner-a', screen: '/prints/reports/11/' }))
    const { requestedPages } = installRouteAppApi({
      pageHtml: (path) => path === '/prints/reports/11/'
        ? '<main><h1>小甲打印报告</h1></main>'
        : '<main><h1>小乙打印报告</h1></main>',
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '小甲打印报告' })).toBeTruthy()
    await user.selectOptions(screen.getByRole('combobox', { name: '学习者' }), 'learner-b')
    expect(await screen.findByRole('heading', { name: '小乙打印报告' })).toBeTruthy()
    const params = new URLSearchParams(window.location.search)
    expect(params.get('learner')).toBe('learner-b')
    expect(params.get('screen')).toBe('/prints/reports/22/')
    expect(requestedPages).toContain('/prints/reports/22/')
  })

  it('routes household-scoped operations links and restores the path household over stale outer state', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', routeUrl({ view: 'settings', household: 'home-1', learner: 'learner-a', screen: '/members/?household_id=home-1' }))
    const { requestedPages } = installRouteAppApi({
      pageHtml: (path) => path === '/operations/household/home-2/retention/'
        ? '<main><h1>乙家庭数据保留</h1></main>'
        : '<main><h1>甲家庭设置</h1><a href="/operations/household/home-2/retention/">打开乙家庭数据保留</a></main>',
      learners: [],
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '甲家庭设置' })).toBeTruthy()
    await user.click(screen.getByRole('link', { name: '打开乙家庭数据保留' }))
    expect(await screen.findByRole('heading', { name: '乙家庭数据保留' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('household')).toBe('home-2')
    expect(new URLSearchParams(window.location.search).get('learner')).toBeNull()
    expect(requestedPages).toContain('/operations/household/home-2/retention/')
  })

  it('restores a household-specific operations screen over a stale outer household', async () => {
    window.history.replaceState({}, '', routeUrl({ view: 'settings', household: 'home-1', learner: 'learner-a', screen: '/operations/household/home-2/retention/' }))
    const { requestedPages } = installRouteAppApi({
      pageHtml: () => '<main><h1>乙家庭数据保留</h1></main>',
      learners: [],
    })

    render(<App />)
    expect(await screen.findByRole('heading', { name: '乙家庭数据保留' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('household')).toBe('home-2')
    expect(new URLSearchParams(window.location.search).get('learner')).toBeNull()
    expect(requestedPages).toContain('/operations/household/home-2/retention/')
  })

  it('asks before leaving a form with unsaved edits', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/app/?view=knowledge&household=home-1&screen=%2Fknowledge%2F%3Fhousehold_id%3Dhome-1')
    const confirmMock = vi.fn(() => false)
    vi.stubGlobal('confirm', confirmMock)
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-1', name: '甲家庭', role: 'owner' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [
        { id: 'learner-b', display_name: '小乙', grade: null, profile_url: '/learning/', report_url: '/prints/' },
      ] }))
      if (url.pathname === '/api/v1/workspace/page/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
        url: '/knowledge/?household_id=home-1', title: '知识与题库',
        html: '<main><h1>知识与题库</h1><label for="note">备注</label><input id="note" name="note" value=""></main>', widgets: [],
      } }))
      if (url.pathname.endsWith('/overview/')) return Promise.resolve(Response.json(overview))
      if (url.pathname.endsWith('/attempts/')) return Promise.resolve(Response.json(attempts))
      throw new Error(`unexpected request: ${url.pathname}`)
    }))

    render(<App />)
    expect(await screen.findByLabelText('备注')).toBeTruthy()
    fireEvent.input(screen.getByLabelText('备注'), { target: { value: '待保存' } })
    await user.click(screen.getByRole('button', { name: '学习总览' }))
    expect(confirmMock).toHaveBeenCalledOnce()
    expect(new URLSearchParams(window.location.search).get('view')).toBe('knowledge')

    confirmMock.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: '学习总览' }))
    expect(await screen.findByText('作答来源', { selector: '[data-slot="card-title"]' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('view')).toBe('overview')
  })

  it('follows a successful native POST redirect without asking to discard the submitted form', async () => {
    window.history.replaceState({}, '', '/app/?view=knowledge&household=home-1&screen=%2Fknowledge%2F%3Fhousehold_id%3Dhome-1')
    const confirmMock = vi.fn(() => false)
    vi.stubGlobal('confirm', confirmMock)
    const requestedPages: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-1', name: '甲家庭', role: 'owner' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [] }))
      if (url.pathname === '/api/v1/workspace/page/') {
        const path = url.searchParams.get('url') || ''
        requestedPages.push(path)
        return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
          url: path, title: '知识与题库',
          html: path.includes('saved=1')
            ? '<main><h1>保存后页面</h1></main>'
            : '<main><form method="post" action="/knowledge/save/"><label for="note">备注</label><input id="note" name="note" value=""><button name="action" value="save">保存</button></form></main>',
          widgets: [],
        } }))
      }
      if (url.pathname === '/api/v1/workspace/submit/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', redirect: '/knowledge/?household_id=home-1&saved=1' }))
      throw new Error(`unexpected request: ${url.pathname} ${init?.method || ''}`)
    }))

    render(<App />)
    expect(await screen.findByLabelText('备注')).toBeTruthy()
    fireEvent.input(screen.getByLabelText('备注'), { target: { value: '提交中的备注' } })
    const form = screen.getByLabelText('备注').closest('form')
    expect(form?.isConnected).toBe(true)
    expect(form?.closest('.workspace-page')).toBeTruthy()
    const submitter = form?.querySelector('button') || null
    const nativeSubmit = vi.fn()
    const bubbledSubmit = vi.fn()
    form?.addEventListener('submit', nativeSubmit)
    form?.closest('.workspace-page')?.addEventListener('submit', bubbledSubmit)
    await act(async () => { (form as HTMLFormElement).requestSubmit(submitter as HTMLButtonElement) })

    expect(nativeSubmit).toHaveBeenCalledOnce()
    expect(bubbledSubmit).toHaveBeenCalledOnce()
    expect(confirmMock).not.toHaveBeenCalled()
    expect(requestedPages).toEqual(['/knowledge/?household_id=home-1', '/knowledge/?household_id=home-1&saved=1'])
    expect(await screen.findByRole('heading', { name: '保存后页面' })).toBeTruthy()
    expect(requestedPages).toContain('/knowledge/?household_id=home-1&saved=1')
  })

  it('preserves a direct learning attempt path while selecting the default learner', async () => {
    window.history.replaceState({}, '', '/app/?view=learning&household=home-1&screen=%2Flearning%2Fattempt%2Fattempt-9%2F')
    const requestedPages: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-1', name: '甲家庭', role: 'owner' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [
        { id: 'learner-1', display_name: '小甲', grade: null, profile_url: '/learning/profile/learner-1/', report_url: '/prints/' },
      ] }))
      if (url.pathname === '/api/v1/workspace/page/') {
        requestedPages.push(url.searchParams.get('url') || '')
        return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
          url: '/learning/attempt/attempt-9/', title: '作答详情', html: '<main><h1>指定作答详情</h1></main>', widgets: [],
        } }))
      }
      throw new Error(`unexpected request: ${url.pathname}`)
    }))

    render(<App />)
    expect(await screen.findByRole('heading', { name: '指定作答详情' })).toBeTruthy()
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-1'))
    expect(new URLSearchParams(window.location.search).get('screen')).toBe('/learning/attempt/attempt-9/')
    expect(requestedPages).toEqual(['/learning/attempt/attempt-9/'])
  })

  it('opens the selected learner profile and carries profile-link context into overview', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/app/?view=learning&household=home-1&learner=learner-a&screen=%2Flearning%2F%3Fhousehold%3Dhome-1%26learner%3Dlearner-a')
    const requestedPages: string[] = []
    const requestedOverviewLearners: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-1', name: '甲家庭', role: 'owner' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [
        { id: 'learner-a', display_name: '小甲', grade: null, profile_url: '/learning/profile/learner-a/', report_url: '/prints/' },
        { id: 'learner-b', display_name: '小乙', grade: null, profile_url: '/learning/profile/learner-b/', report_url: '/prints/' },
      ] }))
      if (url.pathname === '/api/v1/workspace/page/') {
        const path = url.searchParams.get('url') || ''
        requestedPages.push(path)
        const isLearnerB = path.startsWith('/learning/profile/learner-b/')
        const isLearnerA = path.startsWith('/learning/profile/learner-a/')
        return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
          url: path,
          title: '学习档案',
          html: isLearnerB
            ? '<main><h1>小乙档案</h1><a href="/learning/profile/learner-a/">打开小甲档案</a></main>'
            : isLearnerA
              ? '<main><h1>小甲档案</h1></main>'
              : '<main><h1>学习档案列表</h1></main>',
          widgets: [],
        } }))
      }
      const overviewMatch = url.pathname.match(/^\/api\/v1\/learners\/([^/]+)\/overview\/$/)
      if (overviewMatch) {
        requestedOverviewLearners.push(overviewMatch[1])
        return Promise.resolve(Response.json({ ...overview, scope: { ...overview.scope, household_id: 'home-1', learner_id: overviewMatch[1] } }))
      }
      throw new Error(`unexpected request: ${url.pathname}`)
    }))

    render(<App />)
    expect(await screen.findByRole('heading', { name: '学习档案列表' })).toBeTruthy()
    await user.selectOptions(screen.getByRole('combobox', { name: '学习者' }), 'learner-b')
    expect(await screen.findByRole('heading', { name: '小乙档案' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-b')
    expect(new URLSearchParams(window.location.search).get('screen')).toBe('/learning/profile/learner-b/')

    await user.click(screen.getByRole('link', { name: '打开小甲档案' }))
    expect(await screen.findByRole('heading', { name: '小甲档案' })).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get('learner')).toBe('learner-a')
    expect(new URLSearchParams(window.location.search).get('screen')).toBe('/learning/profile/learner-a/')

    await user.click(screen.getByRole('button', { name: '学习总览' }))
    expect(await screen.findByText('作答来源', { selector: '[data-slot="card-title"]' })).toBeTruthy()
    expect(requestedOverviewLearners).toEqual(['learner-a'])
    expect(requestedPages).toContain('/learning/profile/learner-b/')
    expect(requestedPages).toContain('/learning/profile/learner-a/')
  })

  it('leaves expired-session login links to normal browser navigation', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      schema_version: 'swb.api.v1', error: { code: 'login_required', message: '请先登录' },
    }, { status: 401 })))
    render(<App />)
    const loginLink = await screen.findByRole('link', { name: '前往登录' })
    expect(loginLink.getAttribute('href')).toBe('/accounts/login/?next=/app/')
    let preventedBeforeNativeNavigation = false
    const preventNavigationForTest = (event: Event) => {
      preventedBeforeNativeNavigation = event.defaultPrevented
      event.preventDefault()
    }
    document.addEventListener('click', preventNavigationForTest)
    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    loginLink.dispatchEvent(click)
    document.removeEventListener('click', preventNavigationForTest)
    expect(preventedBeforeNativeNavigation).toBe(false)
  })

  it('keeps framework anchors in the app, previews images and PDFs, and validates household links', async () => {
    const user = userEvent.setup()
    const original = HTMLElement.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
    window.history.replaceState({}, '', '/app/?view=knowledge&household=home-1&screen=%2Fknowledge%2F%3Fhousehold_id%3Dhome-1')
    const requestedPages: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/v1/session/') return Promise.resolve(Response.json({
        schema_version: 'swb.api.v1', user: { username: 'parent' }, csrf_token: 'csrf-1',
        households: [{ id: 'home-1', name: '甲家庭', role: 'owner' }, { id: 'home-2', name: '乙家庭', role: 'reviewer' }],
      }))
      if (url.pathname === '/api/v1/about/') return Promise.resolve(Response.json(about))
      if (url.pathname === '/api/v1/learners/') return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', items: [] }))
      if (url.pathname === '/api/v1/workspace/page/') {
        const path = url.searchParams.get('url') || ''
        requestedPages.push(path)
        const anchoredPage = path.includes('/entity/')
        return Promise.resolve(Response.json({ schema_version: 'swb.api.v1', page: {
          url: path,
          title: '知识与题库',
          html: anchoredPage
            ? '<main><h1>锚点详情</h1><section id="revision-9">第九版</section><a href="/prints/snapshots/12/document.pdf/?token=check">PDF 文档</a><a href="/page/123e4567-e89b-12d3-a456-426614174000/preview/90/">原图</a><a href="/knowledge/?household_id=home-2">切换家庭</a><a href="/knowledge/?household_id=unknown">无效家庭</a></main>'
            : path.includes('household_id=home-2')
              ? '<main><h1>知识列表</h1><a href="/knowledge/?household_id=unknown">无效家庭</a></main>'
              : '<main><h1>知识列表</h1><a href="#revision-current">本页版本</a><section id="revision-current">当前版</section><a href="/knowledge/entity/12/?household_id=home-1#revision-9">跨页版本</a></main>',
          widgets: [],
        } }))
      }
      throw new Error(`unexpected request: ${url.pathname}`)
    }))

    try {
      render(<App />)
      expect(await screen.findByRole('heading', { name: '知识列表' })).toBeTruthy()
      const samePageAnchor = screen.getByRole('link', { name: '本页版本' })
      fireEvent.click(samePageAnchor)
      await waitFor(() => expect(new URLSearchParams(window.location.search).get('screen')).toBe('/knowledge/?household_id=home-1#revision-current'))
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' }))
      expect(new URLSearchParams(window.location.search).get('screen')).toBe('/knowledge/?household_id=home-1#revision-current')
      expect(requestedPages).toEqual(['/knowledge/?household_id=home-1'])

      await user.click(screen.getByRole('link', { name: '跨页版本' }))
      expect(await screen.findByRole('heading', { name: '锚点详情' })).toBeTruthy()
      await waitFor(() => expect(scrollIntoView.mock.calls.length).toBeGreaterThan(1))
      expect(new URLSearchParams(window.location.search).get('screen')).toBe('/knowledge/entity/12/?household_id=home-1#revision-9')
      expect(requestedPages).toContain('/knowledge/entity/12/?household_id=home-1')

      await user.click(screen.getByRole('link', { name: 'PDF 文档' }))
      expect(screen.getByRole('dialog', { name: 'document.pdf' })).toBeTruthy()
      expect(screen.getByTitle('document.pdf').tagName).toBe('IFRAME')
      expect(screen.getByTitle('document.pdf').getAttribute('src')).toBe('/prints/snapshots/12/document.pdf/?token=check&preview=1')
      await user.click(screen.getByRole('button', { name: '关闭预览' }))
      await user.click(screen.getByRole('link', { name: '原图' }))
      expect(screen.getByRole('dialog', { name: '原图预览' })).toBeTruthy()
      expect(screen.getByRole('img', { name: '原图预览' }).getAttribute('src')).toBe('/page/123e4567-e89b-12d3-a456-426614174000/preview/90/')
      await user.click(screen.getByRole('button', { name: '关闭预览' }))

      await user.click(screen.getByRole('link', { name: '切换家庭' }))
      await waitFor(() => expect(new URLSearchParams(window.location.search).get('household')).toBe('home-2'))
      expect(new URLSearchParams(window.location.search).get('learner')).toBeNull()
      await user.click(screen.getByRole('link', { name: '无效家庭' }))
      expect(new URLSearchParams(window.location.search).get('household')).toBe('home-2')
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: original })
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
    }
  })
})
