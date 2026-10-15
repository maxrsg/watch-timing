import exifr from 'exifr'
import type { ExifTags } from '@/api/client'

/** Same shape as the server's tags, so client and server can be compared field by field. */
export type ClientExif = ExifTags

export const EXIF_FIELDS = [
  ['datetime_original', 'DateTimeOriginal'],
  ['subsec_time_original', 'SubSecTimeOriginal'],
  ['offset_time_original', 'OffsetTimeOriginal'],
  ['make', 'Make'],
  ['model', 'Model'],
  ['orientation', 'Orientation'],
] as const satisfies readonly (readonly [keyof ExifTags, string])[]

function normalize(value: unknown): string | number | null {
  if (value === undefined || value === null) return null
  if (typeof value === 'number') return value
  const text = String(value).replace(/\0/g, '').trim()
  return text === '' ? null : text
}

export async function readClientExif(file: File): Promise<ClientExif> {
  // Raw values (no Date revival, no translation) to match what the server reads.
  const raw = (await exifr.parse(file, {
    pick: EXIF_FIELDS.map(([, tag]) => tag),
    reviveValues: false,
    translateValues: false,
  })) as Record<string, unknown> | undefined

  const out = {} as Record<keyof ExifTags, string | number | null>
  for (const [key, tag] of EXIF_FIELDS) out[key] = normalize(raw?.[tag])
  return out as ClientExif
}

export async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

export type FieldStatus = 'ok' | 'missing' | 'mismatch'

export function compareField(client: unknown, server: unknown): FieldStatus {
  if (client === null || server === null) return 'missing'
  return String(client) === String(server) ? 'ok' : 'mismatch'
}
