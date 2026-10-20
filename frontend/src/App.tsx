import { useEffect, useState } from 'react'
import { CaptureProbe } from '@/components/CaptureProbe'
import { ReadTest } from '@/components/ReadTest'
import { ReferenceClock } from '@/components/ReferenceClock'

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const update = () => setHash(window.location.hash)
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return hash
}

const PAGES = [
  { hash: '', label: 'Read dial' },
  { hash: '#probe', label: 'Timestamp check' },
  { hash: '#clock', label: 'Reference clock' },
]

export default function App() {
  const hash = useHash()
  if (hash === '#clock') {
    return (
      <main className="safe-area-p min-h-svh bg-background">
        <ReferenceClock />
      </main>
    )
  }
  return (
    <main className="safe-area-p flex min-h-svh flex-col gap-6 bg-background">
      {hash === '#probe' ? <CaptureProbe /> : <ReadTest />}
      <nav className="mx-auto flex max-w-xl flex-wrap gap-x-4 text-sm text-muted-foreground">
        {PAGES.map((page) => (
          <a
            key={page.hash}
            href={page.hash || '#'}
            className={page.hash === hash || (!page.hash && hash === '') ? 'text-foreground' : 'underline'}
          >
            {page.label}
          </a>
        ))}
      </nav>
    </main>
  )
}
