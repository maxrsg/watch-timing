import { useState } from 'react'
import { Menu, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { PAGES } from '@/lib/pages'
import { cn } from '@/lib/utils'

/** The menu button and the navigation drawer it opens. `current` is the page's hash. */
export function AppMenu({ current }: { current: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" className="size-11" aria-label="Menu">
          <Menu className="size-5" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" showCloseButton={false} className="safe-area-p gap-2">
        <div className="flex items-center justify-between gap-2">
          <SheetTitle className="text-lg">Watch timing</SheetTitle>
          <SheetClose asChild>
            <Button variant="ghost" className="size-11" aria-label="Close menu">
              <X className="size-5" />
            </Button>
          </SheetClose>
        </div>
        <SheetDescription className="sr-only">Go to a page</SheetDescription>
        <nav className="flex flex-col gap-1">
          {PAGES.map(({ hash, label, icon: Icon }) => (
            <a
              key={hash}
              href={hash || '#'}
              aria-current={hash === current ? 'page' : undefined}
              onClick={() => setOpen(false)}
              className={cn(
                'flex min-h-11 items-center gap-3 rounded-lg px-3 text-base hover:bg-muted',
                hash === current ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground',
              )}
            >
              <Icon className="size-5" /> {label}
            </a>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  )
}
