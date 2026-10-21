import { useEffect, useState } from 'react'
import { Check, CircleAlert, LoaderCircle, Move, RotateCcw, X } from 'lucide-react'
import { type DeviceCapture, type HandTips, type PhotoPoint, type ReadResult, readDial } from '@/api/client'
import { CapturePicker } from '@/components/CapturePicker'
import { DefinitionRow } from '@/components/DefinitionRow'
import { PhotoOverlay } from '@/components/PhotoOverlay'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { errorText, formatDialTime, formatSignedSeconds, formatWallTime } from '@/lib/format'
import { type CapturedFrame, frameDevice, frameToFile } from '@/lib/frame'
import { initialTip, initialTips } from '@/lib/hands'
import { cn } from '@/lib/utils'

type Photo = { file: File; url: string; device?: DeviceCapture }

/** What to tell the user to do next. */
function instruction(photo: Photo | null, result: ReadResult | null, correcting: boolean): string {
  if (correcting) {
    return 'Drag each colored dot onto its hand (anywhere along it; only the direction counts). Zoom in for the seconds.'
  }
  if (!photo) return "Take a photo of the watch, filling most of the frame, then tap 12 o'clock."
  if (!result) return "Tap the 12 o'clock marker on the photo."
  return "Tap 12 o'clock again to re-read, correct the hands, or take a new photo."
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
          {r?.corrected && <Badge variant="secondary">hands placed by you</Badge>}
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
          {r && (
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
        {r && (
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
  // Non-null while the user drags the hands into place.
  const [tips, setTips] = useState<HandTips | null>(null)

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
    setTips(null)
  }

  function start(file: File, device?: DeviceCapture) {
    reset({ file, url: URL.createObjectURL(file), device })
  }

  function fromFrame(frame: CapturedFrame) {
    start(frameToFile(frame), frameDevice(frame))
  }

  async function read(point: PhotoPoint, hands?: HandTips) {
    if (!photo || busy) return
    setTap(point)
    setBusy(true)
    setError(null)
    try {
      setResult(await readDial(photo.file, point, photo.device, hands))
      setTips(null)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  // The overlay the hands are placed on: the dial was found (with or without a reading).
  const overlay = result?.overlay ?? null

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="font-heading text-2xl font-semibold">Read the dial</h1>
        <p className="text-sm text-muted-foreground">{instruction(photo, result, tips !== null)}</p>
      </header>

      {!photo && <CapturePicker onFrame={fromFrame} onFile={(f) => start(f)} />}

      {photo && (
        <>
          <PhotoOverlay
            src={photo.url}
            tap={tap}
            overlay={overlay}
            onTap={(point) => void read(point)}
            tips={tips}
            onMoveTip={(role, point) => setTips((t) => (t ? { ...t, [role]: point } : t))}
          />
          {tips && tap && (
            <div className="flex flex-wrap gap-2">
              <Button size="touch" onClick={() => void read(tap, tips)} disabled={busy}>
                <Check /> Read with these hands
              </Button>
              <Button
                size="touch"
                variant="outline"
                onClick={() =>
                  setTips((t) => {
                    if (!t || !overlay) return t
                    return { ...t, second: t.second ? null : initialTip(overlay, 'second') }
                  })
                }
              >
                {tips.second ? 'No seconds hand' : 'Add seconds hand'}
              </Button>
              <Button size="touch" variant="ghost" onClick={() => setTips(null)} aria-label="Stop correcting">
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
          {result && !busy && !tips && (
            <>
              <Result result={result} />
              {overlay && tap && (
                <Button
                  size="touch"
                  variant={result.reading?.needs_confirmation || !result.reading ? 'default' : 'outline'}
                  onClick={() => setTips(initialTips(overlay))}
                >
                  <Move /> {result.reading ? 'Correct the hands' : 'Place the hands yourself'}
                </Button>
              )}
            </>
          )}
          <Button size="touch" variant="outline" onClick={() => reset()} disabled={busy}>
            <RotateCcw /> New photo
          </Button>
        </>
      )}
    </div>
  )
}
