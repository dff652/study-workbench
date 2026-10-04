import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BookOpenCheck,
  CalendarClock,
  FileText,
  GraduationCap,
  House,
  Layers3,
  Settings,
  ShieldCheck,
  Users,
} from 'lucide-react'
import { api, ApiError } from './api'
import { AboutPanel } from './components/about-panel'
import { NavButton } from './components/nav-button'
import { EmptyState, isUnauthorized, type Remote } from './components/shared'
import { Main } from './components/layout/main'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { EvidenceWorkspace } from './features/evidence/workspace'
import { MaterialWorkspace } from './features/materials/workspace'
import { ProgressWorkspace } from './features/progress/workspace'
import { WorkspacePage } from './features/workspace/page'
import { SolutionWorkspace } from './features/solutions/workspace'
import { SolutionsLauncher } from './features/solutions/launcher'
import { fragmentOfPath, householdIdForBusinessPath, isFilePath, learnerIdForBusinessPath, parseRoute, previewKindForPath, printReportPathForLearner, routeForBusinessPath, routeUrl, safeBusinessPath, screenForView, solutionMaterialId, solutionScreen, withoutFragment, type AppRoute, type View } from './routing/routes'
import type { WorkspacePageScope } from './features/workspace/page-api'
import type { AboutResponse, LearnersResponse, SessionResponse } from './types'

const PRIMARY_NAV = [
  { view: 'overview', label: '学习总览', icon: Layers3 },
  { view: 'materials', label: '资料整理', icon: House },
  { view: 'knowledge', label: '知识与题库', icon: BookOpenCheck },
  { view: 'learning', label: '学习档案', icon: GraduationCap },
  { view: 'progress', label: '进度与复测', icon: CalendarClock },
  { view: 'documents', label: '文档中心', icon: FileText },
  { view: 'settings', label: '设置', icon: Settings },
] as const

const PAGE_TITLES: Record<View, string> = {
  overview: '学习总览',
  materials: '资料整理',
  knowledge: '知识与题库',
  learning: '学习档案',
  attempts: '学习档案',
  progress: '进度与复测',
  documents: '文档中心',
  settings: '设置',
}

export default function App() {
  const [session, setSession] = useState<Remote<SessionResponse>>({ status: 'loading' })
  const [about, setAbout] = useState<Remote<AboutResponse>>({ status: 'loading' })
  const [learners, setLearners] = useState<Remote<LearnersResponse>>({ status: 'loading' })
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location))
  const [sessionRetry, setSessionRetry] = useState(0)
  const [aboutRetry, setAboutRetry] = useState(0)
  const [learnersRetry, setLearnersRetry] = useState(0)
  const [unauthorized, setUnauthorized] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [filePreview, setFilePreview] = useState<{ kind: 'image' | 'pdf'; src: string; title: string } | null>(null)
  const routeRef = useRef(route)
  const sessionRef = useRef(session)
  const unsavedRef = useRef(hasUnsavedChanges)
  const learnersHouseholdRef = useRef('')
  routeRef.current = route
  sessionRef.current = session
  unsavedRef.current = hasUnsavedChanges

  const replaceRoute = useCallback((nextRoute: AppRoute) => {
    const safeRoute = { ...nextRoute, screen: nextRoute.screen ? nextRoute.screen : '' }
    const nextUrl = routeUrl(safeRoute)
    if (window.location.pathname + window.location.search !== nextUrl) window.history.replaceState({}, '', nextUrl)
    routeRef.current = safeRoute
    setRoute(safeRoute)
  }, [])

  const navigateRoute = useCallback((nextRoute: AppRoute, replace = false) => {
    if (unsavedRef.current && !window.confirm('页面有未保存的更改。确定离开当前页面吗？')) return
    const nextUrl = routeUrl(nextRoute)
    if (routeUrl(routeRef.current) === nextUrl) return
    if (replace) window.history.replaceState({}, '', nextUrl)
    else window.history.pushState({}, '', nextUrl)
    routeRef.current = nextRoute
    setRoute(nextRoute)
    setHasUnsavedChanges(false)
  }, [])

  const navigateBusinessPath = useCallback((path: string) => {
    if (session.status !== 'loaded') return
    const learnerRoutes = learners.status === 'loaded' && learnersHouseholdRef.current === routeRef.current.household
      ? learners.data.items
      : []
    const nextRoute = routeForBusinessPath(path, routeRef.current, routeRef.current.learner, learnerRoutes)
    if (!nextRoute) return
    const target = new URL(path, window.location.origin)
    const householdWasSpecified = target.searchParams.has('household') || target.searchParams.has('household_id')
      || householdIdForBusinessPath(`${target.pathname}${target.search}`) !== null
    if (householdWasSpecified && !session.data.households.some((item) => item.id === nextRoute.household)) return
    navigateRoute(nextRoute)
  }, [learners, navigateRoute, session])
  const navigateBusinessPathRef = useRef(navigateBusinessPath)
  navigateBusinessPathRef.current = navigateBusinessPath
  const stableNavigateBusinessPath = useCallback((path: string) => navigateBusinessPathRef.current(path), [])

  const handleGlobalClick = useCallback((event: globalThis.MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = event.target
    if (!(target instanceof Element)) return
    const anchor = target.closest('a[href]')
    if (!(anchor instanceof HTMLAnchorElement) || anchor.hasAttribute('download')) return
    const href = anchor.getAttribute('href') || ''
    if (!href) return
    let targetUrl: URL
    try {
      const currentBusinessUrl = routeRef.current.screen
        ? new URL(routeRef.current.screen, window.location.origin)
        : null
      targetUrl = new URL(href, href.startsWith('#') && currentBusinessUrl ? currentBusinessUrl : window.location.href)
    } catch {
      return
    }
    if (targetUrl.origin !== window.location.origin || !['http:', 'https:'].includes(targetUrl.protocol)) return
    if (targetUrl.pathname === '/accounts' || targetUrl.pathname.startsWith('/accounts/')) return
    const previewKind = previewKindForPath(targetUrl.pathname)
    if (previewKind) {
      event.preventDefault()
      const previewUrl = new URL(`${targetUrl.pathname}${targetUrl.search}`, window.location.origin)
      if (targetUrl.pathname.startsWith('/prints/snapshots/')) previewUrl.searchParams.set('preview', '1')
      setFilePreview({
        kind: previewKind,
        src: `${previewUrl.pathname}${previewUrl.search}`,
        title: previewTitle(targetUrl.pathname, previewKind),
      })
      return
    }
    if (targetUrl.hash && routeRef.current.screen) {
      const currentBusinessUrl = new URL(routeRef.current.screen, window.location.origin)
      if (currentBusinessUrl.pathname === targetUrl.pathname && currentBusinessUrl.search === targetUrl.search) {
        event.preventDefault()
        navigateRoute({ ...routeRef.current, screen: `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}` })
        return
      }
    }
    if (isFilePath(targetUrl.pathname)) {
      if (!anchor.target) {
        anchor.target = '_blank'
        anchor.rel = 'noreferrer'
      }
      return
    }
    event.preventDefault()
    navigateBusinessPath(`${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`)
  }, [navigateBusinessPath, navigateRoute])

  const globalClickHandlerRef = useRef(handleGlobalClick)
  globalClickHandlerRef.current = handleGlobalClick

  useEffect(() => {
    const handleDocumentClick = (event: globalThis.MouseEvent) => globalClickHandlerRef.current(event)
    document.addEventListener('click', handleDocumentClick)
    return () => document.removeEventListener('click', handleDocumentClick)
  }, [])

  useEffect(() => {
    if (!filePreview) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFilePreview(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [filePreview])

  const handleUnauthorized = useCallback(() => setUnauthorized(true), [])
  const handleUnsavedChange = useCallback((changed: boolean) => {
    unsavedRef.current = changed
    setHasUnsavedChanges(changed)
  }, [])
  const handleWorkspaceScope = useCallback((scope: WorkspacePageScope, requestedUrl: string) => {
    const current = routeRef.current
    const activeSession = sessionRef.current
    if (activeSession.status !== 'loaded' || !scope.household_id || !scope.learner_id
      || withoutFragment(current.screen) !== withoutFragment(requestedUrl)
      || !activeSession.data.households.some((item) => item.id === scope.household_id)) return
    if (current.household === scope.household_id && current.learner === scope.learner_id) return
    replaceRoute({ ...current, household: scope.household_id, learner: scope.learner_id })
  }, [replaceRoute])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setSession({ status: 'loading' })
    setUnauthorized(false)
    api.session(controller.signal).then((data) => {
      if (!active) return
      setSession({ status: 'loaded', data })
      const current = routeRef.current
      const household = current.household && data.households.some((item) => item.id === current.household)
        ? current.household
        : data.households[0]?.id || ''
      const urlParams = new URLSearchParams(window.location.search)
      if (household !== current.household) {
        replaceRoute({ ...current, household, learner: '', screen: screenForView(current.view, household) })
      } else if (householdIdForBusinessPath(current.screen)
        && (urlParams.get('household') || urlParams.get('household_id')) !== current.household) {
        replaceRoute(current)
      }
    }).catch((error: unknown) => {
      if (!active) return
      setSession({ status: 'error', message: messageFor(error) })
      if (isUnauthorized(error)) setUnauthorized(true)
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [sessionRetry, replaceRoute])

  useEffect(() => {
    if (session.status !== 'loaded') return
    const controller = new AbortController()
    let active = true
    setAbout({ status: 'loading' })
    api.about(controller.signal).then((data) => {
      if (active) setAbout({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      setAbout({ status: 'error', message: messageFor(error) })
      if (isUnauthorized(error)) handleUnauthorized()
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [session.status, aboutRetry, handleUnauthorized])

  const householdId = route.household
  useEffect(() => {
    if (session.status !== 'loaded' || !householdId) {
      learnersHouseholdRef.current = ''
      setLearners({ status: 'loaded', data: { schema_version: 'swb.api.v1', items: [] } })
      return
    }
    const controller = new AbortController()
    let active = true
    setLearners({ status: 'loading' })
    api.learners(householdId, controller.signal).then((data) => {
      if (!active) return
      learnersHouseholdRef.current = householdId
      setLearners({ status: 'loaded', data })
    }).catch((error: unknown) => {
      if (!active) return
      setLearners({ status: 'error', message: messageFor(error) })
      if (isUnauthorized(error)) handleUnauthorized()
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [session.status, householdId, learnersRetry, handleUnauthorized])

  useEffect(() => {
    if (session.status !== 'loaded' || learners.status !== 'loaded' || !householdId
      || learnersHouseholdRef.current !== householdId || hasUnsavedChanges || route.household !== householdId) return
    const screenLearner = route.screen ? learnerIdForBusinessPath(route.screen, learners.data.items) : null
    if (screenLearner) {
      if (route.learner !== screenLearner) replaceRoute({ ...route, learner: screenLearner })
      return
    }
    if (route.learner && learners.data.items.some((item) => item.id === route.learner)) return
    const learner = viewNeedsLearner(route.view) ? learners.data.items[0]?.id || '' : ''
    const isLearningLanding = route.view === 'learning' && (!route.screen || businessPathname(route.screen) === '/learning/')
    const screen = isLearningLanding ? screenForView(route.view, householdId, learner) : route.screen
    if (route.learner !== learner || route.screen !== screen) replaceRoute({ ...route, learner, screen })
  }, [session.status, learners, householdId, hasUnsavedChanges, route, replaceRoute])

  useEffect(() => {
    if (session.status !== 'loaded' || !householdId || route.screen) return
    const screen = screenForView(route.view, householdId, route.learner)
    if (screen) replaceRoute({ ...route, screen })
  }, [session.status, householdId, route, replaceRoute])

  useEffect(() => {
    const onPopState = () => {
      const nextRoute = parseRoute(window.location)
      if (unsavedRef.current && !window.confirm('页面有未保存的更改。确定离开当前页面吗？')) {
        window.history.pushState({}, '', routeUrl(routeRef.current))
        return
      }
      routeRef.current = nextRoute
      setRoute(nextRoute)
      setHasUnsavedChanges(false)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!unsavedRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [])

  if (unauthorized) return <LoginRequired onRetry={() => setSessionRetry((count) => count + 1)} />
  if (session.status === 'loading') {
    return <div className='flex min-h-svh items-center justify-center bg-muted/40 p-5'><p role='status'>正在连接学习工作台…</p></div>
  }
  if (session.status === 'error') {
    return (
      <div className='flex min-h-svh items-center justify-center bg-muted/40 p-5'>
        <Card className='w-full max-w-lg'>
          <CardHeader><CardTitle>连接学习工作台失败</CardTitle><CardDescription>{session.message}</CardDescription></CardHeader>
          <CardContent><Button type='button' onClick={() => setSessionRetry((count) => count + 1)}>重试连接</Button></CardContent>
        </Card>
      </div>
    )
  }

  const households = session.data.households
  const selectedHousehold = households.find((item) => item.id === householdId)
  const learner = learners.status === 'loaded'
    ? learners.data.items.find((item) => item.id === route.learner)
    : undefined
  const title = PAGE_TITLES[route.view]
  const effectiveScreen = route.screen || screenForView(route.view, householdId, route.learner)
  const workspaceUrl = withoutFragment(effectiveScreen)
  const workspaceAnchor = fragmentOfPath(effectiveScreen)
  const solutionId = route.view === 'documents' ? solutionMaterialId(route.screen) : null
  const isSolutionScreen = solutionId !== null
  const isDocumentsLanding = route.view === 'documents' && effectiveScreen.startsWith('/prints/') && !isSolutionScreen
  const isBusinessScreen = Boolean(effectiveScreen) && (route.view === 'knowledge' || route.view === 'learning'
    || route.view === 'documents' || route.view === 'settings' || Boolean(route.screen))
  const needsLearner = route.view === 'overview' || route.view === 'attempts' || route.view === 'progress'
    || route.view === 'learning' || route.view === 'documents'
  const needsNativeLearner = needsLearner && !isBusinessScreen

  const selectHousehold = (nextId: string) => {
    navigateRoute({
      ...route,
      household: nextId,
      learner: '',
      screen: screenForView(route.view, nextId),
    })
  }

  const selectLearner = (nextId: string) => {
    if (learners.status !== 'loaded' || learnersHouseholdRef.current !== householdId) return
    const selectedLearner = learners.data.items.find((item) => item.id === nextId)
    if (!selectedLearner) return
    if (route.view === 'learning') {
      const profilePath = safeBusinessPath(selectedLearner.profile_url)
      if (!profilePath) return
      const profileRoute = routeForBusinessPath(profilePath, { ...route, learner: nextId }, nextId)
      if (!profileRoute || profileRoute.household !== householdId || profileRoute.learner !== nextId) return
      navigateRoute(profileRoute)
      return
    }
    let screen = route.screen
    const screenLearner = learnerIdForBusinessPath(screen, learners.data.items)
    if (nextId !== route.learner) {
      if (route.view === 'progress' && screen) screen = screenForView('progress', householdId, nextId)
      if (route.view === 'documents' && screenLearner && screenLearner !== nextId) screen = printReportPathForLearner(selectedLearner.report_url)
        || screenForView('documents', householdId)
    }
    navigateRoute({ ...route, learner: nextId, screen })
  }

  const selectView = (view: View) => {
    const learnerId = route.learner || (viewNeedsLearner(view) && learners.status === 'loaded' ? learners.data.items[0]?.id || '' : '')
    navigateRoute({ ...route, view, learner: learnerId, screen: screenForView(view, householdId, learnerId) })
  }

  const selectSettingsScreen = (path: string) => {
    navigateRoute({ ...route, view: 'settings', screen: path })
  }

  const settingsLinks = householdId ? [
    { label: '家庭成员', path: `/members/?household_id=${encodeURIComponent(householdId)}`, icon: Users },
    { label: '模型与费用', path: `/ai/config/${encodeURIComponent(householdId)}/`, icon: ShieldCheck },
    { label: '数据保留', path: `/operations/household/${encodeURIComponent(householdId)}/retention/`, icon: FileText },
    { label: '使用帮助', path: '/help/', icon: FileText },
  ] : []

  return (
    <div className='min-h-svh bg-muted/30 text-foreground'>
      <a href='#content' className='fixed left-4 top-2 z-[100] -translate-y-16 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:translate-y-0'>跳到主要内容</a>
      <div className='min-h-svh lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]'>
        <aside className='border-b bg-sidebar text-sidebar-foreground lg:sticky lg:top-0 lg:h-svh lg:border-b-0 lg:border-r'>
          <div className='flex items-center gap-3 px-5 py-5'>
            <div className='flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground'><GraduationCap className='size-5' aria-hidden='true' /></div>
            <div>
              <p className='font-semibold leading-tight'>学习工作台</p>
              <p className='mt-1 text-xs text-muted-foreground'>家庭学习与资料整理</p>
            </div>
          </div>
          <nav aria-label='主导航' className='flex gap-2 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible'>
            {PRIMARY_NAV.map(({ view, label, icon }) => (
              <NavButton key={view} active={route.view === view || (view === 'learning' && route.view === 'attempts')} icon={icon} onClick={() => selectView(view)}>{label}</NavButton>
            ))}
          </nav>
          {householdId ? <section className='mx-3 mb-4 rounded-lg border border-sidebar-border px-3 py-3'>
            <h2 className='mb-2 text-xs font-semibold tracking-wide text-muted-foreground'>当前家庭</h2>
            <p className='truncate text-sm font-medium'>{selectedHousehold?.name || '正在读取家庭…'}</p>
          </section> : null}
        </aside>

        <div className='min-w-0'>
          <header className='sticky top-0 z-30 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75'>
            <div className='flex min-h-16 items-center justify-between gap-4 px-4 py-3 sm:px-6 xl:px-8'>
              <div className='min-w-0'>
                <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>{title}</p>
                <p className='truncate text-sm font-semibold'>{selectedHousehold?.name || '家庭学习工作台'}</p>
              </div>
              <div className='flex shrink-0 items-center gap-2'>
                <details className='relative'>
                  <summary className='cursor-pointer list-none rounded-md border px-3 py-2 text-xs font-medium hover:bg-muted'>
                    {about.status === 'loaded' ? `关于 · v${about.data.version}` : '关于'}
                  </summary>
                  <div className='absolute right-0 top-full z-50 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-lg border bg-popover p-3 text-popover-foreground shadow-lg'>
                    <AboutPanel about={about} onRetry={() => setAboutRetry((count) => count + 1)} />
                  </div>
                </details>
                <details className='relative'>
                  <summary className='cursor-pointer list-none rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted'>{session.data.user.username}</summary>
                  <div className='absolute right-0 top-full z-50 mt-2 w-56 rounded-lg border bg-popover p-3 text-popover-foreground shadow-lg'>
                    <p className='truncate text-sm font-medium'>{session.data.user.username}</p>
                    <p className='mt-1 text-xs text-muted-foreground'>{selectedHousehold ? roleLabel(selectedHousehold.role) : '家庭身份未确认'}</p>
                    <form method='post' action='/accounts/logout/' className='mt-3 border-t pt-3'>
                      <input type='hidden' name='csrfmiddlewaretoken' value={session.data.csrf_token} />
                      <Button type='submit' variant='outline' size='sm' className='w-full'>退出账号</Button>
                    </form>
                  </div>
                </details>
              </div>
            </div>
          </header>

          <Main id='content' fluid className='space-y-6 px-4 py-6 sm:px-6 xl:px-8'>
            {!isBusinessScreen ? <div className='flex flex-wrap items-end justify-between gap-4'>
              <div>
                <h1 className='text-2xl font-semibold tracking-tight sm:text-3xl'>{title}</h1>
                <p className='mt-2 max-w-2xl text-sm leading-6 text-muted-foreground'>{descriptionFor(route.view)}</p>
              </div>
            </div> : null}

            {households.length === 0 ? (
              <EmptyState title='当前账号没有可访问的家庭' detail='请使用有权限的账号登录，或联系家庭所有者调整访问权限。' icon={House} />
            ) : <Card className='shadow-sm'>
              <CardContent className='grid gap-4 p-4 sm:grid-cols-[minmax(14rem,0.8fr)_minmax(14rem,1fr)] sm:items-end sm:p-5'>
                <div>
                  <p id='household-label' className='mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground'><House className='size-3.5' aria-hidden='true' />家庭</p>
                  {households.length === 1 ? (
                    <div className='flex h-10 items-center rounded-md border bg-muted/40 px-3 text-sm font-medium'>{households[0].name}</div>
                  ) : (
                    <select aria-labelledby='household-label' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={householdId} onChange={(event) => selectHousehold(event.target.value)}>
                      {households.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  )}
                </div>
                {needsLearner ? <div>
                  <p id='learner-label' className='mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground'><GraduationCap className='size-3.5' aria-hidden='true' />学习者</p>
                  {learners.status === 'loading' ? <div className='flex h-10 items-center rounded-md border bg-muted/20 px-3 text-sm text-muted-foreground'>读取学习者…</div> : null}
                  {learners.status === 'error' ? <div className='flex h-10 items-center justify-between rounded-md border border-amber-300 bg-amber-50 px-3 text-xs text-amber-900'><span>读取失败</span><button type='button' className='underline' onClick={() => setLearnersRetry((count) => count + 1)}>重试</button></div> : null}
                  {learners.status === 'loaded' && learners.data.items.length > 0 ? (
                    <select aria-labelledby='learner-label' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={route.learner} onChange={(event) => selectLearner(event.target.value)}>
                      {learners.data.items.map((item) => <option key={item.id} value={item.id}>{item.display_name}{item.grade ? ` · ${item.grade}` : ''}</option>)}
                    </select>
                  ) : null}
                  {learners.status === 'loaded' && learners.data.items.length === 0 ? <div className='flex h-10 items-center rounded-md border border-dashed px-3 text-sm text-muted-foreground'>暂无学习者记录</div> : null}
                </div> : <div className='rounded-lg bg-primary/[0.04] px-4 py-3'>
                  <p className='text-xs text-muted-foreground'>当前家庭</p>
                  <p className='mt-1 truncate font-semibold'>{selectedHousehold?.name || '未选择'}</p>
                </div>}
              </CardContent>
            </Card>}

            {route.view === 'settings' && settingsLinks.length > 0 ? (
              <nav aria-label='设置导航' className='flex flex-wrap gap-2'>
                {settingsLinks.map(({ label, path, icon: Icon }) => {
                  const active = route.screen === path || route.screen.startsWith(path.split('?')[0])
                  return <Button key={path} type='button' variant={active ? 'secondary' : 'outline'} size='sm' aria-current={active ? 'page' : undefined} onClick={() => selectSettingsScreen(path)}><Icon className='size-4' aria-hidden='true' />{label}</Button>
                })}
              </nav>
            ) : null}

            {households.length > 0 && isBusinessScreen && effectiveScreen ? (
              isDocumentsLanding ? <SolutionsLauncher householdId={householdId} onUnauthorized={handleUnauthorized} onOpen={(materialId) => navigateRoute({ ...route, view: 'documents', screen: solutionScreen(materialId) })} onMaterials={() => selectView('materials')} /> : null
            ) : null}
            {households.length > 0 && isSolutionScreen && solutionId ? <SolutionWorkspace
              key={`${householdId}:${solutionId}`}
              materialId={solutionId}
              csrfToken={session.data.csrf_token}
              canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
              onUnauthorized={handleUnauthorized}
              onUnsavedChange={handleUnsavedChange}
              onBack={() => navigateRoute({ ...route, screen: screenForView('documents', householdId, route.learner) })}
            /> : null}
            {households.length > 0 && isBusinessScreen && effectiveScreen && !isSolutionScreen ? (
              <WorkspacePage
                key={workspaceUrl}
                url={workspaceUrl}
                anchor={workspaceAnchor}
                csrfToken={session.data.csrf_token}
                onNavigate={stableNavigateBusinessPath}
                onScopeLoaded={handleWorkspaceScope}
                onUnauthorized={handleUnauthorized}
                onUnsavedChange={handleUnsavedChange}
              />
            ) : null}
            {households.length > 0 && !isBusinessScreen && route.view === 'materials' ? (
              <MaterialWorkspace
                key={householdId}
                householdId={householdId}
                householdName={selectedHousehold?.name || ''}
                csrfToken={session.data.csrf_token}
                canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                learners={learners.status === 'loaded' ? learners.data.items : []}
                selectedLearnerId={route.learner}
                onUnauthorized={handleUnauthorized}
                onOpenSolutions={(materialId) => navigateRoute({ ...route, view: 'documents', screen: solutionScreen(materialId) })}
              />
            ) : null}
            {households.length > 0 && needsNativeLearner && learners.status === 'error' ? (
              <Card className='border-amber-300/70 bg-amber-50/70'><CardContent className='flex flex-wrap items-center justify-between gap-3 p-5'><p className='text-sm'>{learners.message}</p><Button type='button' variant='outline' onClick={() => setLearnersRetry((count) => count + 1)}>重试</Button></CardContent></Card>
            ) : null}
            {households.length > 0 && needsNativeLearner && learners.status === 'loaded' && learners.data.items.length === 0 ? (
              <EmptyState title='这个家庭还没有学习者' detail='添加学习者后，这里会显示真实的作答和证据记录。' icon={GraduationCap} />
            ) : null}
            {households.length > 0 && needsNativeLearner && learner ? (
              route.view === 'progress' ? (
                <ProgressWorkspace
                  key={`${householdId}:${learner.id}`}
                  householdId={householdId}
                  learner={learner}
                  csrfToken={session.data.csrf_token}
                  canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                  onUnauthorized={handleUnauthorized}
                />
              ) : (
                <EvidenceWorkspace key={`${householdId}:${learner.id}`} householdId={householdId} learner={learner} activePage={route.view === 'attempts' ? 'attempts' : 'overview'} onUnauthorized={handleUnauthorized} />
              )
            ) : null}
          </Main>
        </div>
      </div>
      {filePreview ? (
        <div className='fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-3 sm:p-6' role='dialog' aria-modal='true' aria-label={filePreview.title} onMouseDown={(event) => { if (event.target === event.currentTarget) setFilePreview(null) }}>
          <section className='flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-background shadow-2xl'>
            <header className='flex items-center justify-between gap-3 border-b px-4 py-3'>
              <h2 className='truncate text-sm font-semibold'>{filePreview.title}</h2>
              <Button type='button' variant='outline' size='sm' aria-label='关闭预览' onClick={() => setFilePreview(null)}>关闭</Button>
            </header>
            {filePreview.kind === 'image' ? (
              <div className='flex min-h-0 flex-1 items-center justify-center overflow-auto bg-black/5 p-2 sm:p-4'><img src={filePreview.src} alt={filePreview.title} className='max-h-[calc(100vh-7rem)] max-w-full object-contain' /></div>
            ) : (
              <iframe title={filePreview.title} src={filePreview.src} className='min-h-[60vh] flex-1 border-0 sm:min-h-[75vh]' />
            )}
          </section>
        </div>
      ) : null}
    </div>
  )
}

function LoginRequired({ onRetry }: { onRetry: () => void }) {
  return (
    <div className='flex min-h-svh items-center justify-center bg-muted/40 p-5'>
      <Card className='w-full max-w-lg'>
        <CardHeader>
          <div className='flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground'><House className='size-6' aria-hidden='true' /></div>
          <CardTitle className='mt-2 text-xl'>请先登录学习工作台</CardTitle>
          <CardDescription>登录后可查看所属家庭的学习记录和原图证据。</CardDescription>
        </CardHeader>
        <CardContent className='space-y-4'>
          <Button asChild><a href='/accounts/login/?next=/app/'>前往登录</a></Button>
          <button type='button' className='ml-3 text-sm text-primary underline-offset-4 hover:underline' onClick={onRetry}>重试连接</button>
        </CardContent>
      </Card>
    </div>
  )
}

function messageFor(error: unknown) {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : '连接暂时不可用，请重试。'
}

function businessPathname(value: string) {
  try { return new URL(value, window.location.origin).pathname } catch { return '' }
}

function previewTitle(pathname: string, kind: 'image' | 'pdf') {
  const filename = pathname.split('/').filter(Boolean).at(-1) || ''
  if (kind === 'image' && /\/preview\/\d+\/$/.test(pathname)) return '原图预览'
  if (kind === 'image' && /\/derivative\/[^/]+\/?$/.test(pathname)) return '派生图预览'
  if (kind === 'image' && /\/png\/?$/.test(pathname)) return '教学图预览'
  return filename.includes('.') ? decodeURIComponent(filename) : kind === 'pdf' ? 'PDF 预览' : '图片预览'
}

function descriptionFor(view: View) {
  switch (view) {
    case 'materials': return '整理家庭资料、核对题面与原图，并检查整理结果。'
    case 'overview': return '查看真实作答记录、来源和仍待核实的学习证据。'
    case 'attempts':
    case 'learning': return '查看逐次作答、来源、评价和订正历史。未知与未测状态会明确保留。'
    case 'progress': return '查看资料整理进展、已记录的学习证据和复测计划。'
    case 'knowledge': return '整理知识点、方法、题型和题目之间的来源关联。'
    case 'documents': return '生成、检查和下载家庭学习资料。'
    case 'settings': return '管理家庭成员、模型服务和数据保留设置。'
  }
}

function roleLabel(role: string) {
  if (role === 'owner') return '家庭所有者'
  if (role === 'reviewer') return '可整理和复核'
  if (role === 'viewer') return '只读成员'
  return '家庭身份未确认'
}

function viewNeedsLearner(view: View) {
  return view === 'materials' || view === 'overview' || view === 'attempts' || view === 'learning'
    || view === 'progress' || view === 'documents'
}
