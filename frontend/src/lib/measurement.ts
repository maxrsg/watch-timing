import type { NewMeasurement, PhotoPoint, ReadResult } from '@/api/client'

/**
 * What to save for a reading, or null when it can't be a measurement: it needs the dial's
 * seconds and the photo's reference time. The server recomputes the deviation from these.
 */
export function measurementFromResult(result: ReadResult, tap: PhotoPoint | null): NewMeasurement | null {
  const r = result.reading
  if (
    !r ||
    r.seconds === null ||
    result.reference_time_utc === null ||
    result.reference_utc_offset_minutes === null ||
    result.reference_source === null
  ) {
    return null
  }
  return {
    reference_time_utc: result.reference_time_utc,
    reference_utc_offset_minutes: result.reference_utc_offset_minutes,
    reference_source: result.reference_source,
    platform: result.platform,
    frame_timing: result.frame_timing,
    latency_correction_ms: result.latency_correction_ms,
    hours: r.hours,
    minutes: r.minutes,
    seconds: r.seconds,
    confidence: r.confidence,
    seconds_confidence: r.seconds_confidence,
    correction: r.correction,
    overlay: result.overlay,
    tap,
    image_sha256: result.image_sha256,
  }
}
