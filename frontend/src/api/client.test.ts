import { afterEach, describe, expect, it, vi } from 'vitest'
import { OFFLINE, TIMED_OUT, UNEXPECTED_RESPONSE, createWatch, listWatches, readDial } from './client'

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

  it('sends a typed time without a tap', async () => {
    const form = captureForm()
    await readDial(file, null, undefined, undefined, { hours: 12, minutes: 5, seconds: 7.5 })
    expect(form().has('tap_x')).toBe(false)
    expect([form().get('typed_hours'), form().get('typed_minutes'), form().get('typed_seconds')]).toEqual([
      '12',
      '5',
      '7.5',
    ])
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

describe('watch requests', () => {
  it('send the owner ID with the watch and its JSON body', async () => {
    let init: RequestInit | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, i: RequestInit) => {
        init = i
        return new Response('{}', { status: 201 })
      }),
    )
    await createWatch('Seiko')
    const headers = init!.headers as Record<string, string>
    expect(headers['X-Owner-Id']).toMatch(/^[0-9a-f-]{36}$/)
    expect(JSON.parse(init!.body as string)).toEqual({ name: 'Seiko' })
  })

  it('readDial sends the watch with the owner ID', async () => {
    let init: RequestInit | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, i: RequestInit) => {
        init = i
        return new Response('{}', { status: 200 })
      }),
    )
    await readDial(file, { x: 1, y: 2 }, undefined, undefined, undefined, 7)
    expect((init!.body as FormData).get('watch_id')).toBe('7')
    expect((init!.headers as Record<string, string>)['X-Owner-Id']).toBeTruthy()
  })
})

describe('errors', () => {
  function respond(response: () => Response | Promise<Response>) {
    vi.stubGlobal('fetch', vi.fn(async () => response()))
  }

  it("say so when the server can't be reached", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Load failed')
      }),
    )
    await expect(listWatches()).rejects.toThrow(OFFLINE)
  })

  it('say so when the server takes too long', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new DOMException('signal timed out', 'TimeoutError')
      }),
    )
    await expect(listWatches()).rejects.toThrow(TIMED_OUT)
  })

  it("show the server's message", async () => {
    respond(() => new Response(JSON.stringify({ detail: 'Watch not found.' }), { status: 404 }))
    await expect(listWatches()).rejects.toThrow('Watch not found.')
  })

  it('name the field of a validation error', async () => {
    const detail = [{ loc: ['body', 'typed_hours'], msg: 'Input should be less than or equal to 12', type: 'x' }]
    respond(() => new Response(JSON.stringify({ detail }), { status: 422 }))
    await expect(listWatches()).rejects.toThrow('Typed hours: Input should be less than or equal to 12')
  })

  it("explain a proxy's error page", async () => {
    respond(() => new Response('<html>Bad gateway</html>', { status: 502 }))
    await expect(listWatches()).rejects.toThrow('The server is starting or unavailable. Try again in a moment.')
  })

  it('catch a success that is not JSON', async () => {
    respond(() => new Response('<html></html>', { status: 200 }))
    await expect(listWatches()).rejects.toThrow(UNEXPECTED_RESPONSE)
  })
})
