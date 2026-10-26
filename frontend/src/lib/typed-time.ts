import type { ReadResult, TypedTime } from '@/api/client'

/** The typed-time form's fields, as typed. */
export type TypedTimeFields = { hours: string; minutes: string; seconds: string }

const HINT: TypedTimeFields = { hours: 'h', minutes: 'mm', seconds: 'ss.s' }

const WHOLE = /^\d{1,2}$/
const DECIMAL = /^\d{1,2}([.,]\d*)?$/

/** The typed time, or a message saying what's wrong. A comma works as the decimal separator. */
export function parseTypedTime(fields: TypedTimeFields): TypedTime | string {
  const h = fields.hours.trim()
  const m = fields.minutes.trim()
  const s = fields.seconds.trim()
  if (!h || !m || !s) return 'Enter the hours, minutes and seconds.'
  const hours = WHOLE.test(h) ? Number(h) : NaN
  if (!(hours >= 1 && hours <= 12)) return 'Hours go from 1 to 12.'
  const minutes = WHOLE.test(m) ? Number(m) : NaN
  if (!(minutes >= 0 && minutes <= 59)) return 'Minutes go from 0 to 59.'
  const seconds = DECIMAL.test(s) ? Number(s.replace(',', '.')) : NaN
  if (!(seconds >= 0 && seconds < 60)) return 'Seconds go from 0 to 59.9.'
  return { hours, minutes, seconds }
}

/**
 * The form's placeholders (the fields themselves start empty): the current reading, or else the
 * hour and minute of the photo's reference time. The seconds placeholder is a reading's seconds
 * or a format hint, never the reference's: they're what the deviation is made of.
 */
export function typedTimePlaceholders(result: ReadResult | null): TypedTimeFields {
  const r = result?.reading
  if (r) {
    return {
      hours: String(r.hours),
      minutes: String(r.minutes).padStart(2, '0'),
      seconds: r.seconds === null ? HINT.seconds : r.seconds.toFixed(1),
    }
  }
  if (result?.reference_time_utc && result.reference_utc_offset_minutes !== null) {
    const wall = new Date(Date.parse(result.reference_time_utc) + result.reference_utc_offset_minutes * 60_000)
    return {
      hours: String(wall.getUTCHours() % 12 || 12),
      minutes: String(wall.getUTCMinutes()).padStart(2, '0'),
      seconds: HINT.seconds,
    }
  }
  return HINT
}
