import { readPresentationMode, savePresentationMode, type PresentationMode } from './lib/presentation-mode'
import { PdfPreview } from './components/pdf-preview'
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
import { api, getErrorMessage } from './api'
import { AboutPanel } from './components/about-panel'
import { LearningStart } from './components/learning-start'
import { LearningTasks } from './components/learning-tasks'
import { WorkspacePanel, WorkspaceTabs } from './components/workspace-tabs'
import { NavButton } from './components/nav-button'
import { EmptyState, isUnauthorized, type Remote } from './components/shared'
import { Main } from './components/layout/main'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { EvidenceWorkspace } from './features/evidence/workspace'
import { MaterialWorkspace } from './features/materials/workspace'
import { MaterialProcessing } from './features/materials/processing'
import { ProgressWorkspace } from './features/progress/workspace'
import { WorkspacePage } from './features/workspace/page'
import { SolutionWorkspace } from './features/solutions/workspace'
import { DocumentCatalogue } from './features/solutions/catalogue'
import { SolutionsLauncher } from './features/solutions/launcher'
import { KnowledgeWorkspace } from './features/knowledge/workspace'
import { fragmentOfPath, householdIdForBusinessPath, isFilePath, knowledgeMaterialId, knowledgeScreen, learnerIdForBusinessPath, parseRoute, previewKindForPath, printReportPathForLearner, routeForBusinessPath, routeUrl, safeBusinessPath, screenForView, solutionMaterialId, solutionScreen, withoutFragment, type AppRoute, type View } from './routing/routes'
import type { WorkspacePageScope } from './features/workspace/page-api'
import type { AboutResponse, LearnersResponse, SessionResponse } from './types'

const PRIMARY_NAV = [
  { view: 'overview', label: '学习总览', icon: Layers3 },
  { view: 'materials', label: '资料整理', icon: House },
  { view: 'knowledge', label: '知识与题库', icon: BookOpenCheck },
  { view: 'learning', label: '学习档案', icon: GraduationCap },
  { view: 'progress', label: '进度与复测', icon: CalendarClock },
  { view: 'documents', label: '文档中心', icon: FileText },
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
  const [presentation, setPresentation] = useState<PresentationMode>('student')
  const [sessionRetry, setSessionRetry] = useState(0)
  const [aboutRetry, setAboutRetry] = useState(0)
  const [learnersRetry, setLearnersRetry] = useState(0)
  const [unauthorized, setUnauthorized] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const previewDialogRef = useRef<HTMLDivElement>(null)
  const [filePreview, setFilePreview] = useState<{ kind: 'image' | 'pdf'; src: string; title: string; previews?: string[] } | null>(null)
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
    const contextual = new URL(path, window.location.origin)
    if (/^\/knowledge\/question\//.test(contextual.pathname) && routeRef.current.learner) contextual.searchParams.set('learner', routeRef.current.learner)
    const nextRoute = routeForBusinessPath(`${contextual.pathname}${contextual.search}${contextual.hash}`, routeRef.current, routeRef.current.learner, learnerRoutes)
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
    if (!(anchor instanceof HTMLAnchorElement) || anchor.hasAttribute('download') || anchor.target === '_blank') return
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
        title: anchor.dataset.previewTitle || previewTitle(targetUrl.pathname, previewKind),
        previews: previewPages(anchor.dataset.previewPages),
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
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = previewDialogRef.current
    const main = document.getElementById('workbench-shell')
    main?.setAttribute('inert', '')
    const focusables = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]') || []).filter((item) => !item.closest('[hidden]'))
    focusables()[0]?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setFilePreview(null) }
      if (event.key === 'Tab') {
        const items = focusables(), first = items[0], last = items[items.length - 1]
        if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first?.focus() }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => { main?.removeAttribute('inert'); window.removeEventListener('keydown', onKeyDown); if (trigger?.isConnected) trigger.focus() }
  }, [filePreview])

  const handleUnauthorized = useCallback(() => setUnauthorized(true), [])
  const handleUnsavedChange = useCallback((changed: boolean) => {
    unsavedRef.current = changed
    setHasUnsavedChanges(changed)
  }, [])
  const handleWorkspaceTab = useCallback((tab: string) => {
    replaceRoute({ ...routeRef.current, tab })
  }, [replaceRoute])
  const handleMaterialLocation = useCallback((location: { materialId: string; query: string; page: number; subject?: string }) => {
    const current = routeRef.current
    if (current.view !== 'materials' || current.screen) return
    const next = { ...current, materialId: location.materialId, materialQuery: location.query, materialPage: location.page, materialSubject: location.subject ?? current.materialSubject ?? '' }
    if (current.materialId && location.materialId && location.materialId !== current.materialId) window.history.pushState({}, '', routeUrl(next))
    replaceRoute(next)
  }, [replaceRoute])
  const handleWorkspaceScope = useCallback((scope: WorkspacePageScope, requestedUrl: string) => {
    const current = routeRef.current
    const activeSession = sessionRef.current
    if (activeSession.status !== 'loaded' || !scope.household_id
      || withoutFragment(current.screen) !== withoutFragment(requestedUrl)
      || !activeSession.data.households.some((item) => item.id === scope.household_id)) return
    const learnerId = scope.learner_id || (current.household === scope.household_id ? current.learner : '')
    if (current.household === scope.household_id && current.learner === learnerId) return
    replaceRoute({ ...current, household: scope.household_id, learner: learnerId })
  }, [replaceRoute])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setSession({ status: 'loading' })
    setUnauthorized(false)
    api.session(controller.signal).then((data) => {
      if (!active) return
      setSession({ status: 'loaded', data })
      setPresentation(readPresentationMode(data.user.username))
      const current = routeRef.current
      const household = current.household && data.households.some((item) => item.id === current.household)
        ? current.household
        : data.households[0]?.id || ''
      const urlParams = new URLSearchParams(window.location.search)
      if (household !== current.household) {
        replaceRoute({ ...current, household, learner: '', screen: screenForView(current.view, household), materialId: undefined, materialQuery: undefined, materialPage: undefined })
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
    // A child workspace may have just recorded its material or tab in this commit.
    const current = routeRef.current
    if (session.status !== 'loaded' || learners.status !== 'loaded' || !householdId
      || learnersHouseholdRef.current !== householdId || unsavedRef.current || current.household !== householdId) return
    const screenLearner = current.screen ? learnerIdForBusinessPath(current.screen, learners.data.items) : null
    if (screenLearner) {
      if (current.learner !== screenLearner) replaceRoute({ ...current, learner: screenLearner })
      return
    }
    if (current.learner && learners.data.items.some((item) => item.id === current.learner)) return
    const learner = viewNeedsLearner(current.view) ? learners.data.items[0]?.id || '' : ''
    const isLearningLanding = current.view === 'learning' && (!current.screen || businessPathname(current.screen) === '/learning/')
    const screen = isLearningLanding ? screenForView(current.view, householdId, learner) : current.screen
    if (current.learner !== learner || current.screen !== screen) replaceRoute({ ...current, learner, screen })
  }, [session.status, learners, householdId, hasUnsavedChanges, route, replaceRoute])

  useEffect(() => {
    const current = routeRef.current
    if (session.status !== 'loaded' || !householdId || current.household !== householdId || current.screen) return
    const screen = current.view === 'knowledge' ? `/knowledge/?household_id=${encodeURIComponent(householdId)}&mode=${presentation === 'student' ? 'learn' : 'manage'}` : screenForView(current.view, householdId, current.learner)
    if (screen) replaceRoute({ ...current, screen })
  }, [session.status, householdId, route, replaceRoute, presentation])

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
  const knowledgeId = ['knowledge', 'documents'].includes(route.view) ? knowledgeMaterialId(route.screen) : null
  const isKnowledgeScreen = knowledgeId !== null
  const isKnowledgeLauncher = route.view === 'knowledge' && new URL(effectiveScreen || '/', window.location.origin).pathname === '/__app__/knowledge-explanations/'
  const isKnowledgeIndex = route.view === 'knowledge' && new URL(effectiveScreen || '/', window.location.origin).pathname === '/knowledge/'
  const isDocumentsLanding = route.view === 'documents' && new URL(effectiveScreen || '/', window.location.origin).pathname === '/prints/' && !isSolutionScreen
  const documentsTab = route.tab === 'practice' ? 'practice' : route.tab === 'knowledge' ? 'knowledge' : route.tab === 'solutions' ? 'solutions' : 'recent'
  const isBusinessScreen = Boolean(effectiveScreen) && (route.view === 'knowledge' || route.view === 'learning'
    || route.view === 'documents' || route.view === 'settings' || Boolean(route.screen))
  const needsLearner = viewNeedsLearner(route.view)
  const hasLearnerWorkspace = route.view === 'overview' || route.view === 'attempts'
    || route.view === 'learning' || route.view === 'progress'
  const needsNativeLearner = hasLearnerWorkspace && !isBusinessScreen

  const selectHousehold = (nextId: string) => {
    navigateRoute({
      ...route,
      household: nextId,
      learner: '',
      screen: route.view === 'knowledge' ? `/knowledge/?household_id=${encodeURIComponent(nextId)}&mode=${presentation === 'student' ? 'learn' : 'manage'}` : screenForView(route.view, nextId),
      materialId: undefined,
      materialQuery: undefined,
      materialPage: undefined,
      materialSubject: undefined,
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
    if (route.view === 'knowledge' && /^\/knowledge\/question\//.test(screen)) {
      const questionPath = new URL(screen, window.location.origin)
      questionPath.searchParams.set('learner', nextId)
      screen = `${questionPath.pathname}${questionPath.search}${questionPath.hash}`
    }
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
    navigateRoute({ ...route, view, learner: learnerId, screen: view === 'knowledge' ? `/knowledge/?household_id=${encodeURIComponent(householdId)}&mode=${presentation === 'student' ? 'learn' : 'manage'}` : screenForView(view, householdId, learnerId), tab: '', materialId: undefined, materialQuery: undefined, materialPage: undefined })
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
      <div id='workbench-shell' className='min-h-svh lg:grid lg:grid-cols-[13rem_minmax(0,1fr)]'>
        <aside className='flex flex-col border-b bg-sidebar text-sidebar-foreground lg:sticky lg:top-0 lg:h-svh lg:border-b-0 lg:border-r'>
          <div className='flex min-h-14 items-center gap-2 px-4 py-3'>
            <div className='flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground'><GraduationCap className='size-4' aria-hidden='true' /></div>
            <p className='font-semibold leading-tight'>学习工作台</p>
          </div>
          <nav aria-label='主导航' className='flex flex-wrap gap-1 px-3 pb-3 lg:flex-1 lg:flex-col lg:flex-nowrap'>
            {PRIMARY_NAV.map(({ view, label, icon }) => (
              <NavButton key={view} active={route.view === view || (view === 'learning' && route.view === 'attempts')} icon={icon} onClick={() => selectView(view)}>{label}</NavButton>
            ))}
            <div className='lg:mt-auto lg:border-t lg:pt-3'><NavButton active={route.view === 'settings'} icon={Settings} onClick={() => selectView('settings')}>设置</NavButton></div>
          </nav>
        </aside>

        <div className='min-w-0'>
          <header className='sticky top-0 z-30 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75'>
            <div className='flex min-h-14 flex-wrap items-center justify-between gap-2 px-4 py-2 sm:px-6'>
              <div className='flex min-w-0 flex-wrap items-center gap-2 sm:gap-4'>
                {households.length > 1 ? <label className='flex min-w-0 items-center gap-2 text-sm'>
                  <span className='text-muted-foreground'>家庭</span>
                  <select aria-label='家庭' className='h-9 max-w-[12rem] rounded-md border bg-background px-2 text-sm' value={householdId} onChange={(event) => selectHousehold(event.target.value)}>{households.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
                </label> : <p className='max-w-[18rem] truncate text-sm font-medium' title={selectedHousehold?.name}>{selectedHousehold?.name || '家庭学习工作台'}</p>}
                {householdId && needsLearner ? <div className='flex min-w-0 items-center gap-2 text-sm'>
                  <span className='text-muted-foreground'>学习者</span>
                  {learners.status === 'loading' ? <span role='status' className='text-muted-foreground'>读取中…</span> : null}
                  {learners.status === 'error' ? <span role='alert' className='flex items-center gap-2 text-destructive'>读取失败<button type='button' className='underline' onClick={() => setLearnersRetry((count) => count + 1)}>重试</button></span> : null}
                  {learners.status === 'loaded' && learners.data.items.length === 1 ? <span className='max-w-[12rem] truncate font-medium' title={learner?.display_name}>{learner?.display_name || '尚未选择'}</span> : null}
                  {learners.status === 'loaded' && learners.data.items.length > 1 ? <select aria-label='学习者' className='h-9 max-w-[12rem] rounded-md border bg-background px-2 text-sm' value={route.learner} onChange={(event) => selectLearner(event.target.value)}>{learners.data.items.map((item) => <option key={item.id} value={item.id}>{item.display_name}{item.grade ? ` · ${item.grade}` : ''}</option>)}</select> : null}
                  {learners.status === 'loaded' && learners.data.items.length === 0 ? <span className='text-muted-foreground'>暂无记录</span> : null}
                </div> : null}
              </div>
              <div className='flex shrink-0 flex-wrap items-center gap-2'>
                <div role='group' aria-label='使用方式' className='flex rounded-md border p-1'>{([{ value: 'student', label: '学生练习' }, { value: 'parent', label: '家长跟进' }] as const).map((mode) => <Button key={mode.value} type='button' size='sm' variant={presentation === mode.value ? 'secondary' : 'ghost'} aria-pressed={presentation === mode.value} onClick={() => { setPresentation(mode.value); savePresentationMode(session.data.user.username, mode.value); if (isKnowledgeIndex) navigateRoute({ ...route, screen: `/knowledge/?household_id=${encodeURIComponent(householdId)}&mode=${mode.value === 'student' ? 'learn' : 'manage'}` }) }}>{mode.label}</Button>)}</div>
                <details className='relative'>
                  <summary className='cursor-pointer list-none rounded-md border px-3 py-2 text-xs font-medium hover:bg-muted'>
                    关于
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

          <Main id='content' className={`min-w-0 space-y-6 px-4 py-6 sm:px-6 ${route.view === 'settings' ? 'max-w-4xl' : route.view === 'materials' || route.view === 'knowledge' ? 'max-w-[90rem]' : 'max-w-7xl'}`}>
            {!isBusinessScreen || (isDocumentsLanding && documentsTab !== 'practice') || isSolutionScreen || isKnowledgeScreen || isKnowledgeLauncher ? <h1 className='text-xl font-semibold tracking-tight'>{isSolutionScreen ? '逐题讲解' : isKnowledgeScreen || isKnowledgeLauncher ? '知识点讲解' : title}</h1> : null}

            {households.length === 0 ? (
              <EmptyState title='当前账号没有可访问的家庭' detail='请使用有权限的账号登录，或联系家庭所有者调整访问权限。' icon={House} />
            ) : null}

            {households.length > 0 && route.view === 'overview' && !isBusinessScreen ? <LearningTasks key={`tasks:${householdId}:${learner?.id || ''}`} householdId={householdId} learnerId={learner?.id || ''} studentMode={presentation === 'student'} onUnauthorized={handleUnauthorized} /> : null}
            {households.length > 0 && route.view === 'overview' && !isBusinessScreen ? <LearningStart
              parentMode={presentation === 'parent'}
              learnerName={learner?.display_name || ''}
              canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
              onPractice={() => navigateBusinessPath(`/knowledge/?household_id=${encodeURIComponent(householdId)}&mode=learn#question-index`)}
              onExplanation={() => selectView('documents')}
              onReview={() => selectView('progress')}
              onMaterials={() => selectView('materials')}
              onRecord={() => learner && navigateBusinessPath(`/learning/profile/${encodeURIComponent(learner.id)}/attempt/new/`)}
              onHistory={() => selectView('learning')}
            /> : null}


            {route.view === 'settings' && settingsLinks.length > 0 ? (
              <nav aria-label='设置导航' className='flex flex-wrap gap-2'>
                {settingsLinks.map(({ label, path, icon: Icon }) => {
                  const active = route.screen === path || route.screen.startsWith(path.split('?')[0])
                  return <Button key={path} type='button' variant={active ? 'secondary' : 'outline'} size='sm' aria-current={active ? 'page' : undefined} onClick={() => selectSettingsScreen(path)}><Icon className='size-4' aria-hidden='true' />{label}</Button>
                })}
              </nav>
            ) : null}
            {households.length > 0 && isDocumentsLanding ? <WorkspaceTabs
              id='document-center'
              label='文档分类'
              tabs={[{ value: 'recent', label: '最近成果' }, { value: 'knowledge', label: '知识点讲解' }, { value: 'solutions', label: '家长解析' }, { value: 'practice', label: '练习与整套五册' }]}
              value={documentsTab}
              onChange={handleWorkspaceTab}
            /> : null}

            {households.length > 0 && isDocumentsLanding ? <WorkspacePanel id='document-center' value='recent' active={documentsTab}><DocumentCatalogue key={`catalogue:${householdId}`} householdId={householdId} onUnauthorized={handleUnauthorized} /></WorkspacePanel> : null}
            {households.length > 0 && isBusinessScreen && effectiveScreen ? (
              isDocumentsLanding ? <WorkspacePanel id='document-center' value='solutions' active={documentsTab}><SolutionsLauncher
                key={householdId}
                householdId={householdId}
                onUnauthorized={handleUnauthorized}
                onOpen={(materialId, hasOutputs) => navigateRoute({ ...route, view: 'documents', screen: `${solutionScreen(materialId)}?panel=${hasOutputs ? 'outputs' : 'editor'}` })}
                onPrepareDocuments={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'
                  ? (materialId) => navigateBusinessPath(`/prints/materials/${encodeURIComponent(materialId)}/five-books/`)
                  : undefined}
                onMaterials={() => selectView('materials')}
              /></WorkspacePanel> : null
            ) : null}
            {households.length > 0 && isKnowledgeIndex ? <details open={presentation === 'parent'} className='border-b pb-3'><summary className='cursor-pointer text-sm font-medium'>家长整理工具</summary><div className='mt-3 flex flex-wrap items-center gap-3'><Button type='button' size='sm' variant='outline' onClick={() => navigateRoute({ ...route, screen: '/__app__/knowledge-explanations/', tab: undefined })}>整理知识点讲解</Button><p className='text-sm text-muted-foreground'>按资料编写完整结论、条件与依据，再生成知识讲解文档。</p></div></details> : null}
            {households.length > 0 && (isKnowledgeLauncher || isDocumentsLanding) ? <WorkspacePanel id='document-center' value='knowledge' active={isKnowledgeLauncher ? 'knowledge' : documentsTab}><SolutionsLauncher
              key={`${householdId}:knowledge`}
              mode='knowledge'
              householdId={householdId}
              onUnauthorized={handleUnauthorized}
              onOpen={(materialId, hasOutputs) => navigateRoute({ ...route, screen: knowledgeScreen(materialId), tab: hasOutputs ? 'outputs' : 'editor' })}
              onMaterials={() => selectView('materials')}
            /></WorkspacePanel> : null}
            {households.length > 0 && isSolutionScreen && solutionId ? <SolutionWorkspace
              key={`${householdId}:${solutionId}`}
              materialId={solutionId}
              householdId={householdId}
              initialPanel={new URL(effectiveScreen, window.location.origin).searchParams.get('panel') === 'outputs' ? 'outputs' : 'editor'}
              initialTab={route.tab || undefined}
              onTabChange={handleWorkspaceTab}
              csrfToken={session.data.csrf_token}
              canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
              onUnauthorized={handleUnauthorized}
              onUnsavedChange={handleUnsavedChange}
              onScopeLoaded={handleWorkspaceScope}
              onBack={() => navigateRoute({ ...route, screen: screenForView('documents', householdId, route.learner) })}
            /> : null}
            {households.length > 0 && isKnowledgeScreen && knowledgeId ? <KnowledgeWorkspace
              key={`${householdId}:knowledge:${knowledgeId}`}
              materialId={knowledgeId}
              householdId={householdId}
              initialPanel={new URL(effectiveScreen, window.location.origin).searchParams.get('panel') === 'outputs' ? 'outputs' : 'editor'}
              initialTab={route.tab || undefined}
              onTabChange={handleWorkspaceTab}
              csrfToken={session.data.csrf_token}
              canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
              onUnauthorized={handleUnauthorized}
              onUnsavedChange={handleUnsavedChange}
              onScopeLoaded={handleWorkspaceScope}
              onBack={() => navigateRoute({ ...route, screen: route.view === 'documents' ? screenForView('documents', householdId) : '/__app__/knowledge-explanations/', tab: route.view === 'documents' ? 'knowledge' : undefined })}
            /> : null}
            {households.length > 0 && isBusinessScreen && effectiveScreen && !isSolutionScreen && !isKnowledgeScreen && !isKnowledgeLauncher ? (
              <DocumentPracticePanel landing={isDocumentsLanding} active={documentsTab}><WorkspacePage
                key={workspaceUrl}
                url={workspaceUrl}
                householdId={householdId}
                canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                anchor={workspaceAnchor}
                csrfToken={session.data.csrf_token}
                onNavigate={stableNavigateBusinessPath}
                onScopeLoaded={handleWorkspaceScope}
                onUnauthorized={handleUnauthorized}
                onUnsavedChange={handleUnsavedChange}
                initialTab={route.tab || ''}
                onTabChange={handleWorkspaceTab}
              /></DocumentPracticePanel>
            ) : null}
            {households.length > 0 && !isBusinessScreen && route.view === 'materials' ? (
              route.tab === 'processing' ? <MaterialProcessing householdId={householdId} onUnauthorized={handleUnauthorized} onReturn={() => navigateRoute({ ...routeRef.current, tab: 'pages' })} /> : <MaterialWorkspace
                key={householdId}
                householdId={householdId}
                householdName={selectedHousehold?.name || ''}
                onUnsavedChange={handleUnsavedChange}
                csrfToken={session.data.csrf_token}
                canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                learners={learners.status === 'loaded' ? learners.data.items : []}
                selectedLearnerId={route.learner}
                onUnauthorized={handleUnauthorized}
                onOpenSolutions={(materialId) => navigateBusinessPath(solutionScreen(materialId))}
                initialTab={route.tab || 'pages'}
                onProcessingProgress={() => navigateRoute({ ...routeRef.current, tab: 'processing' })}
                onTabChange={handleWorkspaceTab}
                initialMaterialId={route.materialId || ''}
                initialQuery={route.materialQuery || ''}
                initialPage={route.materialPage || 1}
                initialSubject={route.materialSubject || ''}
                onLocationChange={handleMaterialLocation}
              />
            ) : null}
            {households.length > 0 && needsNativeLearner && learners.status === 'error' ? (
              <Card className='border-amber-300/70 bg-amber-50/70'><CardContent className='flex flex-wrap items-center justify-between gap-3 p-5'><p className='text-sm'>{learners.message}</p><Button type='button' variant='outline' onClick={() => setLearnersRetry((count) => count + 1)}>重试</Button></CardContent></Card>
            ) : null}
            {households.length > 0 && needsNativeLearner && learners.status === 'loaded' && learners.data.items.length === 0 ? (
              <div className='space-y-3'><EmptyState title='这个家庭还没有学习者' detail='添加学习者后，这里会显示真实的作答和证据记录。资料整理可以独立进行。' icon={GraduationCap} />{selectedHousehold?.role !== 'viewer' ? <Button type='button' onClick={() => navigateBusinessPath(`/learning/profile/new/?household=${encodeURIComponent(householdId)}`)}>添加首位学习者</Button> : <p className='text-sm text-muted-foreground'>请家庭所有者或审核成员添加学习档案。</p>}</div>
            ) : null}
            {households.length > 0 && needsNativeLearner && hasLearnerWorkspace && learner ? (
              route.view === 'progress' ? (
                <ProgressWorkspace
                  key={`progress:${householdId}:${learner.id}`}
                  householdId={householdId}
                  learner={learner}
                  csrfToken={session.data.csrf_token}
                  canWrite={selectedHousehold?.role === 'owner' || selectedHousehold?.role === 'reviewer'}
                  onUnauthorized={handleUnauthorized}
                  onUnsavedChange={handleUnsavedChange}
                  initialTab={route.tab || 'plans'}
                  onTabChange={handleWorkspaceTab}
                />
              ) : (
                <EvidenceWorkspace key={`evidence:${householdId}:${learner.id}`} householdId={householdId} learner={learner} activePage={route.view === 'attempts' ? 'attempts' : 'overview'} initialTab={route.tab || undefined} onTabChange={handleWorkspaceTab} initialFilters={route.evidenceFilters} onFiltersChange={(evidenceFilters) => navigateRoute({ ...routeRef.current, evidenceFilters })} onUnauthorized={handleUnauthorized} />
              )
            ) : null}
          </Main>
        </div>
      </div>
      {filePreview ? (
        <div ref={previewDialogRef} className='fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-3 sm:p-6' role='dialog' aria-modal='true' aria-label={filePreview.title} onMouseDown={(event) => { if (event.target === event.currentTarget) setFilePreview(null) }}>
          <section className='flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-background shadow-2xl'>
            <header className='flex items-center justify-between gap-3 border-b px-4 py-3'>
              <h2 className='truncate text-sm font-semibold'>{filePreview.title}</h2>
              <Button type='button' variant='outline' size='sm' aria-label='关闭预览' onClick={() => setFilePreview(null)}>关闭</Button>
            </header>
            {filePreview.kind === 'image' ? (
              <div className='flex min-h-0 flex-1 items-center justify-center overflow-auto bg-black/5 p-2 sm:p-4'><img src={filePreview.src} alt={filePreview.title} className='max-h-[calc(100vh-7rem)] max-w-full object-contain' /></div>
            ) : (
              <div className='flex min-h-0 flex-1 flex-col overflow-auto p-3'><PdfPreview title={filePreview.title} src={filePreview.src} previews={filePreview.previews} /></div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  )
}

function DocumentPracticePanel({ landing, active, children }: { landing: boolean; active: string; children: React.ReactNode }) {
  return landing ? <WorkspacePanel id='document-center' value='practice' active={active}>{children}</WorkspacePanel> : children
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
  return getErrorMessage(error)
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

function roleLabel(role: string) {
  if (role === 'owner') return '家庭所有者'
  if (role === 'reviewer') return '可整理和复核'
  if (role === 'viewer') return '只读成员'
  return '家庭身份未确认'
}

function viewNeedsLearner(view: View) {
  return view === 'materials' || view === 'overview' || view === 'attempts' || view === 'learning'
    || view === 'progress' || view === 'documents' || view === 'knowledge'
}

function previewPages(value?: string): string[] {
  if (!value) return []
  try {
    const pages: unknown = JSON.parse(value)
    return Array.isArray(pages) ? pages.filter((page): page is string => typeof page === 'string' && Boolean(safeBusinessPath(page))) : []
  } catch { return [] }
}
