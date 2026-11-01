import type { ComponentProps } from 'react'
import { Watch } from 'lucide-react'
import { PAGES } from '@/lib/pages'
import { cn } from '@/lib/utils'

/** The app's name with a brass watch: the top of the drawer and the sidebar. */
export function Brand({ className, ...props }: ComponentProps<'span'>) {
  return (
    <span className={cn('flex items-center gap-2.5', className)} {...props}>
      <span className="flex size-9 items-center justify-center rounded-full border border-primary/40 bg-primary/10">
        <Watch className="size-5 text-primary" />
      </span>
      <span className="font-heading text-xl font-semibold tracking-tight">Watch Timing</span>
    </span>
  )
}

/** Links to the app's pages; `current` is the page's hash. */
export function NavLinks({ current, onNavigate }: { current: string; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1">
      {PAGES.map(({ hash, label, icon: Icon }) => (
        <a
          key={hash}
          href={hash || '#'}
          aria-current={hash === current ? 'page' : undefined}
          onClick={onNavigate}
          className={cn(
            'flex min-h-11 items-center gap-3 rounded-lg border-l-2 px-3 text-base transition-colors hover:bg-sidebar-accent',
            hash === current
              ? 'border-primary bg-sidebar-accent font-medium text-sidebar-foreground'
              : 'border-transparent text-muted-foreground',
          )}
        >
          <Icon className={cn('size-5', hash === current && 'text-primary')} /> {label}
        </a>
      ))}
    </nav>
  )
}
