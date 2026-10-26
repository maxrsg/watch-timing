import { useEffect, useState } from 'react'
import { AppMenu } from '@/components/AppMenu'
import { CaptureProbe } from '@/components/CaptureProbe'
import { ReadTest } from '@/components/ReadTest'
import { ReferenceClock } from '@/components/ReferenceClock'
import { pageFor } from '@/lib/pages'

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const update = () => setHash(window.location.hash)
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return hash
}

export default function App() {
  const page = pageFor(useHash())
  if (page.hash === '#clock') {
    // Full-bleed for photographing; the menu stays out of the way in a corner.
    return (
      <main className="safe-area-p relative min-h-svh bg-background">
        <div className="absolute top-2 left-2">
          <AppMenu current={page.hash} />
        </div>
        <ReferenceClock />
      </main>
    )
  }
  return (
    <main className="safe-area-p flex min-h-svh flex-col gap-2 bg-background">
      <header className="mx-auto flex w-full max-w-xl items-center gap-1">
        <div className="-ml-3">
          <AppMenu current={page.hash} />
        </div>
        <h1 className="font-heading text-xl font-semibold">{page.label}</h1>
      </header>
      {page.hash === '#probe' ? <CaptureProbe /> : <ReadTest />}
    </main>
  )
}
