import type { ReactNode } from 'react'
import { ArrowUpRight, CircleHelp, ClipboardList, Image as ImageIcon, LoaderCircle, RefreshCw } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { ApiError, getErrorMessage } from '../api'
import type { EvidenceSource, Filters, SourceKind } from '../types'
import { Button } from './ui/button'

export type Remote<T> =
  | { status: 'loading' }
  | { status: 'loaded'; data: T }
  | { status: 'error'; message: string }

export const SOURCE_LABELS: Record<SourceKind, string> = {
  independent_answer: '独立作答',
  assisted_answer: '提示后作答',
  classroom_note: '课堂笔记',
  copied_work: '抄录作业',
  unknown: '来源未知',
}

export const INITIAL_FILTERS: Filters = { dateFrom: '', dateTo: '', sourceKind: '' }

export function sameOriginHref(value: string | null | undefined) {
  if (!value || typeof window === 'undefined') return null
  try {
    const target = new URL(value, window.location.origin)
    if (target.origin !== window.location.origin) return null
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return null
  }
}

export function errorText(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    return '登录状态已失效，请重新登录后继续。'
  }
  return getErrorMessage(error)
}

export function isUnauthorized(error: unknown) {
  return error instanceof ApiError && error.status === 401
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className='flex items-center gap-3 rounded-xl border bg-card px-5 py-6 text-sm text-muted-foreground' role='status' aria-live='polite'>
      <LoaderCircle className='size-4 animate-spin text-primary' aria-hidden='true' />
      {label}
    </div>
  )
}

export function RetryState({
  message,
  onRetry,
  title = '暂时无法加载',
}: {
  message: string
  onRetry: () => void
  title?: string
}) {
  return (
    <div className='rounded-xl border border-amber-300/70 bg-amber-50/70 p-5' role='alert'>
      <div className='flex items-start gap-3'>
        <CircleHelp className='mt-0.5 size-5 shrink-0 text-amber-700' aria-hidden='true' />
        <div className='min-w-0 flex-1'>
          <h3 className='font-semibold text-foreground'>{title}</h3>
          <p className='mt-1 text-sm leading-6 text-muted-foreground'>{message}</p>
          <Button type='button' variant='outline' size='sm' className='mt-3' onClick={onRetry}>
            <RefreshCw className='size-4' aria-hidden='true' />
            重试
          </Button>
        </div>
      </div>
    </div>
  )
}

export function EmptyState({
  title,
  detail,
  icon: Icon = ClipboardList,
}: {
  title: string
  detail: string
  icon?: LucideIcon
}) {
  return (
    <div className='flex min-h-48 flex-col items-center justify-center rounded-xl border border-dashed bg-card px-6 py-10 text-center'>
      <span className='mb-4 flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground'>
        <Icon className='size-5' aria-hidden='true' />
      </span>
      <h3 className='font-semibold'>{title}</h3>
      <p className='mt-1 max-w-md text-sm leading-6 text-muted-foreground'>{detail}</p>
    </div>
  )
}

export function ApiLink({ href, children }: { href: string | null | undefined; children: ReactNode }) {
  const safeHref = sameOriginHref(href)
  if (!safeHref) return null
  return (
    <a className='inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline' href={safeHref}>
      {children}
      <ArrowUpRight className='size-3.5' aria-hidden='true' />
    </a>
  )
}

export function SourceEvidence({ sources }: { sources: EvidenceSource[] }) {
  if (sources.length === 0) {
    return <p className='text-sm text-muted-foreground'>原图来源未记录。</p>
  }

  return (
    <ul className='space-y-2'>
      {sources.map((source) => {
        const pageHref = sameOriginHref(source.page_url)
        const previewHref = sameOriginHref(source.preview_url)
        return (
          <li key={`${source.region_revision_id}-${source.purpose}`} className='flex flex-wrap items-center gap-x-3 gap-y-1 text-sm'>
            <span className='inline-flex items-center gap-1.5 text-foreground'>
              <ImageIcon className='size-4 text-muted-foreground' aria-hidden='true' />
              {source.label || '原图证据'}
            </span>
            {source.missing ? (
              <span className='text-muted-foreground'>来源暂不可用</span>
            ) : (
              <>
                {pageHref ? <ApiLink href={source.page_url}>查看来源页</ApiLink> : null}
                {previewHref ? <ApiLink href={source.preview_url}>查看原图证据</ApiLink> : null}
                {!pageHref && !previewHref ? <span className='text-muted-foreground'>来源链接未提供</span> : null}
              </>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function formatCount(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('zh-CN').format(value) : '未提供'
}
