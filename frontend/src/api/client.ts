import { toLocalIsoString } from '@/lib/format'
import type { components } from './schema'

export type ProbeResult = components['schemas']['ProbeResult']
export type ExifTags = components['schemas']['ExifTags']
export type ServerTime = components['schemas']['ServerTime']
export type FrameTiming = components['schemas']['FrameTiming']
export type Platform = components['schemas']['Platform']
export type ReadResult = components['schemas']['ReadResult']
export type Overlay = components['schemas']['Overlay']
export type DialReading = components['schemas']['DialReadingOut']
/** A point in the upright photo's pixels: the frame the tap, the overlay and hand tips use. */
export type PhotoPoint = components['schemas']['PhotoPoint']
export type OverlayRole = components['schemas']['HandOverlay']['role']
export type HandRole = Exclude<OverlayRole, 'other'>
/** Hand tips the user placed, in photo pixels. `second: null` = no seconds hand. */
export type HandTips = Record<'hour' | 'minute', PhotoPoint> & { second: PhotoPoint | null }

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
 */
export async function readDial(
  file: File,
  tap: PhotoPoint,
  device?: DeviceCapture,
  hands?: HandTips,
): Promise<ReadResult> {
  const form = uploadForm(file, device)
  form.append('tap_x', String(tap.x))
  form.append('tap_y', String(tap.y))
  if (hands) {
    for (const role of ['hour', 'minute', 'second'] as const) {
      const tip = hands[role]
      if (!tip) continue
      form.append(`${role}_x`, String(tip.x))
      form.append(`${role}_y`, String(tip.y))
    }
  }
  const res = await fetch('/api/read', { method: 'POST', body: form })
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
