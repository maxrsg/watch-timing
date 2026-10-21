import type { HandRole, HandTips, Overlay, PhotoPoint } from '@/api/client'

/**
 * A point at a clock angle (degrees clockwise from 12) and distance from `origin`, in image
 * coordinates (y points down): the same convention as the backend's `geometry.clock_point`.
 */
export function clockPoint(origin: PhotoPoint, angleDeg: number, distance: number): PhotoPoint {
  const a = (angleDeg * Math.PI) / 180
  return { x: origin.x + distance * Math.sin(a), y: origin.y - distance * Math.cos(a) }
}

// Where a hand's handle starts when the server found no such hand: clock angle and length as a
// fraction of the dial ring (a rough guess; the user drags it into place).
const DEFAULT_TIP: Record<HandRole, [number, number]> = {
  hour: [300, 0.45],
  minute: [60, 0.75],
  second: [180, 0.8],
}

/** Where to start a hand's handle: at the detected hand, or at a default spot if there's none. */
export function initialTip(overlay: Overlay, role: HandRole): PhotoPoint {
  const found = overlay.hands.find((h) => h.role === role)?.tip
  if (found) return found
  const [angle, length] = DEFAULT_TIP[role]
  return clockPoint(overlay.pivot, angle, length * overlay.dial_semi_major)
}

/** Start the handles at the detected hands, or at defaults for hands that weren't found. */
export function initialTips(overlay: Overlay): HandTips {
  return {
    hour: initialTip(overlay, 'hour'),
    minute: initialTip(overlay, 'minute'),
    second: initialTip(overlay, 'second'),
  }
}
