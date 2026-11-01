import { useEffect, useState } from 'react'
import { AppMenu } from '@/components/AppMenu'
import { CaptureProbe } from '@/components/CaptureProbe'
import { ReadTest } from '@/components/ReadTest'
import { ReferenceClock } from '@/components/ReferenceClock'
import { WatchDetail } from '@/components/WatchDetail'
import { WatchList } from '@/components/WatchList'
import { adoptOwner } from '@/lib/owner'
import { pageFor, parseHash, watchIdFor } from '@/lib/pages'

/** An owner link ("#watches?owner=<id>") hands this browser the watches; the ID then leaves the URL. */
function takeOwnerFromHash(): string {
  const { base, query } = parseHash(window.location.hash)
  const owner = query.get('owner')
  if (base === '#watches' && owner) {
    adoptOwner(owner)
    history.replaceState(null, '', '#watches')
  }
  return window.location.hash
}

function useHash(): string {
  const [hash, setHash] = useState(takeOwnerFromHash)
  useEffect(() => {
    const update = () => setHash(takeOwnerFromHash())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return hash
}

function Page({ hash }: { hash: string }) {
  const page = pageFor(hash)
  if (page.hash === '#probe') return <CaptureProbe />
  if (page.hash === '#watches') {
    const id = watchIdFor(hash)
    return id === null ? <WatchList /> : <WatchDetail key={id} id={id} />
  }
  return <ReadTest />
}

export default function App() {
  const hash = useHash()
  const page = pageFor(hash)
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
      <Page hash={hash} />
    </main>
  )
}
