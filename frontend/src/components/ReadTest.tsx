import { useEffect, useState } from 'react'
import { Camera, Check, CircleAlert, LoaderCircle, Move, RotateCcw, X } from 'lucide-react'
import { type DeviceCapture, type Overlay, type ReadResult, readDial } from '@/api/client'
import { LibraryButton } from '@/components/LibraryButton'
import { LiveCamera } from '@/components/LiveCamera'
import { type HandRole, type HandTips, type PhotoPoint, PhotoOverlay } from '@/components/PhotoOverlay'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { errorText, formatDialTime, formatSignedSeconds, formatWallTime } from '@/lib/format'
import type { CapturedFrame } from '@/lib/frame'
import { detectPlatform } from '@/lib/platform'
import { cn } from '@/lib/utils'

type Photo = { file: File; url: string; device?: DeviceCapture }

// Where a hand's handle starts when the server found no such hand: clock angle and length as a
// fraction of the dial ring (a rough guess; the user drags it into place).
const DEFAULT_TIP: Record<HandRole, [number, number]> = {
  hour: [300, 0.45],
  minute: [60, 0.75],
  second: [180, 0.8],
}

/** Start the handles at the detected hands, or at defaults for hands that weren't found. */
function initialTips(overlay: Overlay): HandTips {
  const found = (role: HandRole) => overlay.hands.find((h) => h.role === role)?.tip
  const fallback = (role: HandRole): PhotoPoint => {
    const [angle, length] = DEFAULT_TIP[role]
    const a = (angle * Math.PI) / 180
    const r = length * overlay.dial_semi_major
    return { x: overlay.pivot.x + r * Math.sin(a), y: overlay.pivot.y - r * Math.cos(a) }
  }
  return {
    hour: found('hour') ?? fallback('hour'),
    minute: found('minute') ?? fallback('minute'),
    second: found('second') ?? fallback('second'),
  }
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{children}</dd>
    </>
  )
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
            <Row label="Photo taken">
              {formatWallTime(Date.parse(result.reference_time_utc), result.reference_utc_offset_minutes)}{' '}
              <span className="text-muted-foreground">
                ({result.reference_source === 'exif' ? 'photo EXIF' : 'phone clock'})
              </span>
            </Row>
          )}
          {r && (
            <Row label="Confidence">
              {Math.round(r.confidence * 100)} %, seconds {Math.round(r.seconds_confidence * 100)} %
            </Row>
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
  const [cameraOpen, setCameraOpen] = useState(false)
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

  function start(file: File, device?: DeviceCapture) {
    setPhoto({ file, url: URL.createObjectURL(file), device })
    setCameraOpen(false)
    setTap(null)
    setResult(null)
    setError(null)
    setTips(null)
  }

  function fromFrame(frame: CapturedFrame) {
    const file = new File([frame.blob], `frame-${frame.captureTime.getTime()}.jpg`, {
      type: frame.blob.type,
    })
    start(file, { captureTime: frame.captureTime, timing: frame.timing, platform: detectPlatform() })
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

  function reset() {
    setPhoto(null)
    setTap(null)
    setResult(null)
    setError(null)
    setTips(null)
  }

  const canCorrect = Boolean(result?.overlay && tap)

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="font-heading text-2xl font-semibold">Read the dial</h1>
        <p className="text-sm text-muted-foreground">
          {tips
            ? 'Drag each colored dot onto its hand (anywhere along it; only the direction counts). Zoom in for the seconds.'
            : photo
              ? result
                ? 'Tap 12 o\'clock again to re-read, correct the hands, or take a new photo.'
                : 'Tap the 12 o\'clock marker on the photo.'
              : 'Take a photo of the watch, filling most of the frame, then tap 12 o\'clock.'}
        </p>
      </header>

      {!photo &&
        (cameraOpen ? (
          <LiveCamera disabled={false} onClose={() => setCameraOpen(false)} onCapture={fromFrame} />
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button size="touch" onClick={() => setCameraOpen(true)}>
              <Camera /> Open camera
            </Button>
            <LibraryButton disabled={false} onFile={(f) => start(f)} />
          </div>
        ))}

      {photo && (
        <>
          <PhotoOverlay
            src={photo.url}
            tap={tap}
            overlay={result?.overlay ?? null}
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
                  setTips((t) =>
                    t && (t.second ? { ...t, second: null } : { ...t, second: initialTips(result!.overlay!).second }),
                  )
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
              {canCorrect && (
                <Button
                  size="touch"
                  variant={result.reading?.needs_confirmation || !result.reading ? 'default' : 'outline'}
                  onClick={() => setTips(initialTips(result.overlay!))}
                >
                  <Move /> {result.reading ? 'Correct the hands' : 'Place the hands yourself'}
                </Button>
              )}
            </>
          )}
          <Button size="touch" variant="outline" onClick={reset} disabled={busy}>
            <RotateCcw /> New photo
          </Button>
        </>
      )}
    </div>
  )
}
