import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

/** Keeps inputs mounted while secondary information is tucked away. */
export function Disclosure({ title, description, children, defaultOpen = false, className = '' }: {
  title: string
  description?: string
  children: ReactNode
  defaultOpen?: boolean
  className?: string
}) {
  return <details open={defaultOpen || undefined} className={`group/disclosure rounded-xl border bg-background ${className}`}>
    <summary className='flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:px-5'>
      <span className='min-w-0'><span className='block text-base font-semibold'>{title}</span>{description ? <span className='mt-1 block text-sm font-normal leading-6 text-muted-foreground'>{description}</span> : null}</span>
      <ChevronDown className='size-5 shrink-0 text-muted-foreground transition-transform group-open/disclosure:rotate-180 motion-reduce:transition-none' aria-hidden='true' />
    </summary>
    <div className='border-t px-4 py-4 sm:px-5'>{children}</div>
  </details>
}
