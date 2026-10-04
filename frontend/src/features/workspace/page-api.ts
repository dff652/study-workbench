import { safeBusinessPath } from '../../routing/routes'

export type WorkspaceWidget = 'regions' | 'order' | 'derivatives'

export type WorkspacePageScope = { household_id: string; learner_id: string }

export type WorkspacePageData = {
  url: string
  title: string
  html: string
  widgets: WorkspaceWidget[]
  scope?: WorkspacePageScope
}

export type WorkspacePageResponse = {
  schema_version: 'swb.api.v1'
  page?: WorkspacePageData
  redirect?: string
  error?: { code?: string; message?: string }
}

export type WorkspacePageResult = {
  response: Response
  data: WorkspacePageResponse
}

export class WorkspacePageError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'WorkspacePageError'
    this.status = status
    this.code = code
  }
}

export async function getWorkspacePage(url: string, signal: AbortSignal): Promise<WorkspacePageResult> {
  const safeUrl = safeBusinessPath(url)
  if (!safeUrl) throw new WorkspacePageError(400, 'invalid_url', '页面地址无效，请从工作台导航重新打开。')
  const endpoint = new URL('/api/v1/workspace/page/', window.location.origin)
  endpoint.searchParams.set('url', safeUrl)
  return readWorkspaceResponse(await fetch(endpoint, {
    method: 'GET',
    signal,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  }))
}

export async function postWorkspaceForm(
  url: string,
  form: FormData,
  csrfToken: string,
  signal: AbortSignal,
): Promise<WorkspacePageResult> {
  const safeUrl = safeBusinessPath(url)
  if (!safeUrl) throw new WorkspacePageError(400, 'invalid_url', '表单地址无效，请从工作台导航重新打开。')
  const endpoint = new URL('/api/v1/workspace/submit/', window.location.origin)
  endpoint.searchParams.set('url', safeUrl)
  return readWorkspaceResponse(await fetch(endpoint, {
    method: 'POST',
    signal,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken },
    body: form,
  }))
}

async function readWorkspaceResponse(response: Response): Promise<WorkspacePageResult> {
  let data: WorkspacePageResponse
  try {
    data = await response.json() as WorkspacePageResponse
  } catch {
    throw new WorkspacePageError(response.status, 'invalid_response', response.status === 401
      ? '登录状态已失效，请重新登录后继续。'
      : '页面响应暂时无法读取，请重试。')
  }

  if (data.schema_version !== 'swb.api.v1') {
    throw new WorkspacePageError(response.status, 'invalid_response', '页面响应格式暂时无法识别，请重试。')
  }
  if (!response.ok && !(response.status === 400 && data.page)) {
    throw new WorkspacePageError(response.status, data.error?.code || 'request_failed', messageForStatus(response.status, data.error?.message))
  }
  if (data.page) {
    const safeUrl = safeBusinessPath(data.page.url)
    const scope = data.page.scope === undefined ? undefined : normalizePageScope(data.page.scope)
    if (!safeUrl || typeof data.page.html !== 'string' || !data.page.html.trim() || typeof data.page.title !== 'string' || !Array.isArray(data.page.widgets)
      || (data.page.scope !== undefined && !scope)) {
      throw new WorkspacePageError(response.status, 'invalid_page', '页面内容暂时无法显示，请重试。')
    }
    const widgets = data.page.widgets.filter(isWorkspaceWidget)
    data = { ...data, page: { ...data.page, url: safeUrl, widgets, ...(scope ? { scope } : {}) } }
  }
  if (data.redirect && !safeBusinessPath(data.redirect)) {
    throw new WorkspacePageError(response.status, 'invalid_redirect', '页面已完成，但目标地址无效。')
  }
  if (!data.page && !data.redirect) {
    throw new WorkspacePageError(response.status, 'empty_response', '页面没有返回可显示的内容，请重试。')
  }
  return { response, data }
}

function normalizePageScope(value: unknown): WorkspacePageScope | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const scope = value as Record<string, unknown>
  if (typeof scope.household_id !== 'string' || !scope.household_id.trim()
    || typeof scope.learner_id !== 'string' || !scope.learner_id.trim()) return null
  return { household_id: scope.household_id.trim(), learner_id: scope.learner_id.trim() }
}

function isWorkspaceWidget(value: unknown): value is WorkspaceWidget {
  return value === 'regions' || value === 'order' || value === 'derivatives'
}

function messageForStatus(status: number, detail?: string) {
  if (status === 401) return '登录状态已失效，请重新登录后继续。'
  if (status === 403) return '当前账号没有权限查看这个页面。'
  if (status === 404) return '找不到这个页面，可能已移动或当前家庭下不可用。'
  if (detail && detail.trim()) return detail
  return '暂时无法打开这个页面，请检查连接后重试。'
}
