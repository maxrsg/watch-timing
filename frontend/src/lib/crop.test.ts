import { describe, expect, it } from 'vitest'
import type { Overlay } from '@/api/client'
import { cropSquare } from './crop'

const PORTRAIT = { width: 1000, height: 2000 }

function dial(x: number, y: number, radius: number): Overlay {
  return {
    dial_center: { x, y },
    dial_semi_major: radius,
    dial_semi_minor: radius,
    dial_angle_deg: 0,
    pivot: { x, y },
    twelve: { x, y: y - radius },
    hands: [],
  }
}

describe('cropSquare', () => {
  it('shows the centered square without a dial', () => {
    expect(cropSquare(PORTRAIT, null)).toEqual({ x: 0, y: 500, side: 1000 })
    expect(cropSquare({ width: 2000, height: 1000 }, null)).toEqual({ x: 500, y: 0, side: 1000 })
  })

  it('zooms in on the dial', () => {
    expect(cropSquare(PORTRAIT, dial(500, 900, 200))).toEqual({ x: 250, y: 650, side: 500 })
  })

  it('never shows more than the photo and stays inside it', () => {
    expect(cropSquare(PORTRAIT, dial(500, 900, 600))).toEqual({ x: 0, y: 400, side: 1000 })
    expect(cropSquare(PORTRAIT, dial(100, 1950, 200))).toEqual({ x: 0, y: 1500, side: 500 })
  })
})
