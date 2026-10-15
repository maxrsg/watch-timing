import type { components } from './schema'

export type ProbeResult = components['schemas']['ProbeResult']
export type ExifTags = components['schemas']['ExifTags']
export type ServerTime = components['schemas']['ServerTime']
export type FrameTiming = components['schemas']['FrameTiming']
export type Platform = components['schemas']['Platform']

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
export async function probe(
  file: File,
  device?: { captureTime: Date; timing: FrameTiming; platform: Platform },
): Promise<ProbeResult> {
  const form = new FormData()
  form.append('file', file, file.name)
  if (device) {
    form.append('device_capture_time', device.captureTime.toISOString())
    form.append('frame_timing', device.timing)
    form.append('platform', device.platform)
  }
  const res = await fetch('/api/probe', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

export async function getServerTime(): Promise<ServerTime> {
  const res = await fetch('/api/time', { cache: 'no-store' })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}
