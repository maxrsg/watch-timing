import { toLocalIsoString } from '@/lib/format'
import { ownerId } from '@/lib/owner'
import type { components } from './schema'

export type ProbeResult = components['schemas']['ProbeResult']
export type ExifTags = components['schemas']['ExifTags']
export type ServerTime = components['schemas']['ServerTime']
export type FrameTiming = components['schemas']['FrameTiming']
export type Platform = components['schemas']['Platform']
export type ReadResult = components['schemas']['ReadResult']
export type Overlay = components['schemas']['Overlay']
export type DialReading = components['schemas']['DialReadingOut']
export type WatchSummary = components['schemas']['WatchSummary']
export type WatchDetail = components['schemas']['WatchDetail']
export type Session = components['schemas']['SessionOut']
export type SavedMeasurement = components['schemas']['MeasurementOut']
export type NewMeasurement = components['schemas']['MeasurementIn']
export type Rate = components['schemas']['RateOut']
/** A point in the upright photo's pixels: the frame the tap, the overlay and hand tips use. */
export type PhotoPoint = components['schemas']['PhotoPoint']
export type OverlayRole = components['schemas']['HandOverlay']['role']
export type HandRole = Exclude<OverlayRole, 'other'>
/** Hand tips the user placed, in photo pixels. `second: null` = no seconds hand. */
export type HandTips = Record<'hour' | 'minute', PhotoPoint> & { second: PhotoPoint | null }

/** A time the user read off the dial and typed: hours 1–12 as the dial shows them. */
export type TypedTime = { hours: number; minutes: number; seconds: number }

export type DeviceCapture = { captureTime: Date; timing: FrameTiming; platform: Platform }

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    // FastAPI validation errors: [{ loc, msg, type }, …]
    const first = Array.isArray(body.detail) ? body.detail[0] : undefined
    if (typeof first?.msg === 'string') return first.msg
  } catch {
    // Not JSON; fall through.
  }
  return `Request failed (${res.status})`
}

/**
 * Upload the original file bytes unchanged (no canvas, no re-encoding).
 * `device` is only for frames from the in-app camera, which have no EXIF: the device-clock
 * time of the frame, which frame timestamp it is, and the platform. The server calibrates the
 * camera latency per (platform, timing).
 */
export async function probe(file: File, device?: DeviceCapture): Promise<ProbeResult> {
  const form = uploadForm(file, device)
  const res = await fetch('/api/probe', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

/**
 * Read the dial. `tap` is the 12 o'clock marker in the upright photo's pixels. With `hands`
 * (tips the user placed, same pixels), the server uses them instead of detecting the hands.
 * With `typed`, the server takes that time as the reading (no tap needed); the photo then only
 * provides the reference time. With `watchId`, the server steers the reading with that
 * watch's predicted deviation.
 */
export async function readDial(
  file: File,
  tap: PhotoPoint | null,
  device?: DeviceCapture,
  hands?: HandTips,
  typed?: TypedTime,
  watchId?: number,
): Promise<ReadResult> {
  const form = uploadForm(file, device)
  const headers: Record<string, string> = {}
  if (watchId !== undefined) {
    form.append('watch_id', String(watchId))
    headers['X-Owner-Id'] = ownerId()
  }
  if (tap) {
    form.append('tap_x', String(tap.x))
    form.append('tap_y', String(tap.y))
  }
  if (typed) {
    form.append('typed_hours', String(typed.hours))
    form.append('typed_minutes', String(typed.minutes))
    form.append('typed_seconds', String(typed.seconds))
  }
  if (hands) {
    for (const role of ['hour', 'minute', 'second'] as const) {
      const tip = hands[role]
      if (!tip) continue
      form.append(`${role}_x`, String(tip.x))
      form.append(`${role}_y`, String(tip.y))
    }
  }
  const res = await fetch('/api/read', { method: 'POST', body: form, headers })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

function uploadForm(file: File, device?: DeviceCapture): FormData {
  const form = new FormData()
  form.append('file', file, file.name)
  if (device) {
    // Local time with its UTC offset: the dial shows local time, so the server needs the zone.
    form.append('device_capture_time', toLocalIsoString(device.captureTime))
    form.append('frame_timing', device.timing)
    form.append('platform', device.platform)
  }
  return form
}

export async function getServerTime(): Promise<ServerTime> {
  const res = await fetch('/api/time', { cache: 'no-store' })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

/** A watch request: JSON, with this browser's anonymous owner ID. */
async function watchRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Owner-Id': ownerId() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  return (res.status === 204 ? undefined : await res.json()) as T
}

export function listWatches(): Promise<WatchSummary[]> {
  return watchRequest('/api/watches')
}

export function createWatch(name: string): Promise<WatchSummary> {
  return watchRequest('/api/watches', 'POST', { name })
}

export function renameWatch(id: number, name: string): Promise<WatchSummary> {
  return watchRequest(`/api/watches/${id}`, 'PATCH', { name })
}

export function deleteWatch(id: number): Promise<void> {
  return watchRequest(`/api/watches/${id}`, 'DELETE')
}

export function getWatch(id: number): Promise<WatchDetail> {
  return watchRequest(`/api/watches/${id}`)
}

/** The watch was set: a new session starts (the rate starts over). */
export function startSession(id: number): Promise<WatchDetail> {
  return watchRequest(`/api/watches/${id}/sessions`, 'POST')
}

export function saveMeasurement(watchId: number, measurement: NewMeasurement): Promise<SavedMeasurement> {
  return watchRequest(`/api/watches/${watchId}/measurements`, 'POST', measurement)
}

export function deleteMeasurement(watchId: number, measurementId: number): Promise<void> {
  return watchRequest(`/api/watches/${watchId}/measurements/${measurementId}`, 'DELETE')
}
