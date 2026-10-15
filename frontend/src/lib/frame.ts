/**
 * Grab one frame from the live camera together with the device-clock time of that frame.
 * Canvas frames have no EXIF, so the timestamp travels next to the image instead.
 */
import type { FrameTiming } from '@/api/client'

export type CapturedFrame = {
  blob: Blob
  captureTime: Date
  timing: FrameTiming
  width: number
  height: number
}

/** A frame callback normally fires within one frame; this only catches a stalled video. */
const FRAME_TIMEOUT_MS = 2000

/**
 * DOMHighResTimeStamp → wall-clock Date. Anchors on the current Date.now()/performance.now()
 * pair rather than performance.timeOrigin, which drifts from the wall clock on long-lived pages.
 */
export function wallClock(
  highRes: number,
  nowWall: number = Date.now(),
  nowPerf: number = performance.now(),
): Date {
  return new Date(nowWall - nowPerf + highRes)
}

function encode(video: HTMLVideoElement, captureTime: Date, timing: FrameTiming) {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const context = canvas.getContext('2d')
  // A missing context would upload a blank image with a valid timestamp: fail loudly instead.
  if (!context) return Promise.reject(new Error('Could not draw the camera frame.'))
  context.drawImage(video, 0, 0)
  return new Promise<CapturedFrame>((resolve, reject) =>
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve({ blob, captureTime, timing, width: canvas.width, height: canvas.height })
          : reject(new Error('Could not encode the camera frame.')),
      'image/jpeg',
      0.95,
    ),
  )
}

export function captureFrame(video: HTMLVideoElement): Promise<CapturedFrame> {
  if (!('requestVideoFrameCallback' in video)) {
    return encode(video, new Date(), 'tap')
  }
  // Draw inside the frame callback so the pixels and the metadata belong to the same frame.
  return new Promise((resolve, reject) => {
    const handle = video.requestVideoFrameCallback((_now, meta) => {
      clearTimeout(timeout)
      const [time, timing]: [number, FrameTiming] =
        meta.captureTime !== undefined
          ? [meta.captureTime, 'capture_time']
          : [meta.presentationTime, 'presentation_time']
      encode(video, wallClock(time), timing).then(resolve, reject)
    })
    const timeout = setTimeout(() => {
      video.cancelVideoFrameCallback(handle)
      reject(new Error('The camera stopped delivering frames.'))
    }, FRAME_TIMEOUT_MS)
  })
}
