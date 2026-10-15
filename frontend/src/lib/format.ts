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
