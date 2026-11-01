/** Explicit sign for times, deviations and rates: "+", "−" (minus sign) or "±" for zero. */
export function sign(value: number): string {
  return value > 0 ? '+' : value < 0 ? '−' : '±'
}

/** "+3.2 s": explicit sign, one decimal. */
export function formatSignedSeconds(seconds: number): string {
  return `${sign(seconds)}${Math.abs(seconds).toFixed(1)} s`
}

/** "+123 ms": explicit sign. */
export function formatSignedMs(ms: number): string {
  return `${sign(ms)}${Math.abs(ms).toFixed(0)} ms`
}

/** "18:15:30.250" in UTC. */
export function formatUtcTime(ms: number): string {
  return new Date(ms).toISOString().slice(11, 23)
}

/** Message text from anything thrown, without the "Error: " prefix. */
export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** "2026-10-18T20:15:30.250+02:00": local wall time with the device's current UTC offset. */
export function toLocalIsoString(date: Date): string {
  const pad = (n: number, width = 2) => String(Math.abs(n)).padStart(width, '0')
  const offset = -date.getTimezoneOffset()
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `.${pad(date.getMilliseconds(), 3)}` +
    `${offset >= 0 ? '+' : '-'}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`
  )
}

/** "18:15:30.3": wall-clock time of a UTC instant in a zone given by its UTC offset. */
export function formatWallTime(utcMs: number, offsetMinutes: number): string {
  return new Date(utcMs + offsetMinutes * 60_000).toISOString().slice(11, 21)
}

/** "10:08:37.0", or "10:08:??" when the seconds were withheld. */
export function formatDialTime(hours: number, minutes: number, seconds: number | null): string {
  const s = seconds === null ? '??' : seconds.toFixed(1).padStart(4, '0')
  return `${hours}:${String(minutes).padStart(2, '0')}:${s}`
}

/** "+3.2 s/d": a rate in seconds per day, explicit sign. */
export function formatSignedRate(secondsPerDay: number): string {
  return `${sign(secondsPerDay)}${Math.abs(secondsPerDay).toFixed(1)} s/d`
}

/** "Oct 20, 08:15": a date and time in the device's zone, for lists. */
export function formatDateTime(utcMs: number, locale?: string): string {
  return new Date(utcMs).toLocaleString(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "photo EXIF" or "phone clock", for a reference source or a measurement's source key. */
export function sourceLabel(source: string): string {
  return source === 'exif' ? 'photo EXIF' : 'phone clock'
}
