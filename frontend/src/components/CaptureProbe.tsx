import { useEffect, useState } from 'react'
import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'
import { probe, type ProbeResult } from '@/api/client'
import { CapturePicker } from '@/components/CapturePicker'
import { DefinitionRow } from '@/components/DefinitionRow'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { type ClockSample, measureClockOffset } from '@/lib/clock'
import {
  type ClientExif,
  compareField,
  EXIF_FIELDS,
  type FieldStatus,
  readClientExif,
  sha256Hex,
} from '@/lib/exif'
import { errorText, formatSignedMs, formatSignedSeconds, formatUtcTime } from '@/lib/format'
import { type CapturedFrame, frameDevice, frameToFile } from '@/lib/frame'

type Source = 'live' | 'library'

type Run = {
  source: Source
  fileName: string
  fileType: string
  previewUrl: string
  selectedAt: Date
  /** Live camera only: frame metadata (timestamp, timing source, size). */
  frame: Omit<CapturedFrame, 'blob'> | null
  /** Device clock vs server, measured right after capture; error if it couldn't be measured. */
  clock: ClockSample | null
  clockError: string | null
  clientSha256: string
  clientExif: ClientExif | null
  clientError: string | null
  server: ProbeResult | null
  serverError: string | null
}

function StatusBadge({ status }: { status: FieldStatus }) {
  if (status === 'ok') return <Badge variant="secondary">ok</Badge>
  return <Badge variant="destructive">{status}</Badge>
}

export function CaptureProbe() {
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Each preview URL is released when it's replaced or the page unmounts.
  const previewUrl = run?.previewUrl
  useEffect(() => {
    if (!previewUrl) return
    return () => URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  async function handle(file: File, source: Source, frame?: CapturedFrame) {
    setBusy(true)
    setError(null)
    try {
      const selectedAt = new Date()
      // Before the heavy work: hashing/decoding a big image would delay the responses and
      // inflate the round trips.
      const clock = await measureClockOffset().then(
        (sample) => ({ sample, error: null }),
        (e: unknown) => ({ sample: null, error: errorText(e) }),
      )
      const [clientSha256, client] = await Promise.all([
        sha256Hex(file),
        readClientExif(file).then(
          (exif) => ({ exif, error: null }),
          (e: unknown) => ({ exif: null, error: errorText(e) }),
        ),
      ])
      let server: ProbeResult | null = null
      let serverError: string | null = null
      try {
        server = await probe(file, frame && frameDevice(frame))
      } catch (e) {
        serverError = errorText(e)
      }
      setRun({
        source,
        fileName: file.name,
        fileType: file.type,
        previewUrl: URL.createObjectURL(file),
        selectedAt,
        frame: frame
          ? {
              captureTime: frame.captureTime,
              timing: frame.timing,
              width: frame.width,
              height: frame.height,
            }
          : null,
        clock: clock.sample,
        clockError: clock.error,
        clientSha256,
        clientExif: client.exif,
        clientError: client.error,
        server,
        serverError,
      })
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const shaStatus: FieldStatus | null = run?.server
    ? compareField(run.clientSha256, run.server.sha256)
    : null
  const referenceMs = run?.server?.reference_time_utc
    ? Date.parse(run.server.reference_time_utc)
    : null
  const ok = referenceMs !== null && shaStatus === 'ok'

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Capture with the in-app camera (timestamped with the device clock), or pick a photo from
        the library (timestamped from EXIF). To measure the in-app camera's timing, open{' '}
        <a className="text-foreground underline" href="/#clock" target="_blank" rel="noreferrer">
          the reference clock
        </a>{' '}
        on a computer and photograph it.
      </p>

      <CapturePicker
        disabled={busy}
        onFrame={(frame) => handle(frameToFile(frame), 'live', frame)}
        onFile={(f) => handle(f, 'library')}
      />

      {error && <p className="text-sm text-destructive">{error}</p>}

      {busy && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="animate-spin" /> Reading and uploading…
        </p>
      )}

      {run && !busy && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {ok ? (
                  <>
                    <CircleCheck /> Reference time:{' '}
                    {run.server?.reference_source === 'exif' ? 'EXIF' : 'device clock'}
                  </>
                ) : (
                  <>
                    <CircleAlert className="text-destructive" /> Problem found
                  </>
                )}
              </CardTitle>
              <CardDescription className="break-all">
                {run.source === 'live' ? 'in-app camera' : 'library'} · {run.fileName} ·{' '}
                {run.fileType || 'unknown type'}
                {run.server && ` · ${run.server.format ?? '?'} · ${run.server.size} bytes`}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              <img src={run.previewUrl} alt="Captured photo" className="w-full rounded-md" />
              {run.clientError && <p className="text-destructive">Phone: {run.clientError}</p>}
              {run.serverError && <p className="text-destructive">Server: {run.serverError}</p>}
              {run.server?.error && <p className="text-destructive">{run.server.error}</p>}
              {run.server?.ignored_device_time && (
                <p className="text-destructive">
                  The server used EXIF and ignored the device time that was sent.
                </p>
              )}
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                {referenceMs !== null && (
                  <DefinitionRow label="Reference (UTC)">{formatUtcTime(referenceMs)}</DefinitionRow>
                )}
                {run.frame && (
                  <>
                    <DefinitionRow label="Frame timing">{run.frame.timing}</DefinitionRow>
                    {run.server?.platform && <DefinitionRow label="Platform">{run.server.platform}</DefinitionRow>}
                    {run.server?.reference_source === 'device_clock' && (
                      <DefinitionRow label="Latency correction">
                        {run.server.latency_correction_ms === null ? (
                          <Badge variant="destructive">uncalibrated</Badge>
                        ) : (
                          formatSignedMs(-run.server.latency_correction_ms)
                        )}
                      </DefinitionRow>
                    )}
                    <DefinitionRow label="Frame size">
                      {run.frame.width}×{run.frame.height}
                    </DefinitionRow>
                  </>
                )}
                <DefinitionRow label="Server vs phone clock">
                  {run.clock ? (
                    `${formatSignedMs(run.clock.offsetMs)} (±${(run.clock.rttMs / 2).toFixed(0)} ms)`
                  ) : (
                    <span className="text-destructive">unavailable: {run.clockError}</span>
                  )}
                </DefinitionRow>
                {/* Compare with the reference clock visible in the photo:
                    visible − raw = the camera's lag (use this to calibrate a new device);
                    visible − corrected = the error left after the correction (≈ 0 if calibrated). */}
                {run.frame && run.clock && (
                  <DefinitionRow label="Server time at capture (raw)">
                    {formatUtcTime(run.frame.captureTime.getTime() + run.clock.offsetMs)}
                  </DefinitionRow>
                )}
                {referenceMs !== null && run.clock && (
                  <DefinitionRow label={run.frame ? 'Server time at capture (corrected)' : 'Server time at capture'}>
                    {formatUtcTime(referenceMs + run.clock.offsetMs)}
                  </DefinitionRow>
                )}
                {referenceMs !== null && run.source === 'library' && (
                  <DefinitionRow label="Selected after capture">
                    {formatSignedSeconds((run.selectedAt.getTime() - referenceMs) / 1000)}
                  </DefinitionRow>
                )}
              </dl>
              {shaStatus && (
                <p className="flex items-center gap-2">
                  Bytes unchanged (SHA-256) <StatusBadge status={shaStatus} />
                </p>
              )}
            </CardContent>
          </Card>

          {run.source === 'library' && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tag</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Server</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {EXIF_FIELDS.map(([key, tag]) => {
                  const c = run.clientExif?.[key] ?? null
                  const s = run.server?.exif[key] ?? null
                  return (
                    <TableRow key={key}>
                      <TableCell className="font-medium">{tag}</TableCell>
                      <TableCell className="tabular-nums">{c ?? '—'}</TableCell>
                      <TableCell className="tabular-nums">{s ?? '—'}</TableCell>
                      <TableCell>
                        <StatusBadge status={compareField(c, s)} />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </div>
  )
}
