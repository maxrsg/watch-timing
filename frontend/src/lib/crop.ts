import type { Overlay } from '@/api/client'

/** A square part of the photo, in photo pixels: what the square photo view shows. */
export type Crop = { x: number; y: number; side: number }

// How much of the photo around the dial the view shows, in dial radii across.
const DIAL_SPAN = 2.5

/**
 * The square of the photo to show: centered on the photo, or zoomed in on the dial once it was
 * found. Never larger than the photo's shorter side, and always inside the photo.
 */
export function cropSquare(size: { width: number; height: number }, overlay: Overlay | null): Crop {
  const max = Math.min(size.width, size.height)
  const side = overlay ? Math.min(max, DIAL_SPAN * overlay.dial_semi_major) : max
  const cx = overlay ? overlay.dial_center.x : size.width / 2
  const cy = overlay ? overlay.dial_center.y : size.height / 2
  const clamp = (v: number, limit: number) => Math.min(Math.max(v, 0), limit - side)
  return { x: clamp(cx - side / 2, size.width), y: clamp(cy - side / 2, size.height), side }
}
