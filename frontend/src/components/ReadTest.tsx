import { useEffect, useState } from 'react'
import { Check, CircleAlert, LoaderCircle, Move, RotateCcw, X } from 'lucide-react'
import {
  type DeviceCapture,
  type HandTips,
  type PhotoPoint,
  type ReadResult,
  type TypedTime,
  readDial,
} from '@/api/client'
import { CapturePicker } from '@/components/CapturePicker'
import { DefinitionRow } from '@/components/DefinitionRow'
import { PhotoOverlay } from '@/components/PhotoOverlay'
import { TypedTimeForm } from '@/components/TypedTimeForm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { errorText, formatDialTime, formatSignedSeconds, formatWallTime } from '@/lib/format'
import { type CapturedFrame, frameDevice, frameToFile } from '@/lib/frame'
import { initialTip, initialTips } from '@/lib/hands'
import { typedTimePlaceholders } from '@/lib/typed-time'
import { cn } from '@/lib/utils'

type Photo = { file: File; url: string; device?: DeviceCapture }

/** Viewing the photo and reading, or dragging the hands into place. */
type Mode = { kind: 'view' } | { kind: 'hands'; tips: HandTips }

const BADGE = { hands: 'hands placed by you', typed: 'typed by you' } as const

/** What to tell the user to do next. */
function instruction(photo: Photo | null, result: ReadResult | null, mode: Mode): string {
  if (mode.kind === 'hands') {
    return 'Drag each colored dot onto its hand (anywhere along it; only the direction counts). Zoom in for the seconds.'
  }
  if (!photo) return "Take a photo of the watch, filling most of the frame, then tap 12 o'clock."
  if (!result) return "Tap the 12 o'clock marker on the photo, or type the time below."
  return "Tap 12 o'clock again to re-read, correct the hands, or type the time below."
}

function Result({ result }: { result: ReadResult }) {
  const r = result.reading
  const deviation = result.deviation_s
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {r ? (
            <span className="font-heading text-3xl tabular-nums">
              {formatDialTime(r.hours, r.minutes, r.seconds)}
            </span>
          ) : (
            <>
              <CircleAlert className="text-destructive" /> Couldn't read the dial
            </>
          )}
          {r?.needs_confirmation && <Badge variant="destructive">check this reading</Badge>}
          {r?.correction && <Badge variant="secondary">{BADGE[r.correction]}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {result.reading_error && <p className="text-destructive">{result.reading_error}</p>}
        {result.timestamp_error && <p className="text-destructive">{result.timestamp_error}</p>}

        {deviation !== null && (
          <p className={cn('text-2xl font-semibold tabular-nums', deviation >= 0 ? 'text-fast' : 'text-slow')}>
            {formatSignedSeconds(deviation)}{' '}
            <span className="text-base font-normal">{deviation >= 0 ? 'fast' : 'slow'}</span>
          </p>
        )}
        {r && r.seconds === null && (
          <p className="text-muted-foreground">
            The seconds couldn't be read reliably, so there's no deviation for this photo.
          </p>
        )}

        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          {result.reference_time_utc && result.reference_utc_offset_minutes !== null && (
            <DefinitionRow label="Photo taken">
              {formatWallTime(Date.parse(result.reference_time_utc), result.reference_utc_offset_minutes)}{' '}
              <span className="text-muted-foreground">
                ({result.reference_source === 'exif' ? 'photo EXIF' : 'phone clock'})
              </span>
            </DefinitionRow>
          )}
          {r && r.correction !== 'typed' && (
            <DefinitionRow label="Confidence">
              {Math.round(r.confidence * 100)} %, seconds {Math.round(r.seconds_confidence * 100)} %
            </DefinitionRow>
          )}
        </dl>

        {r && r.reasons.length > 0 && (
          <ul className="list-disc pl-5 text-muted-foreground">
            {r.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        {r && result.overlay && (
          <p className="text-muted-foreground">
            Drawn on the photo: <span className="text-overlay-hour">hour</span>,{' '}
            <span className="text-overlay-minute">minute</span>,{' '}
            <span className="text-overlay-second">seconds</span>.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

/** Take or pick a photo, tap 12 o'clock, and see what the backend reads. Persists nothing. */
export function ReadTest() {
  const [photo, setPhoto] = useState<Photo | null>(null)
  const [tap, setTap] = useState<PhotoPoint | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ReadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>({ kind: 'view' })

  const url = photo?.url
  useEffect(() => {
    if (!url) return
    return () => URL.revokeObjectURL(url)
  }, [url])

  /** Back to the start, with a new photo or none. */
  function reset(next: Photo | null = null) {
    setPhoto(next)
    setTap(null)
    setResult(null)
    setError(null)
    setMode({ kind: 'view' })
  }

  function start(file: File, device?: DeviceCapture) {
    reset({ file, url: URL.createObjectURL(file), device })
  }

  function fromFrame(frame: CapturedFrame) {
    start(frameToFile(frame), frameDevice(frame))
  }

  /** Send the photo with a tap (and placed hands), or with a typed time. */
  async function read(point: PhotoPoint | null, hands?: HandTips, typed?: TypedTime) {
    if (!photo || busy) return
    if (point) setTap(point)
    setBusy(true)
    setError(null)
    try {
      setResult(await readDial(photo.file, point, photo.device, hands, typed))
      setMode({ kind: 'view' })
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  // The overlay the hands are placed on: the dial was found (with or without a reading).
  const overlay = result?.overlay ?? null
  const tips = mode.kind === 'hands' ? mode.tips : null

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
      <p className="text-sm text-muted-foreground">{instruction(photo, result, mode)}</p>

      {!photo && <CapturePicker onFrame={fromFrame} onFile={(f) => start(f)} />}

      {photo && (
        <>
          <PhotoOverlay
            src={photo.url}
            tap={tap}
            overlay={overlay}
            onTap={(point) => void read(point)}
            tips={tips}
            onMoveTip={(role, point) =>
              setMode((m) => (m.kind === 'hands' ? { ...m, tips: { ...m.tips, [role]: point } } : m))
            }
          />
          {tips && tap && (
            <div className="flex flex-wrap gap-2">
              <Button size="touch" onClick={() => void read(tap, tips)} disabled={busy}>
                <Check /> Read with these hands
              </Button>
              <Button
                size="touch"
                variant="outline"
                onClick={() => {
                  if (!overlay) return
                  const second = tips.second ? null : initialTip(overlay, 'second')
                  setMode({ kind: 'hands', tips: { ...tips, second } })
                }}
              >
                {tips.second ? 'No seconds hand' : 'Add seconds hand'}
              </Button>
              <Button
                size="touch"
                variant="ghost"
                onClick={() => setMode({ kind: 'view' })}
                aria-label="Stop correcting"
              >
                <X />
              </Button>
            </div>
          )}
          {busy && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="animate-spin" /> Reading the dial…
            </p>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {result && !busy && mode.kind === 'view' && <Result result={result} />}
          {mode.kind === 'view' && (
            <TypedTimeForm
              key={photo.url}
              placeholders={typedTimePlaceholders(result)}
              busy={busy}
              onSubmit={(typed) => void read(null, undefined, typed)}
            />
          )}
          {!busy && mode.kind === 'view' && (
            <div className="flex flex-wrap gap-2">
              {result && overlay && tap && (
                <Button
                  size="touch"
                  variant={result.reading?.needs_confirmation || !result.reading ? 'default' : 'outline'}
                  onClick={() => setMode({ kind: 'hands', tips: initialTips(overlay) })}
                >
                  <Move /> {result.reading ? 'Correct the hands' : 'Place the hands'}
                </Button>
              )}
              <Button size="touch" variant="outline" onClick={() => reset()}>
                <RotateCcw /> New photo
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
