import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, LoaderCircle, RotateCcw } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { safeBusinessPath } from '../../routing/routes'
import { getWorkspacePage, postWorkspaceForm, type WorkspacePageData, type WorkspacePageScope, type WorkspaceWidget } from './page-api'
import './page.css'

const WIDGET_SCRIPTS: Record<WorkspaceWidget, string> = {
  regions: '/static/web/regions.js',
  order: '/static/web/order.js',
  derivatives: '/static/web/derivatives.js',
}

export function WorkspacePage({
  url,
  anchor = '',
  csrfToken,
  onNavigate,
  onScopeLoaded,
  onUnauthorized,
  onUnsavedChange,
}: {
  url: string
  anchor?: string
  csrfToken: string
  onNavigate: (url: string) => void
  onScopeLoaded?: (scope: WorkspacePageScope, requestedUrl: string) => void
  onUnauthorized: () => void
  onUnsavedChange: (hasChanges: boolean) => void
}) {
  const [page, setPage] = useState<WorkspacePageData | null>(null)
  const [pageRequestedUrl, setPageRequestedUrl] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [widgetErrors, setWidgetErrors] = useState<WorkspaceWidget[]>([])
  const pageHtml = useMemo(() => page ? { __html: page.html } : undefined, [page])
  const contentRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<HTMLDivElement>(null)
  const submitControllerRef = useRef<AbortController | null>(null)
  const loadControllerRef = useRef<AbortController | null>(null)
  const unsavedRef = useRef(false)
  const onScopeLoadedRef = useRef(onScopeLoaded)
  onScopeLoadedRef.current = onScopeLoaded

  useEffect(() => {
    if (page?.scope && pageRequestedUrl === url) onScopeLoadedRef.current?.(page.scope, pageRequestedUrl)
  }, [page, pageRequestedUrl, url])

  useEffect(() => () => {
    submitControllerRef.current?.abort()
    loadControllerRef.current?.abort()
  }, [])

  const loadPage = useCallback(async (signal: AbortSignal) => {
    const result = await getWorkspacePage(url, signal)
    if (signal.aborted) return
    if (result.data.redirect) {
      onNavigate(result.data.redirect)
      return
    }
    const nextPage = result.data.page || null
    setPage(nextPage)
    setPageRequestedUrl(url)
    setError('')
    setNotice('')
    unsavedRef.current = false
    onUnsavedChange(false)
  }, [onNavigate, onUnsavedChange, url])

  useEffect(() => {
    loadControllerRef.current?.abort()
    const controller = new AbortController()
    loadControllerRef.current = controller
    setLoading(true)
    setError('')
    setNotice('')
    loadPage(controller.signal).catch((reason: unknown) => {
      if (controller.signal.aborted) return
      const status = statusFor(reason)
      if (status === 401) onUnauthorized()
      setError(messageFor(reason))
    }).finally(() => {
      if (loadControllerRef.current === controller) {
        loadControllerRef.current = null
        setLoading(false)
      }
    })
    return () => {
      controller.abort()
      if (loadControllerRef.current === controller) loadControllerRef.current = null
    }
  }, [loadPage, onUnauthorized])

  const markChanged = useCallback(() => {
    unsavedRef.current = true
    onUnsavedChange(true)
  }, [onUnsavedChange])

  useLayoutEffect(() => {
    const root = contentRef.current
    if (!root || !page) return
    root.addEventListener('input', markChanged)
    root.addEventListener('change', markChanged)
    return () => {
      root.removeEventListener('input', markChanged)
      root.removeEventListener('change', markChanged)
    }
  }, [markChanged, page])

  const handleSubmit = useCallback((event: SubmitEvent) => {
    if (event.defaultPrevented || !page) return
    const form = event.target
    if (!(form instanceof HTMLFormElement)) return
    event.preventDefault()
    setNotice('')
    const submitter = event.submitter
    const action = submitter instanceof HTMLElement ? submitter.getAttribute('formaction') : null
    const method = submitter instanceof HTMLElement ? submitter.getAttribute('formmethod') : null
    const targetUrl = safeBusinessPath(action || form.getAttribute('action') || page.url)
    if (!targetUrl) {
      setNotice('表单地址无效，请返回页面后重试。')
      return
    }
    const formData = formDataWithSubmitter(form, submitter)
    const resolvedMethod = (method || form.getAttribute('method') || 'get').toUpperCase()
    if (resolvedMethod === 'GET') {
      unsavedRef.current = false
      onUnsavedChange(false)
      onNavigate(urlWithFormValues(targetUrl, formData))
      return
    }
    if (resolvedMethod !== 'POST') {
      setNotice('这个表单暂不支持当前提交方式。')
      return
    }
    if (submitControllerRef.current) return
    unsavedRef.current = true
    onUnsavedChange(true)
    const controller = new AbortController()
    submitControllerRef.current = controller
    postWorkspaceForm(targetUrl, formData, csrfToken, controller.signal).then((result) => {
      if (controller.signal.aborted || submitControllerRef.current !== controller) return
      if (result.data.redirect) {
        unsavedRef.current = false
        onUnsavedChange(false)
        onNavigate(result.data.redirect)
        return
      }
      if (result.data.page) {
        setPage(result.data.page)
        setPageRequestedUrl(url)
      }
      if (result.response.ok) {
        unsavedRef.current = false
        onUnsavedChange(false)
        setNotice('更改已保存。')
      } else {
        unsavedRef.current = true
        onUnsavedChange(true)
        setNotice('请检查表单中的提示并完成修改。')
      }
      setError('')
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return
      if (statusFor(reason) === 401) onUnauthorized()
      unsavedRef.current = true
      setNotice(messageFor(reason))
    }).finally(() => {
      if (submitControllerRef.current === controller) submitControllerRef.current = null
    })
  }, [csrfToken, onNavigate, onUnauthorized, onUnsavedChange, page, url])

  useLayoutEffect(() => {
    const root = contentRef.current
    if (!root || !page) return
    root.addEventListener('submit', handleSubmit)
    return () => root.removeEventListener('submit', handleSubmit)
  }, [handleSubmit, page])

  useEffect(() => {
    const host = widgetRef.current
    if (!host || !page) return
    let cancelled = false
    const scripts: HTMLScriptElement[] = []
    setWidgetErrors([])
    const loadWidgets = async () => {
      const failed: WorkspaceWidget[] = []
      for (const widget of page.widgets) {
        if (cancelled) return
        const script = document.createElement('script')
        script.src = WIDGET_SCRIPTS[widget]
        script.async = false
        script.dataset.workspaceWidget = widget
        scripts.push(script)
        const loaded = await new Promise<boolean>((resolve) => {
          script.addEventListener('load', () => resolve(true), { once: true })
          script.addEventListener('error', () => resolve(false), { once: true })
          host.appendChild(script)
        })
        if (!loaded) failed.push(widget)
      }
      if (!cancelled) setWidgetErrors(failed)
    }
    void loadWidgets()
    return () => {
      cancelled = true
      scripts.forEach((script) => script.remove())
    }
  }, [page])

  useEffect(() => {
    const root = contentRef.current
    if (!root || !page || !anchor) return
    let targetId = anchor.startsWith('#') ? anchor.slice(1) : anchor
    try { targetId = decodeURIComponent(targetId) } catch { return }
    let frame = 0
    const scroll = () => {
      const target = root.ownerDocument.getElementById(targetId)
      if (target && root.contains(target)) target.scrollIntoView?.({ block: 'start' })
    }
    if (typeof window.requestAnimationFrame === 'function') frame = window.requestAnimationFrame(scroll)
    else window.setTimeout(scroll, 0)
    return () => { if (frame) window.cancelAnimationFrame(frame) }
  }, [anchor, page])

  const retry = () => {
    if (unsavedRef.current && !window.confirm('页面有未保存的更改。确定重新读取页面吗？')) return
    loadControllerRef.current?.abort()
    const controller = new AbortController()
    loadControllerRef.current = controller
    setLoading(true)
    setError('')
    loadPage(controller.signal).catch((reason: unknown) => {
      if (statusFor(reason) === 401) onUnauthorized()
      setError(messageFor(reason))
    }).finally(() => {
      if (loadControllerRef.current === controller) {
        loadControllerRef.current = null
        setLoading(false)
      }
    })
  }

  return (
    <section className='space-y-4' aria-label={page?.title || '业务页面'}>
      {loading ? <div className='flex items-center gap-2 rounded-lg border bg-card px-4 py-5 text-sm text-muted-foreground' role='status'><LoaderCircle className='size-4 animate-spin' aria-hidden='true' />正在打开页面…</div> : null}
      {error ? (
        <div className='rounded-lg border border-amber-300 bg-amber-50 p-5' role='alert'>
          <div className='flex items-start gap-3'><AlertCircle className='mt-0.5 size-5 text-amber-800' aria-hidden='true' /><div className='min-w-0 flex-1'><p className='font-semibold'>暂时无法打开这个页面</p><p className='mt-1 text-sm text-amber-950'>{error}</p><Button type='button' size='sm' variant='outline' className='mt-3' onClick={retry}><RotateCcw className='size-4' aria-hidden='true' />重试</Button></div></div>
        </div>
      ) : null}
      {widgetErrors.length ? (
        <div className='rounded-lg border border-amber-300 bg-amber-50 p-4' role='alert'>
          <div className='flex flex-wrap items-center gap-3'>
            <div className='min-w-0 flex-1'><p className='font-semibold'>页面交互功能加载失败</p><p className='mt-1 text-sm text-amber-950'>以下功能脚本未能加载：{widgetErrors.map(widgetLabel).join('、')}。页面内容仍可查看，请重试页面后再使用这些功能。</p></div>
            <Button type='button' size='sm' variant='outline' onClick={retry}><RotateCcw className='size-4' aria-hidden='true' />重试页面</Button>
          </div>
        </div>
      ) : null}
      {notice ? <p role='status' className='rounded-lg border bg-muted/40 px-4 py-3 text-sm'>{notice}</p> : null}
      {page ? <>
        <div ref={contentRef} className='workspace-page min-w-0 space-y-4' dangerouslySetInnerHTML={pageHtml} />
        <div ref={widgetRef} aria-hidden='true' className='hidden' />
      </> : null}
    </section>
  )
}

function formDataWithSubmitter(form: HTMLFormElement, submitter: EventTarget | null) {
  const result = new FormData(form)
  if (submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) {
    if (submitter.name && !submitter.disabled) result.append(submitter.name, submitter.value)
  }
  return result
}

function urlWithFormValues(path: string, formData: FormData) {
  const target = new URL(path, window.location.origin)
  const submittedNames = new Set<string>()
  for (const [name, value] of formData.entries()) {
    if (typeof value === 'string') submittedNames.add(name)
  }
  for (const name of submittedNames) target.searchParams.delete(name)
  for (const [name, value] of formData.entries()) {
    if (typeof value === 'string') target.searchParams.append(name, value)
  }
  return `${target.pathname}${target.search}`
}

function statusFor(error: unknown) {
  return typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number'
    ? error.status
    : 0
}

function widgetLabel(widget: WorkspaceWidget) {
  const labels: Record<WorkspaceWidget, string> = { regions: '原图区域框选', order: '页面排序', derivatives: '图片派生处理' }
  return labels[widget]
}

function messageFor(error: unknown) {
  if (typeof error === 'object' && error !== null && 'message' in error && typeof error.message === 'string') return error.message
  return '页面请求暂时失败，请重试。'
}
