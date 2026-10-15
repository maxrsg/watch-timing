import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { type ClockSample, measureClockOffset } from '@/lib/clock'
import { errorText, formatSignedMs } from '@/lib/format'

const SLOT_MS = 50
const SLOTS = 1000 / SLOT_MS

/**
 * Open on a computer and photograph it with the phone: the time visible in the photo,
 * minus the phone's recorded capture time, is the in-app camera's timing error.
 * Shows server time (the same clock the phone's offset is measured against).
 *
 * Changing digits blur during the camera's exposure (~1/30 s), so sub-second time is
 * shown as two rows of 10 slots that light up one at a time; the labels never change. A photo
 * shows one or two lit slots, and the middle of the lit area is the capture moment.
 */
export function ReferenceClock() {
  const [sample, setSample] = useState<ClockSample | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    measureClockOffset(10).then(setSample, (e: unknown) => setError(errorText(e)))
    let frame = requestAnimationFrame(function tick() {
      setNow(Date.now())
      frame = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(frame)
  }, [])

  const serverNow = sample ? now + sample.offsetMs : null
  const activeSlot = serverNow === null ? -1 : Math.floor((serverNow % 1000) / SLOT_MS)

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col items-center justify-center gap-8">
      <p className="font-mono text-8xl font-semibold tabular-nums sm:text-9xl">
        {serverNow === null ? '––:––:––' : new Date(serverNow).toISOString().slice(11, 19)}
      </p>

      <div className="grid w-full grid-cols-10 gap-2">
        {Array.from({ length: SLOTS }, (_, i) => (
          <div key={i} className="flex flex-col items-center gap-1">
            <div
              className={cn(
                'aspect-square w-full rounded-md',
                i === activeSlot ? 'bg-foreground' : 'bg-muted',
              )}
            />
            <span className="font-mono text-lg tabular-nums text-muted-foreground">
              .{String(i * SLOT_MS).padStart(3, '0')}
            </span>
          </div>
        ))}
      </div>

      <p className="text-center text-sm text-muted-foreground">
        {error
          ? `Could not reach the server: ${error}`
          : sample
            ? `Server time (UTC) · server vs this screen ${formatSignedMs(sample.offsetMs)} · ±${(sample.rttMs / 2).toFixed(0)} ms · each slot is ${SLOT_MS} ms`
            : 'Syncing with server…'}
      </p>
    </div>
  )
}
