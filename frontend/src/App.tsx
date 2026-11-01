import { useEffect, useState } from 'react'
import { AppMenu } from '@/components/AppMenu'
import { Brand, NavLinks } from '@/components/NavLinks'
import { ReadTest } from '@/components/ReadTest'
import { WatchDetail } from '@/components/WatchDetail'
import { WatchList } from '@/components/WatchList'
import { adoptOwner } from '@/lib/owner'
import { pageFor, parseHash, savedMeasurementFor, watchIdFor } from '@/lib/pages'

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
  if (page.hash === '#watches') {
    const id = watchIdFor(hash)
    return id === null ? <WatchList /> : <WatchDetail key={id} id={id} saved={savedMeasurementFor(hash)} />
  }
  return <ReadTest />
}

/**
 * A drawer and top bar on phones; a sidebar on desktops, where the app is exactly the screen
 * height and only the main area (or a column in it) scrolls.
 */
export default function App() {
  const hash = useHash()
  const page = pageFor(hash)
  return (
    <div className="flex min-h-svh lg:h-svh lg:overflow-hidden">
      <aside className="safe-area-p hidden w-64 shrink-0 flex-col gap-8 border-r border-sidebar-border bg-sidebar lg:flex">
        <Brand className="px-1 pt-2" />
        <NavLinks current={page.hash} />
      </aside>
      <main className="safe-area-p flex min-w-0 flex-1 flex-col gap-4 lg:min-h-0 lg:gap-8 lg:overflow-y-auto lg:px-10 lg:py-8">
        <header className="mx-auto flex w-full max-w-6xl shrink-0 items-center gap-1 border-b border-primary/20 pb-2 lg:pb-4">
          <div className="-ml-3 lg:hidden">
            <AppMenu current={page.hash} />
          </div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight lg:text-3xl">{page.label}</h1>
        </header>
        <Page hash={hash} />
      </main>
    </div>
  )
}
