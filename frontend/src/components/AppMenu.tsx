import { useState } from 'react'
import { Menu, X } from 'lucide-react'
import { Brand, NavLinks } from '@/components/NavLinks'
import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet'

/** The menu button and the navigation drawer it opens (phones; desktops have the sidebar). */
export function AppMenu({ current }: { current: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" className="size-11" aria-label="Menu">
          <Menu className="size-5" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" showCloseButton={false} className="safe-area-p gap-4 bg-sidebar">
        <div className="flex items-center justify-between gap-2">
          <SheetTitle asChild>
            <Brand />
          </SheetTitle>
          <SheetClose asChild>
            <Button variant="ghost" className="size-11" aria-label="Close menu">
              <X className="size-5" />
            </Button>
          </SheetClose>
        </div>
        <SheetDescription className="sr-only">Go to a page</SheetDescription>
        <NavLinks current={current} onNavigate={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  )
}
