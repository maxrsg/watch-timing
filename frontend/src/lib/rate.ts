import type { Rate } from '@/api/client'

/** Why a rate isn't trustworthy yet, for the user. */
export function rateNotes(rate: Rate | null, count: number): string[] {
  if (!rate) {
    return [count === 0 ? 'Save a reading to start.' : 'Needs a second measurement, ideally a day later.']
  }
  const notes = []
  if (rate.short_span) notes.push('Measurements span less than a day: the rate is still rough.')
  if (rate.mixed_sources) notes.push('Phone-clock and EXIF photos are mixed; each gets its own offset.')
  return notes
}
