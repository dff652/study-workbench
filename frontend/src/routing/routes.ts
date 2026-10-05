export const VIEWS = ['materials', 'overview', 'attempts', 'progress', 'knowledge', 'learning', 'documents', 'settings'] as const

export type View = (typeof VIEWS)[number]

export type AppRoute = {
  view: View
  household: string
  learner: string
  screen: string
}

export type LearnerRouteTarget = { id: string; report_url: string }

export const DEFAULT_ROUTE: AppRoute = {
  view: 'overview',
  household: '',
  learner: '',
  screen: '',
}

export function safeBusinessPath(value: string, origin = window.location.origin): string | null {
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null
  try {
    const target = new URL(value, origin)
    if (target.origin !== origin || !['http:', 'https:'].includes(target.protocol)) return null
    const decodedPath = decodeURIComponent(target.pathname)
    if (decodedPath.includes('\\') || decodedPath.startsWith('//')) return null
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return null
  }
}

export function parseRoute(location: Pick<Location, 'pathname' | 'search'>, origin = window.location.origin): AppRoute {
  const params = new URLSearchParams(location.search)
  const requestedView = params.get('view')
  const view = isView(requestedView) ? requestedView : DEFAULT_ROUTE.view
  const rawScreen = params.get('screen') || ''
  const screen = rawScreen ? safeBusinessPath(rawScreen, origin) || '' : ''
  const screenUrl = screen ? new URL(screen, origin) : null
  const screenLearner = screenUrl
    ? learnerForProfilePath(screenUrl.pathname) || screenUrl.searchParams.get('learner') || ''
    : ''
  const screenHousehold = screen ? householdIdForBusinessPath(screen, origin) : null
  const outerHousehold = params.get('household') || params.get('household_id') || ''
  return {
    view,
    household: screenHousehold || outerHousehold,
    learner: screenLearner || (screenHousehold && screenHousehold !== outerHousehold ? '' : params.get('learner') || ''),
    screen,
  }
}

export function routeUrl(route: AppRoute) {
  const params = new URLSearchParams()
  params.set('view', route.view)
  if (route.household) params.set('household', route.household)
  if (route.learner) params.set('learner', route.learner)
  if (route.screen) params.set('screen', route.screen)
  return `/app/?${params.toString()}`
}

export function screenForView(view: View, household: string, learner = ''): string {
  if (!household) return ''
  switch (view) {
    case 'knowledge':
      return scopedPath('/knowledge/', 'household_id', household)
    case 'learning':
      return scopedPath('/learning/', 'household', household, learner)
    case 'documents':
      return scopedPath('/prints/', 'household', household)
    case 'settings':
      return scopedPath('/members/', 'household_id', household)
    default:
      return ''
  }
}

export function routeForBusinessPath(path: string, current: AppRoute, learner = current.learner, learners: readonly LearnerRouteTarget[] = []): AppRoute | null {
  const safePath = safeBusinessPath(path)
  if (!safePath) return null
  const target = new URL(safePath, window.location.origin)
  if (target.pathname === '/app/') return parseRoute(target)
  if (isFilePath(target.pathname)) return null
  const view = viewForBusinessPath(target.pathname, current.view)
  const pathHousehold = householdIdForBusinessPath(safePath)
  const requestedHousehold = target.searchParams.get('household') || target.searchParams.get('household_id')
  const household = pathHousehold || requestedHousehold || current.household
  const profileLearner = learnerForProfilePath(target.pathname)
  const hasRequestedLearner = target.searchParams.has('learner')
  const requestedLearner = hasRequestedLearner ? target.searchParams.get('learner') || '' : ''
  const linkedLearner = household === current.household ? learnerIdForBusinessPath(safePath, learners) || '' : ''
  const targetLearner = profileLearner || linkedLearner || (hasRequestedLearner ? requestedLearner : household === current.household ? learner : '')
  return {
    ...current,
    view,
    household,
    learner: targetLearner,
    screen: safePath,
  }
}

export function householdIdForBusinessPath(path: string, origin = window.location.origin): string | null {
  const safePath = safeBusinessPath(path, origin)
  if (!safePath) return null
  const pathname = new URL(safePath, origin).pathname
  const match = pathname.match(/^\/(?:operations\/household|ai\/(?:config|new))\/([^/]+)(?:\/|$)/)
  if (!match) return null
  try {
    const household = decodeURIComponent(match[1])
    return household && !household.includes('/') && !household.includes('\\') ? household : null
  } catch {
    return null
  }
}

export function learnerIdForBusinessPath(path: string, learners: readonly LearnerRouteTarget[], origin = window.location.origin): string | null {
  const safePath = safeBusinessPath(path, origin)
  if (!safePath) return null
  const targetPath = new URL(safePath, origin).pathname
  const profileLearner = learnerForProfilePath(targetPath)
  if (profileLearner && learners.some((learner) => learner.id === profileLearner)) return profileLearner

  for (const learner of learners) {
    const reportUrl = safeBusinessPath(learner.report_url, origin)
    if (!reportUrl) continue
    const reportPath = new URL(reportUrl, origin).pathname
    if (targetPath === reportPath) return learner.id
    const match = reportPath.match(/^\/study\/learner\/(\d+)\/report\/$/)
    if (!match) continue
    if (targetPath === `/study/learner/${match[1]}/schedule/new/` || targetPath === `/prints/reports/${match[1]}/`) return learner.id
  }
  return null
}

export function printReportPathForLearner(reportUrl: string, origin = window.location.origin) {
  const safeReportUrl = safeBusinessPath(reportUrl, origin)
  if (!safeReportUrl) return null
  const match = new URL(safeReportUrl, origin).pathname.match(/^\/study\/learner\/(\d+)\/report\/$/)
  return match ? `/prints/reports/${match[1]}/` : null
}

export function withoutFragment(path: string) {
  const safePath = safeBusinessPath(path)
  if (!safePath) return ''
  const target = new URL(safePath, window.location.origin)
  return `${target.pathname}${target.search}`
}

export function fragmentOfPath(path: string) {
  const safePath = safeBusinessPath(path)
  return safePath ? new URL(safePath, window.location.origin).hash : ''
}

export function previewKindForPath(pathname: string): 'image' | 'pdf' | null {
  if (/^\/page\/[^/]+\/preview\/\d+\/?$/i.test(pathname)
    || /^\/derivative\/[^/]+\/?$/i.test(pathname)
    || /^\/prints\/diagrams\/files\/\d+\/png\/?$/i.test(pathname)
    || /\.(?:png|jpe?g|webp|gif|svg)\/?$/i.test(pathname)) return 'image'
  if (/\.pdf\/?$/i.test(pathname)) return 'pdf'
  return null
}

export function solutionScreen(materialId: string) {
  return `/__app__/solutions/${encodeURIComponent(materialId)}/`
}

export function solutionMaterialId(screen: string) {
  const match = screen.split(/[?#]/, 1)[0].match(/^\/__app__\/solutions\/([^/?#]+)\/$/)
  if (!match) return null
  try {
    const materialId = decodeURIComponent(match[1])
    return materialId && !materialId.includes('/') && !materialId.includes('\\') ? materialId : null
  } catch {
    return null
  }
}

export function viewForBusinessPath(pathname: string, fallback: View): View {
  if (pathname.startsWith('/knowledge/')) return 'knowledge'
  if (pathname.startsWith('/catalogue/')) return 'knowledge'
  if (pathname.startsWith('/learning/schedules/')) return 'progress'
  if (pathname.startsWith('/learning/')) return 'learning'
  if (pathname.startsWith('/study/')) return 'progress'
  if (pathname.startsWith('/prints/')) return 'documents'
  if (pathname === '/help/' || pathname === '/help') return 'settings'
  if (pathname.startsWith('/members/') || pathname.startsWith('/ai/') || pathname.startsWith('/operations/')) return 'settings'
  if (/^\/(materials|material|page|question|workflows|workflow|prepare|derivative)\//.test(pathname)) return 'materials'
  return fallback
}

function learnerForProfilePath(pathname: string) {
  const match = pathname.match(/^\/learning\/profile\/([^/]+)(?:\/.*)?$/)
  if (!match) return ''
  try {
    const learnerId = decodeURIComponent(match[1])
    return learnerId && learnerId !== 'new' && !learnerId.includes('/') && !learnerId.includes('\\') ? learnerId : ''
  } catch {
    return ''
  }
}

export function isFilePath(pathname: string) {
  return /\.(?:pdf|png|jpe?g|webp|gif|svg|docx?|xlsx?|zip|json)\/?$/i.test(pathname)
    || /\/(?:download|original|derivative)\/$/i.test(pathname)
    || /^\/prints\/diagrams\/files\/\d+\/vector\/?$/i.test(pathname)
    || pathname.startsWith('/media/')
}

function scopedPath(path: string, householdKey: string, household: string, learner = '') {
  const params = new URLSearchParams({ [householdKey]: household })
  if (learner) params.set('learner', learner)
  return `${path}?${params.toString()}`
}

function isView(value: string | null): value is View {
  return Boolean(value && (VIEWS as readonly string[]).includes(value))
}
