import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Camera = typeof import('./camera')

function fakeStream() {
  const track = { readyState: 'live' as MediaStreamTrackState, stop: vi.fn() }
  track.stop.mockImplementation(() => {
    track.readyState = 'ended'
  })
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] }
  return { stream: stream as unknown as MediaStream, track }
}

let camera: Camera
let getUserMedia: ReturnType<typeof vi.fn>

beforeEach(async () => {
  vi.useFakeTimers()
  vi.resetModules() // The module keeps the stream; start each test without one.
  getUserMedia = vi.fn(async () => fakeStream().stream)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  camera = await import('./camera')
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('acquireCamera', () => {
  it('reuses the stream when reopened within the idle time', async () => {
    const first = await camera.acquireCamera()
    camera.releaseCamera()
    vi.advanceTimersByTime(camera.IDLE_STOP_MS - 1)
    expect(await camera.acquireCamera()).toBe(first)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
  })

  it('shares a pending request', async () => {
    const [a, b] = await Promise.all([camera.acquireCamera(), camera.acquireCamera()])
    expect(a).toBe(b)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
  })

  it('stops the stream after the idle time and asks again', async () => {
    const first = await camera.acquireCamera()
    camera.releaseCamera()
    await vi.advanceTimersByTimeAsync(camera.IDLE_STOP_MS)
    expect(first.getVideoTracks()[0]?.readyState).toBe('ended')
    expect(await camera.acquireCamera()).not.toBe(first)
    expect(getUserMedia).toHaveBeenCalledTimes(2)
  })

  it('asks again when the tracks have ended', async () => {
    const { stream, track } = fakeStream()
    getUserMedia.mockResolvedValueOnce(stream)
    await camera.acquireCamera()
    track.readyState = 'ended' // iOS, after the app went to the background
    expect(await camera.acquireCamera()).not.toBe(stream)
    expect(getUserMedia).toHaveBeenCalledTimes(2)
  })

  it('retries after a failed request', async () => {
    getUserMedia.mockRejectedValueOnce(new Error('denied'))
    await expect(camera.acquireCamera()).rejects.toThrow('denied')
    await camera.acquireCamera()
    expect(getUserMedia).toHaveBeenCalledTimes(2)
  })
})

describe('cameraErrorMessage', () => {
  it('says what to do for each kind of failure', () => {
    expect(camera.cameraErrorMessage(new DOMException('', 'NotFoundError'))).toMatch(/library/)
    expect(camera.cameraErrorMessage(new DOMException('', 'NotReadableError'))).toMatch(/in use/)
    expect(camera.cameraErrorMessage(new DOMException('', 'NotAllowedError'))).toMatch(/denied/)
    expect(camera.cameraErrorMessage({ name: 'OverconstrainedError' })).toMatch(/library/)
    expect(camera.cameraErrorMessage(new Error('Something else'))).toBe('Something else')
  })
})
