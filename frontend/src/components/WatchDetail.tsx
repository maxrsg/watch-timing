import { type ReactNode, useEffect, useState } from 'react'
import { ArrowLeft, CircleCheck, LoaderCircle, Pencil, RotateCcw, ScanEye, Trash2, X } from 'lucide-react'
import {
  type SavedMeasurement,
  type Session,
  type WatchDetail as Watch,
  deleteMeasurement,
  deleteWatch,
  getWatch,
  renameWatch,
  startSession,
} from '@/api/client'
import { DeviationChart } from '@/components/DeviationChart'
import { RateText } from '@/components/RateText'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  errorText,
  fastOrSlow,
  fastSlowClass,
  formatDateTime,
  formatDialTime,
  formatSignedSeconds,
  sourceLabel,
} from '@/lib/format'
import { rememberWatch } from '@/lib/last-watch'
import { watchHash } from '@/lib/pages'
import { rateNotes } from '@/lib/rate'
import { cn } from '@/lib/utils'

const CORRECTION = { hands: 'hands placed', typed: 'typed' } as const

/**
 * A dialog asking to confirm an action; `onConfirm` runs, then the dialog closes. If it fails,
 * the dialog stays open with the error, where the user is looking.
 */
function ConfirmDialog({
  trigger,
  title,
  description,
  confirm,
  destructive = false,
  onConfirm,
}: {
  trigger: ReactNode
  title: string
  description: string
  confirm: string
  destructive?: boolean
  onConfirm: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        setError(null)
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <DialogClose asChild>
            <Button size="touch" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button
            size="touch"
            variant={destructive ? 'destructive' : 'default'}
            disabled={busy}
            onClick={() => {
              setBusy(true)
              setError(null)
              onConfirm()
                .then(() => setOpen(false))
                .catch((e: unknown) => setError(errorText(e)))
                .finally(() => setBusy(false))
            }}
          >
            {confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RenameDialog({ watch, onRenamed }: { watch: Watch; onRenamed: (name: string) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(watch.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        setName(watch.name)
        setError(null)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" className="size-11" aria-label="Rename watch">
          <Pencil className="size-5" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (busy) return
            setBusy(true)
            setError(null)
            renameWatch(watch.id, name)
              .then((w) => {
                onRenamed(w.name)
                setOpen(false)
              })
              .catch((err) => setError(errorText(err)))
              .finally(() => setBusy(false))
          }}
        >
          <DialogHeader>
            <DialogTitle>Rename watch</DialogTitle>
            <DialogDescription className="sr-only">Give the watch a new name.</DialogDescription>
          </DialogHeader>
          <Input
            className="h-11"
            maxLength={80}
            autoComplete="off"
            aria-label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" size="touch" disabled={busy || !name.trim()}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function MeasurementTable({
  session,
  highlight,
  onDelete,
}: {
  session: Session
  highlight: number | null
  onDelete: (id: number) => Promise<void>
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Taken</TableHead>
          <TableHead>Dial</TableHead>
          <TableHead className="text-right">Deviation</TableHead>
          <TableHead>
            <span className="sr-only">Delete</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {session.measurements.map((m) => (
          <TableRow key={m.id} className={cn(m.id === highlight && 'bg-primary/10 hover:bg-primary/15')}>
            <TableCell>
              <div className="flex flex-col">
                <span className="tabular-nums">{formatDateTime(Date.parse(m.reference_time_utc))}</span>
                <span className="text-xs text-muted-foreground">{sourceLabel(m.source_key)}</span>
              </div>
            </TableCell>
            <TableCell>
              <div className="flex flex-col items-start gap-0.5">
                <span className="tabular-nums">{formatDialTime(m.hours, m.minutes, m.seconds)}</span>
                {m.correction && <Badge variant="secondary">{CORRECTION[m.correction]}</Badge>}
              </div>
            </TableCell>
            <TableCell
              className={cn('text-right font-medium tabular-nums', fastSlowClass(m.deviation_s))}
            >
              {formatSignedSeconds(m.deviation_s)}
            </TableCell>
            <TableCell className="w-11 p-0">
              <ConfirmDialog
                trigger={
                  <Button variant="ghost" className="size-11" aria-label="Delete measurement">
                    <Trash2 className="size-4 text-muted-foreground" />
                  </Button>
                }
                title="Delete this measurement?"
                description="It no longer counts toward the rate. This can't be undone."
                confirm="Delete"
                destructive
                onConfirm={() => onDelete(m.id)}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function SessionCard({
  session,
  current,
  highlight = null,
  onDelete,
}: {
  session: Session
  current: boolean
  highlight?: number | null
  onDelete: (id: number) => Promise<void>
}) {
  const notes = rateNotes(session.rate, session.measurements.length)
  return (
    <Card>
      <CardContent className="flex flex-col gap-6">
        {/* Desktops: the rate beside the chart. */}
        <div className="flex flex-col gap-4 lg:grid lg:grid-cols-3 lg:gap-8">
          <div className="flex flex-col gap-2">
            <CardDescription>
              {current ? 'Since set' : 'Set'} {formatDateTime(Date.parse(session.started_at))}
              {session.rate &&
                ` · ${session.rate.n} measurements over ${(session.rate.span_hours / 24).toFixed(1)} d`}
            </CardDescription>
            <CardTitle>
              <RateText
                rate={session.rate}
                className={session.rate ? 'font-heading text-4xl lg:text-5xl' : 'text-base font-normal'}
              />
            </CardTitle>
            {notes.length > 0 && (
              <ul className="flex flex-col gap-0.5 text-sm text-muted-foreground">
                {notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
          </div>
          {session.measurements.length > 0 && (
            <div className="lg:col-span-2">
              <DeviationChart session={session} />
            </div>
          )}
        </div>
        {session.measurements.length > 0 && (
          <MeasurementTable session={session} highlight={highlight} onDelete={onDelete} />
        )}
      </CardContent>
    </Card>
  )
}

/** Confirms the measurement just saved from the Read dial page. */
function SavedNotice({
  watch,
  measurement,
  onDismiss,
}: {
  watch: Watch
  measurement: SavedMeasurement
  onDismiss: () => void
}) {
  const tone = fastOrSlow(measurement.deviation_s)
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/30 bg-primary/10 p-3 pl-4">
      <CircleCheck className="size-5 shrink-0 text-primary" />
      <p className="min-w-0 flex-1">
        Saved to {watch.name}:{' '}
        <span className={cn('font-semibold tabular-nums', fastSlowClass(measurement.deviation_s))}>
          {formatSignedSeconds(measurement.deviation_s)}
          {tone && ` ${tone}`}
        </span>
      </p>
      <div className="flex gap-1">
        <Button size="touch" variant="outline" asChild>
          <a href="#" onClick={() => rememberWatch(watch.id)}>
            <ScanEye /> Measure again
          </a>
        </Button>
        <Button variant="ghost" className="size-11" aria-label="Dismiss" onClick={onDismiss}>
          <X className="size-5" />
        </Button>
      </div>
    </div>
  )
}

/** One watch: its current session's rate, chart and measurements, and earlier sessions. */
export function WatchDetail({ id, saved = null }: { id: number; saved?: number | null }) {
  const [watch, setWatch] = useState<Watch | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [justSaved, setJustSaved] = useState(saved)

  useEffect(() => {
    getWatch(id)
      .then(setWatch)
      .catch((e) => setError(errorText(e)))
  }, [id])

  useEffect(() => {
    // The notice is for arriving from a save; a reload or a shared link shouldn't show it again.
    if (saved !== null) history.replaceState(null, '', watchHash(id))
  }, [id, saved])

  // Confirmed actions throw on failure: the confirm dialog shows the error.
  async function removeMeasurement(mid: number) {
    await deleteMeasurement(id, mid)
    setWatch(await getWatch(id))
  }

  if (!watch) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <a href="#watches" className="flex min-h-11 items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft className="size-4" /> All watches
        </a>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="animate-spin" /> Loading…
          </p>
        )}
      </div>
    )
  }

  const [current, ...earlier] = watch.sessions
  const savedMeasurement = current?.measurements.find((m) => m.id === justSaved) ?? null
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 lg:gap-6">
      <a href="#watches" className="flex min-h-11 items-center gap-2 text-sm text-muted-foreground">
        <ArrowLeft className="size-4" /> All watches
      </a>
      <div className="flex items-center gap-1">
        <h2 className="min-w-0 flex-1 truncate font-heading text-3xl font-semibold tracking-tight lg:text-4xl">
          {watch.name}
        </h2>
        <RenameDialog watch={watch} onRenamed={(name) => setWatch({ ...watch, name })} />
        <ConfirmDialog
          trigger={
            <Button variant="ghost" className="size-11" aria-label="Delete watch">
              <Trash2 className="size-5" />
            </Button>
          }
          title={`Delete ${watch.name}?`}
          description="All its measurements are deleted too. This can't be undone."
          confirm="Delete watch"
          destructive
          onConfirm={async () => {
            await deleteWatch(id)
            window.location.hash = '#watches'
          }}
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {savedMeasurement && (
        <SavedNotice watch={watch} measurement={savedMeasurement} onDismiss={() => setJustSaved(null)} />
      )}

      <div className="flex flex-wrap gap-2">
        <Button size="touch" asChild>
          <a href="#" onClick={() => rememberWatch(id)}>
            <ScanEye /> Measure now
          </a>
        </Button>
        <ConfirmDialog
          trigger={
            <Button size="touch" variant="outline">
              <RotateCcw /> I set the watch
            </Button>
          }
          title="Did you set the watch?"
          description="Setting the watch starts a new series: the rate starts over, and earlier measurements stay below."
          confirm="Start a new series"
          onConfirm={async () => setWatch(await startSession(id))}
        />
      </div>

      {current && (
        <SessionCard session={current} current highlight={savedMeasurement?.id} onDelete={removeMeasurement} />
      )}
      {earlier.length > 0 && <h3 className="font-heading text-xl font-semibold">Earlier series</h3>}
      {earlier.map((s) => (
        <SessionCard key={s.id} session={s} current={false} onDelete={removeMeasurement} />
      ))}
    </div>
  )
}
