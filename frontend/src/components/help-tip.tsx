import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'

/** Supplemental help; essential instructions and errors belong in visible text. */
export function HelpTip({ children, label = '查看帮助' }: { children: ReactNode; label?: string }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 12, top: 12 })
  const trigger = useRef<HTMLButtonElement>(null)
  const tooltip = useRef<HTMLSpanElement>(null)
  const dismissed = useRef(false)
  const show = () => { if (!dismissed.current) setOpen(true) }
  const hide = () => { setOpen(false); dismissed.current = false }
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      if (!trigger.current || !tooltip.current) return
      const bounds = trigger.current.getBoundingClientRect()
      const size = tooltip.current.getBoundingClientRect()
      setPosition({
        left: Math.max(12, Math.min(bounds.left, window.innerWidth - size.width - 12)),
        top: bounds.bottom + size.height + 12 < window.innerHeight ? bounds.bottom + 4 : Math.max(12, bounds.top - size.height - 4),
      })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open])
  return (
    <span className='relative inline-flex align-middle'
      onPointerEnter={(event) => { if (event.pointerType === 'mouse') show() }}
      onPointerLeave={(event) => { if (event.pointerType === 'mouse' && document.activeElement !== trigger.current) hide() }}>
      <button ref={trigger} type='button' aria-label={label} aria-expanded={open} aria-controls={id}
        aria-describedby={open ? id : undefined}
        className='inline-flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
        onFocus={show} onBlur={hide}
        onClick={() => { dismissed.current = false; setOpen(true) }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') { setOpen(false); dismissed.current = true; event.stopPropagation() }
        }}>
        <CircleHelp className='size-4' aria-hidden='true' />
      </button>
      {open ? <span ref={tooltip} id={id} role='tooltip' style={position}
        className='fixed z-50 w-64 max-w-[calc(100vw-3rem)] rounded-lg border bg-popover px-3 py-2 text-left text-sm font-normal leading-6 text-popover-foreground shadow-md'>{children}</span> : null}
    </span>
  )
}
