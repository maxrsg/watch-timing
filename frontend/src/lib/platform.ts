import type { Platform } from '@/api/client'

/**
 * Coarse platform for the camera-latency calibration, which depends on device and engine.
 * iPadOS reports itself as "Macintosh", so a touch-capable Mac is treated as iOS.
 */
export function detectPlatform(
  userAgent: string = navigator.userAgent,
  maxTouchPoints: number = navigator.maxTouchPoints,
): Platform {
  if (/iPhone|iPad|iPod/.test(userAgent)) return 'ios'
  if (/Macintosh/.test(userAgent) && maxTouchPoints > 1) return 'ios'
  if (/Android/.test(userAgent)) return 'android'
  return 'other'
}
