import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { KnowledgeFormulaTools } from '../../components/knowledge-formula-tools'
import { AlertCircle, LoaderCircle, RotateCcw } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { usePrivateDraft } from '../drafts/use-private-draft'
import type { PrivateDraft } from '../drafts/client'
import { safeBusinessPath } from '../../routing/routes'
import { userMessage } from '../../lib/user-message'
import { revealWorkspacePanel, wireWorkspaceTabs } from './native-tabs'
import { getWorkspacePage, postWorkspaceForm, type WorkspacePageData, type WorkspacePageScope, type WorkspaceWidget } from './page-api'
import './page.css'

const WIDGET_SCRIPTS: Record<WorkspaceWidget, string> = {
  regions: '/static/web/regions.js',
  order: '/static/web/order.js',
  derivatives: '/static/web/derivatives.js',
}

type WorkspaceDraftControl = { name: string; label: string; kind: string; ordinal: number; values: string[]; displayValues?: string[]; checked?: boolean }
type WorkspaceDraftForm = { index: number; actionPath: string; fields: WorkspaceDraftControl[] }
type WorkspaceDraftPayload = { forms: WorkspaceDraftForm[]; filesNeedReselection: boolean; notSavedOversize?: boolean }

export function WorkspacePage({
  url,
  anchor = '',
  householdId,
  canWrite,
  csrfToken,
  onNavigate,
  onScopeLoaded,
  onUnauthorized,
  onUnsavedChange,
  initialTab = '',
  onTabChange,
}: {
  url: string
  anchor?: string
  householdId: string
  canWrite: boolean
  csrfToken: string
  onNavigate: (url: string) => void
  onScopeLoaded?: (scope: WorkspacePageScope, requestedUrl: string) => void
  onUnauthorized: () => void
  onUnsavedChange: (hasChanges: boolean) => void
  initialTab?: string
  onTabChange?: (value: string) => void
}) {
  const [page, setPage] = useState<WorkspacePageData | null>(null)
  const [pageRequestedUrl, setPageRequestedUrl] = useState('')
  const [reloadVersion, setReloadVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [widgetErrors, setWidgetErrors] = useState<WorkspaceWidget[]>([])
  const [submitPending, setSubmitPending] = useState(false)
  const [draftPayload, setDraftPayload] = useState<WorkspaceDraftPayload>({ forms: [], filesNeedReselection: false, notSavedOversize: false })
  const [draftDirty, setDraftDirty] = useState(false)
  const [filesNeedReselection, setFilesNeedReselection] = useState(false)
  const filesNeedReselectionRef = useRef(false)
  const contentRef = useRef<HTMLDivElement>(null)
  const [formulaHost, setFormulaHost] = useState<HTMLElement | null>(null)
  const widgetRef = useRef<HTMLDivElement>(null)
  const submitControllerRef = useRef<AbortController | null>(null)
  const loadControllerRef = useRef<AbortController | null>(null)
  const unsavedRef = useRef(false)
  const draftPayloadRef = useRef<WorkspaceDraftPayload>({ forms: [], filesNeedReselection: false, notSavedOversize: false })
  const pendingFormRestoreRef = useRef<WorkspaceDraftPayload | null>(null)
  const onScopeLoadedRef = useRef(onScopeLoaded)
  const onTabChangeRef = useRef(onTabChange)
  const nativeTabsRef = useRef<ReturnType<typeof wireWorkspaceTabs> | null>(null)
  const initialTabRef = useRef(initialTab)
  initialTabRef.current = initialTab
  onTabChangeRef.current = onTabChange
  onScopeLoadedRef.current = onScopeLoaded
  const activePage = pageRequestedUrl === url ? page : null
  const pageHtml = useMemo(() => activePage ? { __html: activePage.html } : undefined, [activePage])
  const scopeMatches = Boolean(activePage?.scope && activePage.scope.household_id === householdId)
  const draftKey = activePage?.scope && scopeMatches ? workspaceDraftKey(activePage) : 'workspace:inactive'
  const draftBaseStamp = activePage?.scope && scopeMatches ? workspaceBaseStamp(activePage) : 'inactive'
  const privateDraft = usePrivateDraft<WorkspaceDraftPayload>({
    key: draftKey,
    householdId,
    csrfToken,
    baseStamp: draftBaseStamp,
    enabled: canWrite && scopeMatches,
    dirty: draftDirty,
    payload: draftPayload,
    onUnauthorized,
  })
  const privateDraftCandidate = privateDraft.candidate && isWorkspaceDraftData(privateDraft.candidate.payload)
    ? privateDraft.candidate
    : null
  const privateDraftConflict = privateDraft.conflict && (isClearedDraft(privateDraft.conflict.payload) || isWorkspaceDraftData(privateDraft.conflict.payload))
    ? privateDraft.conflict
    : privateDraft.conflict === null ? null : undefined
  const hasUnrecognizedDraft = Boolean(privateDraft.candidate && !privateDraftCandidate)
    || Boolean(privateDraft.conflict && !privateDraftConflict)

  useEffect(() => {
    if (activePage?.scope) onScopeLoadedRef.current?.(activePage.scope, pageRequestedUrl)
  }, [activePage, pageRequestedUrl])

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
    if (!activePage || !contentRef.current) return
    const tabs = wireWorkspaceTabs(contentRef.current, initialTabRef.current, (value) => onTabChangeRef.current?.(value))
    nativeTabsRef.current = tabs
    return () => { tabs.dispose(); nativeTabsRef.current = null }
  }, [activePage])

  useEffect(() => { nativeTabsRef.current?.select(initialTab) }, [initialTab])

  useEffect(() => {
    if (!activePage || !contentRef.current) return
    contentRef.current.querySelectorAll('.errorlist, [role="alert"]').forEach(expandDetailsForElement)
    const pending = pendingFormRestoreRef.current
    pendingFormRestoreRef.current = null
    if (pending) {
      draftPayloadRef.current = pending
      setDraftPayload(pending)
      setDraftDirty(true)
      filesNeedReselectionRef.current = pending.filesNeedReselection
      setFilesNeedReselection(pending.filesNeedReselection)
      window.setTimeout(() => restoreWorkspaceDraft(contentRef.current, pending), 0)
      return
    }
    const current = collectWorkspaceDraft(contentRef.current)
    draftPayloadRef.current = current
    setDraftPayload(current)
    setDraftDirty(false)
    filesNeedReselectionRef.current = false
    setFilesNeedReselection(false)
  }, [activePage])

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
  }, [loadPage, onUnauthorized, reloadVersion])

  const markChanged = useCallback(() => {
    unsavedRef.current = true
    onUnsavedChange(true)
  }, [onUnsavedChange])

  useLayoutEffect(() => {
    const root = contentRef.current
    if (!root || !activePage) return
    const openRow = (event: MouseEvent | KeyboardEvent) => {
      if (event.defaultPrevented || !(event.target instanceof Element)) return
      if (event instanceof MouseEvent && (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)) return
      const row = event.target.closest<HTMLElement>('[data-row-href]')
      if (!row || !root.contains(row) || event.target.closest('a, button, input, select, textarea, summary')) return
      if (event instanceof KeyboardEvent && (event.key !== 'Enter' || event.target !== row)) return
      const path = safeBusinessPath(row.dataset.rowHref || '')
      if (!path) return
      event.preventDefault()
      onNavigate(path)
    }
    root.addEventListener('click', openRow)
    root.addEventListener('keydown', openRow)
    return () => { root.removeEventListener('click', openRow); root.removeEventListener('keydown', openRow) }
  }, [activePage, onNavigate])

  const handleFormEdit = useCallback((event: Event) => {
    const target = event.target
    const form = target instanceof Element ? target.closest('form') : null
    if (!(form instanceof HTMLFormElement)) {
      markChanged()
      return
    }
    if (form.method.toUpperCase() !== 'POST') return
    const payload = collectWorkspaceDraft(contentRef.current)
    payload.filesNeedReselection ||= filesNeedReselectionRef.current
    draftPayloadRef.current = payload
    setDraftPayload(payload)
    setDraftDirty(true)
    privateDraft.setMessage('')
    markChanged()
  }, [markChanged, privateDraft.setMessage])

  const restorePrivateDraft = (draft: PrivateDraft<WorkspaceDraftPayload | { cleared: true }>) => {
    if (isClearedDraft(draft.payload) || !isWorkspaceDraftData(draft.payload) || !contentRef.current) {
      setNotice('这份草稿格式无法识别，当前页面内容未更改。请清理草稿后继续。')
      return
    }
    privateDraft.accept(draft)
    draftPayloadRef.current = draft.payload
    setDraftPayload(draft.payload)
    setDraftDirty(true)
    filesNeedReselectionRef.current = draft.payload.filesNeedReselection
    setFilesNeedReselection(draft.payload.filesNeedReselection)
    restoreWorkspaceDraft(contentRef.current, draft.payload)
    markChanged()
    setNotice(draft.payload.filesNeedReselection
      ? '已恢复可恢复的表单内容。此前选择的文件未保存在草稿中，请重新选择。'
      : '已恢复这份私人草稿；请检查后再提交表单。')
  }

  useLayoutEffect(() => {
    const root = contentRef.current
    if (!root || !activePage) return
    root.addEventListener('input', handleFormEdit)
    root.addEventListener('change', handleFormEdit)
    return () => {
      root.removeEventListener('input', handleFormEdit)
      root.removeEventListener('change', handleFormEdit)
    }
  }, [activePage, handleFormEdit])

  const handleSubmit = useCallback((event: SubmitEvent) => {
    if (event.defaultPrevented || !activePage) return
    const form = event.target
    if (!(form instanceof HTMLFormElement)) return
    event.preventDefault()
    setNotice('')
    const submitter = event.submitter
    const action = submitter instanceof HTMLElement ? submitter.getAttribute('formaction') : null
    const method = submitter instanceof HTMLElement ? submitter.getAttribute('formmethod') : null
    const targetUrl = safeBusinessPath(action || form.getAttribute('action') || activePage.url)
    if (!targetUrl) {
      setNotice('表单地址无效，请返回页面后重试。')
      return
    }
    const formData = formDataWithSubmitter(form, submitter)
    const resolvedMethod = (method || form.getAttribute('method') || 'get').toUpperCase()
    if (resolvedMethod === 'GET') {
      unsavedRef.current = false
      onUnsavedChange(false)
      setDraftDirty(false)
      onNavigate(urlWithFormValues(targetUrl, formData))
      return
    }
    if (resolvedMethod !== 'POST') {
      setNotice('这个表单暂不支持当前提交方式。')
      return
    }
    if (privateDraft.candidate || privateDraft.conflict !== undefined) {
      setNotice('请先比较并选择恢复草稿或保留当前内容，再提交表单。')
      return
    }
    if (submitControllerRef.current) return
    const submittedDraft = collectWorkspaceDraft(contentRef.current)
    draftPayloadRef.current = submittedDraft
    setDraftPayload(submittedDraft)
    setDraftDirty(true)
    privateDraft.setMessage('')
    unsavedRef.current = true
    onUnsavedChange(true)
    const controller = new AbortController()
    submitControllerRef.current = controller
    setSubmitPending(true)
    postWorkspaceForm(targetUrl, formData, csrfToken, controller.signal).then(async (result) => {
      if (controller.signal.aborted || submitControllerRef.current !== controller) return
      if (result.data.redirect) {
        pendingFormRestoreRef.current = null
        setDraftDirty(false)
        await privateDraft.tombstone()
        if (controller.signal.aborted || submitControllerRef.current !== controller) return
        unsavedRef.current = false
        onUnsavedChange(false)
        if (result.data.redirect === url) {
          setPage(null)
          setReloadVersion((version) => version + 1)
        } else {
          onNavigate(result.data.redirect)
        }
        return
      }
      if (result.data.page) {
        if (!result.response.ok) pendingFormRestoreRef.current = submittedDraft
        setPage(result.data.page)
        setPageRequestedUrl(url)
      }
      if (result.response.ok) {
        pendingFormRestoreRef.current = null
        void privateDraft.tombstone()
        setDraftDirty(false)
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
      if (submitControllerRef.current === controller) {
        submitControllerRef.current = null
        setSubmitPending(false)
      }
    })
  }, [csrfToken, onNavigate, onUnauthorized, onUnsavedChange, activePage, privateDraft.candidate, privateDraft.conflict, privateDraft.setMessage, privateDraft.tombstone, url])

  useLayoutEffect(() => {
    const root = contentRef.current
    if (!root || !activePage) return
    root.addEventListener('submit', handleSubmit)
    return () => root.removeEventListener('submit', handleSubmit)
  }, [activePage, handleSubmit])

  useEffect(() => {
    const host = widgetRef.current
    if (!host || !activePage) return
    let cancelled = false
    const scripts: HTMLScriptElement[] = []
    setWidgetErrors([])
    const loadWidgets = async () => {
      const failed: WorkspaceWidget[] = []
      for (const widget of activePage.widgets) {
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
  }, [activePage])

  useEffect(() => {
    const root = contentRef.current
    if (!root || !activePage || !anchor) return
    let targetId = anchor.startsWith('#') ? anchor.slice(1) : anchor
    try { targetId = decodeURIComponent(targetId) } catch { return }
    let frame = 0
    const scroll = () => {
      const target = root.ownerDocument.getElementById(targetId)
      if (target && root.contains(target)) {
        expandDetailsForElement(target)
        target.scrollIntoView?.({ block: 'start' })
      }
    }
    if (typeof window.requestAnimationFrame === 'function') frame = window.requestAnimationFrame(scroll)
    else window.setTimeout(scroll, 0)
    return () => { if (frame) window.cancelAnimationFrame(frame) }
  }, [anchor, activePage])

  useEffect(() => {
    if (privateDraft.message === '私人草稿已保存。' && !submitControllerRef.current) {
      unsavedRef.current = false
      onUnsavedChange(false)
    } else if (privateDraft.message.startsWith('私人草稿未保存')) {
      unsavedRef.current = true
      onUnsavedChange(true)
    }
  }, [onUnsavedChange, privateDraft.message])

  useLayoutEffect(() => {
    const root = contentRef.current
    const field = root?.querySelector('#id_display_markup')
    if (!root || !field || !root.querySelector('#id_definition')) { setFormulaHost(null); return }
    const host = document.createElement('div')
    field.parentElement?.appendChild(host)
    setFormulaHost(host)
    return () => { host.remove() }
  }, [activePage])

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
    <section className='space-y-4' aria-label={activePage?.title || '业务页面'}>
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
      {submitPending ? <p role='status' className='rounded-lg border bg-muted/40 px-4 py-3 text-sm'>正在提交表单；提交完成前暂时不能修改。</p> : null}
      <WorkspaceDraftRecovery
        candidate={privateDraftCandidate}
        conflict={privateDraftConflict}
        invalidDraft={hasUnrecognizedDraft}
        loadError={privateDraft.loadError}
        message={privateDraft.message}
        currentSummary={summarizeWorkspaceDraft(draftPayloadRef.current)}
        savedSummary={(draft) => isClearedDraft(draft.payload) ? '已清理' : summarizeWorkspaceDraft(draft.payload as WorkspaceDraftPayload)}
        filesNeedReselection={filesNeedReselection || draftNeedsReselection(privateDraftCandidate) || draftNeedsReselection(privateDraftConflict)}
        onRestore={restorePrivateDraft}
        onKeepCurrent={privateDraft.keepCurrent}
        onClearInvalid={privateDraft.keepCurrent}
      />
      {activePage ? <>
        <div ref={contentRef} className='workspace-page min-w-0 space-y-4' aria-busy={submitPending} inert={submitPending} dangerouslySetInnerHTML={pageHtml} />
        {formulaHost && contentRef.current ? createPortal(<KnowledgeFormulaTools root={contentRef.current} csrfToken={csrfToken} />, formulaHost) : null}
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
  if (typeof error === 'object' && error !== null && 'message' in error) return userMessage(error.message, '页面请求暂时失败，请重试。')
  return '页面请求暂时失败，请重试。'
}

function workspaceDraftKey(page: WorkspacePageData) {
  const scope = page.scope
  const path = new URL(page.url, window.location.origin).pathname
  return `workspace:${stableDigest(`${scope?.household_id || ''}\u0000${scope?.learner_id || ''}\u0000${path}`)}`
}

function workspaceBaseStamp(page: WorkspacePageData) {
  const scope = page.scope
  const path = new URL(page.url, window.location.origin).pathname
  return `page:${stableDigest(`${scope?.household_id || ''}\u0000${scope?.learner_id || ''}\u0000${path}`)}`
}

function stableDigest(value: string) {
  let first = 2166136261
  let second = 2246822519
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    first = Math.imul(first ^ code, 16777619)
    second = Math.imul(second ^ code, 3266489917)
  }
  return `${(first >>> 0).toString(16).padStart(8, '0')}${(second >>> 0).toString(16).padStart(8, '0')}`
}

function collectWorkspaceDraft(root: HTMLDivElement | null): WorkspaceDraftPayload {
  if (!root) return { forms: [], filesNeedReselection: false, notSavedOversize: false }
  const forms: WorkspaceDraftForm[] = []
  let filesNeedReselection = false
  let notSavedOversize = false
  let totalCharacters = 0
  const pageForms = Array.from(root.querySelectorAll('form'))
  for (const [index, form] of pageForms.entries()) {
    if (form.method.toUpperCase() !== 'POST') continue
    const fields: WorkspaceDraftControl[] = []
    const ordinals = new Map<string, number>()
    const controls = Array.from(form.elements).filter(isSafeDraftControl)
    for (const control of controls) {
      const kind = controlKind(control)
      const ordinalKey = `${control.name}\u0000${kind}`
      const ordinal = ordinals.get(ordinalKey) || 0
      ordinals.set(ordinalKey, ordinal + 1)
      const values = control instanceof HTMLSelectElement && control.multiple
        ? Array.from(control.selectedOptions, (option) => option.value)
        : [control.value]
      const label = controlLabel(control)
      const displayValues = displayValuesFor(control)
      const size = values.reduce((sum, value) => sum + value.length, 0)
        + displayValues.reduce((sum, value) => sum + value.length, 0) + label.length
      if (totalCharacters + size > 700_000 || fields.length >= 200) {
        notSavedOversize = true
        continue
      }
      totalCharacters += size
      fields.push({
        name: control.name,
        label,
        kind,
        ordinal,
        values,
        displayValues,
        ...(control instanceof HTMLInputElement && (kind === 'checkbox' || kind === 'radio') ? { checked: control.checked } : {}),
      })
    }
    if (Array.from(form.querySelectorAll('input[type="file"]')).some((input) => input instanceof HTMLInputElement && input.files?.length)) {
      filesNeedReselection = true
    }
    forms.push({ index, actionPath: formActionPath(form), fields })
  }
  return { forms, filesNeedReselection, notSavedOversize }
}

function isSafeDraftControl(control: Element): control is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement {
  if (!(control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement)) return false
  if (control.disabled || !control.name.trim() || isSensitiveField(control.name) || isSensitiveField(controlLabel(control))) return false
  if (control instanceof HTMLInputElement && ['hidden', 'file', 'password', 'submit', 'button', 'reset', 'image'].includes(control.type.toLowerCase())) return false
  return true
}

function isSensitiveField(value: string) {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]/g, '')
  return ['password', 'password1', 'password2', 'passwd', 'apikey', 'apisecret', 'secret', 'token', 'accesstoken', 'refreshtoken', 'authorization', 'csrfmiddlewaretoken', 'contexttoken', 'requestkey', 'requestid', 'credential', 'privatekey'].includes(normalized)
    || /password|passwd|token|secret|credential|authorization|csrf|requestkey|requestid|contexttoken|apikey|apisecret|privatekey|sessioncookie/.test(normalized)
}

function controlKind(control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement) {
  if (control instanceof HTMLInputElement) return control.type.toLowerCase()
  if (control instanceof HTMLSelectElement) return control.multiple ? 'select-multiple' : 'select'
  return 'textarea'
}

function controlLabel(control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement) {
  return (control.labels ? Array.from(control.labels, (item) => {
    const copy = item.cloneNode(true)
    if (copy instanceof Element) copy.querySelectorAll('input,textarea,select,button').forEach((nested) => nested.remove())
    return copy.textContent || ''
  }).join(' ').replace(/\s+/g, ' ').trim() : '').slice(0, 120)
}

function displayValuesFor(control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement) {
  if (control instanceof HTMLSelectElement) {
    return Array.from(control.selectedOptions, (option) => option.textContent?.replace(/\s+/g, ' ').trim() || '')
      .filter((value) => value.length > 0).map((value) => value.slice(0, 120))
  }
  if (control instanceof HTMLInputElement && (control.type === 'checkbox' || control.type === 'radio')) {
    return [control.checked ? '已选择' : '未选择']
  }
  return control.value ? [control.value.slice(0, 500)] : []
}

function formActionPath(form: HTMLFormElement) {
  const safe = safeBusinessPath(form.getAttribute('action') || window.location.pathname)
  return safe ? new URL(safe, window.location.origin).pathname : window.location.pathname
}

function expandDetailsForElement(element: Element) {
  revealWorkspacePanel(element)
  let ancestor: Element | null = element
  while (ancestor) {
    if (ancestor instanceof HTMLDetailsElement) ancestor.open = true
    ancestor = ancestor.parentElement
  }
}

function restoreWorkspaceDraft(root: HTMLDivElement | null, payload: WorkspaceDraftPayload) {
  if (!root) return
  const forms = Array.from(root.querySelectorAll('form'))
  for (const savedForm of payload.forms) {
    const form = forms[savedForm.index]
    if (!(form instanceof HTMLFormElement) || form.method.toUpperCase() !== 'POST' || formActionPath(form) !== savedForm.actionPath) continue
    const restoredChoiceGroups = new Set<string>()
    for (const field of savedForm.fields) {
      const matchingControls = Array.from(form.elements).filter((control): control is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement =>
        isSafeDraftControl(control) && control.name === field.name && controlKind(control) === field.kind,
      )
      if (field.kind === 'checkbox' || field.kind === 'radio') {
        const groupKey = `${field.kind}\u0000${field.name}`
        if (restoredChoiceGroups.has(groupKey)) continue
        restoredChoiceGroups.add(groupKey)
        const savedGroup = savedForm.fields.filter((item) => item.kind === field.kind && item.name === field.name)
        if (field.kind === 'radio') {
          const selected = savedGroup.find((item) => item.checked)
          const selectedControl = selected && matchingControls.find((item) => item instanceof HTMLInputElement && item.value === selected.values[0])
          if (selected && !selectedControl) continue
          const toUpdate = selectedControl ? [selectedControl] : matchingControls
          toUpdate.forEach((item) => {
            if (!(item instanceof HTMLInputElement)) return
            expandDetailsForElement(item)
            item.checked = item === selectedControl
            item.dispatchEvent(new Event('input', { bubbles: true }))
            item.dispatchEvent(new Event('change', { bubbles: true }))
          })
        } else {
          for (const saved of savedGroup) {
            const control = matchingControls.find((item) => item instanceof HTMLInputElement && item.value === saved.values[0])
            if (!(control instanceof HTMLInputElement)) continue
            expandDetailsForElement(control)
            control.checked = Boolean(saved.checked)
            control.dispatchEvent(new Event('input', { bubbles: true }))
            control.dispatchEvent(new Event('change', { bubbles: true }))
          }
        }
        continue
      }
      const control = matchingControls[field.ordinal]
      if (!control) continue
      if (control instanceof HTMLSelectElement) {
        const existingValues = field.values.filter((value) => Array.from(control.options).some((option) => option.value === value))
        if (!existingValues.length && (!control.multiple || field.values.length > 0)) continue
        expandDetailsForElement(control)
        if (control.multiple) {
          const selected = new Set(existingValues)
          Array.from(control.options).forEach((option) => { option.selected = selected.has(option.value) })
        } else {
          control.value = existingValues[0]
        }
      } else {
        expandDetailsForElement(control)
        control.value = field.values[0] || ''
      }
      control.dispatchEvent(new Event('input', { bubbles: true }))
      control.dispatchEvent(new Event('change', { bubbles: true }))
    }
  }
}

function summarizeWorkspaceDraft(payload: WorkspaceDraftPayload) {
  const fields = payload.forms.flatMap((form) => form.fields)
  const lines = fields.slice(0, 6).map((field) => {
    const label = field.label || '填写项'
    const display = field.displayValues
    const value = display?.length
      ? display.join('、')
      : field.kind === 'checkbox' || field.kind === 'radio'
        ? (field.checked ? '已选择' : '未选择')
        : field.kind === 'select' || field.kind === 'select-multiple'
          ? (field.values.length ? '已保存选择' : '未选择')
          : field.label
            ? '未填写'
            : '已填写'
    return `${label}：${value}`
  })
  if (fields.length > 6) lines.push(`还有 ${fields.length - 6} 项内容`)
  if (!lines.length) lines.push('尚未填写可恢复的内容')
  if (payload.filesNeedReselection) lines.push('此前选择的文件需要重新选择')
  if (payload.notSavedOversize) lines.push('部分过长内容未保存到草稿')
  return lines.join('\n')
}

function isClearedDraft(value: unknown): value is { cleared: true } {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) && 'cleared' in value && value.cleared === true)
}

function isWorkspaceDraftData(value: unknown): value is WorkspaceDraftPayload {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const payload = value as Record<string, unknown>
  if (!Array.isArray(payload.forms) || payload.forms.length > 100 || typeof payload.filesNeedReselection !== 'boolean'
    || (payload.notSavedOversize !== undefined && typeof payload.notSavedOversize !== 'boolean')) return false
  const allowedKinds = new Set(['text', 'search', 'number', 'email', 'url', 'tel', 'date', 'datetime-local', 'month', 'week', 'time', 'checkbox', 'radio', 'select', 'select-multiple', 'textarea', 'color', 'range'])
  let totalCharacters = 0
  let totalFields = 0
  for (const formValue of payload.forms) {
    if (!formValue || typeof formValue !== 'object' || Array.isArray(formValue)) return false
    const form = formValue as Record<string, unknown>
    if (!Number.isSafeInteger(form.index) || (form.index as number) < 0 || typeof form.actionPath !== 'string'
      || !Array.isArray(form.fields) || form.fields.length > 200) return false
    const safePath = safeBusinessPath(form.actionPath)
    if (!safePath || new URL(safePath, window.location.origin).pathname !== form.actionPath) return false
    totalFields += form.fields.length
    if (totalFields > 500) return false
    for (const fieldValue of form.fields) {
      if (!fieldValue || typeof fieldValue !== 'object' || Array.isArray(fieldValue)) return false
      const field = fieldValue as Record<string, unknown>
      if (typeof field.name !== 'string' || !field.name.trim() || isSensitiveField(field.name)
        || typeof field.label !== 'string' || field.label.length > 120
        || typeof field.kind !== 'string' || !allowedKinds.has(field.kind)
        || !Number.isSafeInteger(field.ordinal) || (field.ordinal as number) < 0
        || !Array.isArray(field.values) || field.values.length > 500
        || !field.values.every((item) => typeof item === 'string' && item.length <= 250_000)
        || (field.displayValues !== undefined && (!Array.isArray(field.displayValues) || field.displayValues.length > 500
          || !field.displayValues.every((item) => typeof item === 'string' && item.length <= 500)))
        || (field.checked !== undefined && typeof field.checked !== 'boolean')) return false
      if (isSensitiveField(field.label)) return false
      totalCharacters += (field.values as string[]).reduce((total, item) => total + item.length, 0)
      totalCharacters += field.label.length
      if (Array.isArray(field.displayValues)) totalCharacters += (field.displayValues as string[]).reduce((total, item) => total + item.length, 0)
      if (totalCharacters > 900_000) return false
    }
  }
  return true
}

function draftNeedsReselection(draft: PrivateDraft<WorkspaceDraftPayload | { cleared: true }> | null | undefined) {
  return Boolean(draft && isWorkspaceDraftData(draft.payload) && draft.payload.filesNeedReselection)
}

function WorkspaceDraftRecovery({
  candidate,
  conflict,
  invalidDraft,
  loadError,
  message,
  currentSummary,
  savedSummary,
  filesNeedReselection,
  onRestore,
  onKeepCurrent,
  onClearInvalid,
}: {
  candidate: PrivateDraft<WorkspaceDraftPayload | { cleared: true }> | null
  conflict: PrivateDraft<WorkspaceDraftPayload | { cleared: true }> | null | undefined
  invalidDraft: boolean
  loadError: string
  message: string
  currentSummary: string
  savedSummary: (draft: PrivateDraft<WorkspaceDraftPayload | { cleared: true }>) => string
  filesNeedReselection: boolean
  onRestore: (draft: PrivateDraft<WorkspaceDraftPayload | { cleared: true }>) => void
  onKeepCurrent: () => void
  onClearInvalid: () => void
}) {
  const hasConflict = conflict !== undefined
  const pendingDraft = hasConflict ? conflict : candidate
  if (!hasConflict && !pendingDraft && !loadError && !message && !invalidDraft) return null
  return <section className='space-y-3 rounded-lg border border-sky-200 bg-sky-50/60 p-4' aria-label='私人草稿'>
    {loadError ? <div role='alert' className='text-sm text-amber-950'><p>私人草稿暂时无法读取，自动保存已暂停；当前页面输入仍保留。</p><p className='mt-1'>{userMessage(loadError, '请保留当前输入，稍后重新打开页面。')}</p></div> : null}
    {invalidDraft ? <div role='alert' className='flex flex-wrap items-center gap-3 text-sm text-amber-950'><span>这份私人草稿格式无法识别，当前页面内容没有被替换。</span><Button type='button' size='sm' variant='outline' onClick={onClearInvalid}>清理不可恢复草稿</Button></div> : null}
    {hasConflict || candidate ? <>
      <div><h2 className='font-semibold'>{hasConflict ? '另一窗口也修改了这项内容' : '发现一份未完成的表单草稿'}</h2><p className='mt-1 text-sm text-muted-foreground'>请先比较两边内容，再选择恢复草稿或保留当前输入；系统不会自动覆盖。</p></div>
      <div className='grid gap-3 sm:grid-cols-2'><div className='rounded-md border bg-background p-3'><h3 className='text-xs font-medium text-muted-foreground'>当前页面</h3><p className='mt-1 whitespace-pre-wrap break-words text-sm'>{currentSummary}</p></div><div className='rounded-md border bg-background p-3'><h3 className='text-xs font-medium text-muted-foreground'>已保存内容</h3><p className='mt-1 whitespace-pre-wrap break-words text-sm'>{pendingDraft ? savedSummary(pendingDraft) : '另一窗口已清理草稿'}</p></div></div>
      {filesNeedReselection ? <p className='text-sm text-amber-900'>草稿不包含本机文件；请重新选择需要上传的文件。</p> : null}
      <div className='flex flex-wrap gap-2'><Button type='button' size='sm' onClick={() => pendingDraft && !isClearedDraft(pendingDraft.payload) && onRestore(pendingDraft)} disabled={!pendingDraft || isClearedDraft(pendingDraft.payload)}>{pendingDraft && isClearedDraft(pendingDraft.payload) ? '草稿已清理' : hasConflict ? '恢复另一窗口内容' : '恢复这份草稿'}</Button><Button type='button' variant='outline' size='sm' onClick={onKeepCurrent}>保留当前内容</Button></div>
    </> : null}
    {!pendingDraft && !hasConflict && message ? <p role='status' className='text-sm text-muted-foreground'>{message}</p> : null}
  </section>
}
