import { useEffect, useState } from 'react'
import { CaptureProbe } from '@/components/CaptureProbe'
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

export default function App() {
  const hash = useHash()
  return (
    <main className="safe-area-p min-h-svh bg-background">
      {hash === '#clock' ? <ReferenceClock /> : <CaptureProbe />}
    </main>
  )
}
