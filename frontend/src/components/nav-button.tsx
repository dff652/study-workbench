import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Button } from './ui/button'

export function NavButton({
  active,
  icon: Icon,
  onClick,
  children,
}: {
  active: boolean
  icon: LucideIcon
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Button type='button' variant={active ? 'secondary' : 'ghost'} className={`h-10 justify-start ${active ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground'}`} aria-current={active ? 'page' : undefined} onClick={onClick}>
      <Icon className='size-4' aria-hidden='true' />{children}
    </Button>
  )
}
