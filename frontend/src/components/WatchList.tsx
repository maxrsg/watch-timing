import { useEffect, useState } from 'react'
import { ChevronRight, Copy, LoaderCircle, Plus } from 'lucide-react'
import { type WatchSummary, createWatch, listWatches } from '@/api/client'
import { RateText } from '@/components/RateText'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { errorText, formatSignedSeconds } from '@/lib/format'
import { ownerLink } from '@/lib/owner'
import { watchHash } from '@/lib/pages'

/** Opens these watches in another browser: there's no login, the link carries the owner ID. */
function OwnerLink() {
  const [copied, setCopied] = useState(false)
  const link = ownerLink()
  return (
    <div className="flex flex-col gap-2 text-sm text-muted-foreground">
      <p>
        Your watches are tied to this browser. To open them on another device, copy this link there.
        Anyone with the link can see and change them.
      </p>
      <Button
        size="touch"
        variant="outline"
        onClick={() =>
          void navigator.clipboard.writeText(link).then(
            () => setCopied(true),
            () => window.prompt('Copy this link:', link),
          )
        }
      >
        <Copy /> {copied ? 'Link copied' : 'Copy link to my watches'}
      </Button>
    </div>
  )
}

function NewWatchForm({ onCreated }: { onCreated: (watch: WatchSummary) => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <form
      className="flex flex-col gap-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        if (!name.trim() || busy) return
        setBusy(true)
        setError(null)
        createWatch(name)
          .then((watch) => {
            setName('')
            onCreated(watch)
          })
          .catch((err) => setError(errorText(err)))
          .finally(() => setBusy(false))
      }}
    >
      <Label htmlFor="new-watch">Add a watch</Label>
      <div className="flex gap-2">
        <Input
          id="new-watch"
          className="h-11"
          placeholder="e.g. Orient Ray II"
          maxLength={80}
          autoComplete="off"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button type="submit" size="touch" disabled={busy || !name.trim()}>
          <Plus /> Add
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </form>
  )
}

function WatchCard({ watch }: { watch: WatchSummary }) {
  const latest = watch.latest_deviation_s
  return (
    <a href={watchHash(watch.id)} className="block rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50">
      <Card className="hover:bg-muted">
        <CardContent className="flex min-h-11 items-center gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate font-medium">{watch.name}</span>
            <span className="text-sm text-muted-foreground tabular-nums">
              {watch.measurement_count === 1 ? '1 measurement' : `${watch.measurement_count} measurements`}
              {latest !== null && ` · last ${formatSignedSeconds(latest)}`}
            </span>
          </div>
          <RateText rate={watch.rate} className="text-lg" />
          <ChevronRight className="size-5 text-muted-foreground" />
        </CardContent>
      </Card>
    </a>
  )
}

/** The watches this browser owns, with their current rate, and adding one. */
export function WatchList() {
  const [watches, setWatches] = useState<WatchSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listWatches()
      .then(setWatches)
      .catch((e) => setError(errorText(e)))
  }, [])

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!watches && !error && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="animate-spin" /> Loading watches…
        </p>
      )}
      {watches && watches.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Add a watch, then save readings to it to see how fast or slow it runs.
        </p>
      )}
      {watches && watches.length > 0 && (
        <div className="flex flex-col gap-2">
          {watches.map((w) => (
            <WatchCard key={w.id} watch={w} />
          ))}
        </div>
      )}
      <NewWatchForm onCreated={(w) => setWatches((ws) => [...(ws ?? []), w])} />
      {watches && watches.length > 0 && <OwnerLink />}
    </div>
  )
}
