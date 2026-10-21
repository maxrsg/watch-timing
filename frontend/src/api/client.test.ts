import { afterEach, describe, expect, it, vi } from 'vitest'
import { readDial } from './client'

function captureForm(): () => FormData {
  let body: FormData | undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      body = init.body as FormData
      return new Response('{}', { status: 200 })
    }),
  )
  return () => body!
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const file = new File(['x'], 'dial.jpg', { type: 'image/jpeg' })

describe('readDial', () => {
  it('sends the tap and no hand fields when none were placed', async () => {
    const form = captureForm()
    await readDial(file, { x: 10, y: 20 })
    expect(form().get('tap_x')).toBe('10')
    expect(form().get('tap_y')).toBe('20')
    expect(form().has('hour_x')).toBe(false)
  })

  it('sends placed hands, leaving out a missing seconds hand', async () => {
    const form = captureForm()
    await readDial(file, { x: 1, y: 2 }, undefined, {
      hour: { x: 3, y: 4 },
      minute: { x: 5, y: 6 },
      second: null,
    })
    expect([form().get('hour_x'), form().get('hour_y')]).toEqual(['3', '4'])
    expect([form().get('minute_x'), form().get('minute_y')]).toEqual(['5', '6'])
    expect(form().has('second_x')).toBe(false)
  })

  it('sends the device fields together', async () => {
    const form = captureForm()
    const captureTime = new Date(Date.UTC(2026, 9, 20, 12, 0, 0))
    await readDial(file, { x: 1, y: 2 }, { captureTime, timing: 'tap', platform: 'android' })
    expect(form().get('frame_timing')).toBe('tap')
    expect(form().get('platform')).toBe('android')
    expect(form().get('device_capture_time')).toBeTruthy()
  })
})
