import { describe, expect, it } from 'vitest'
import { type CapturedFrame, frameDevice, frameToFile, wallClock } from './frame'

const frame: CapturedFrame = {
  blob: new Blob(['jpeg'], { type: 'image/jpeg' }),
  captureTime: new Date(Date.UTC(2026, 9, 20, 12, 0, 0, 250)),
  timing: 'capture_time',
  width: 4,
  height: 3,
}

describe('frameToFile', () => {
  it('names the file after the capture time and keeps the type', () => {
    const file = frameToFile(frame)
    expect(file.name).toBe(`frame-${frame.captureTime.getTime()}.jpg`)
    expect(file.type).toBe('image/jpeg')
  })
})

describe('frameDevice', () => {
  it('carries the frame time, its timing source and the platform', () => {
    expect(frameDevice(frame, 'ios')).toEqual({
      captureTime: frame.captureTime,
      timing: 'capture_time',
      platform: 'ios',
    })
  })
})

describe('wallClock', () => {
  it('anchors a high-res timestamp on the current wall/perf pair', () => {
    expect(wallClock(900, 10_000, 1_000).getTime()).toBe(9_900)
  })
})
