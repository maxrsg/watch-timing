// One camera stream for the page. iOS asks for permission on every new getUserMedia once the
// earlier capture has stopped, so closing and reopening the camera reuses the stream instead.
// It's stopped after a while unused, so the camera light doesn't stay on.

export const IDLE_STOP_MS = 2 * 60 * 1000

const CONSTRAINTS: MediaStreamConstraints = {
  audio: false,
  video: {
    facingMode: { ideal: 'environment' },
    width: { ideal: 3840 },
    height: { ideal: 2160 },
  },
}

let stream: Promise<MediaStream> | null = null
let idleTimer: ReturnType<typeof setTimeout> | null = null

function cancelIdleStop() {
  if (idleTimer !== null) clearTimeout(idleTimer)
  idleTimer = null
}

function stopCamera() {
  cancelIdleStop()
  const pending = stream
  stream = null
  pending?.then((s) => s.getTracks().forEach((t) => t.stop())).catch(() => {})
}

// iOS ends the tracks when the app goes to the background; such a stream is asked for again.
const isLive = (s: MediaStream) => s.getVideoTracks().every((t) => t.readyState === 'live')

export async function acquireCamera(): Promise<MediaStream> {
  cancelIdleStop()
  if (stream) {
    const current = stream
    try {
      const s = await current
      if (isLive(s)) return s
    } catch {
      // A failed request (denied, no camera) is retried below.
    }
    if (stream === current) stream = null
  }
  // A pending request is shared, so two quick mounts don't prompt twice.
  stream ??= navigator.mediaDevices.getUserMedia(CONSTRAINTS)
  const pending = stream
  try {
    return await pending
  } catch (e) {
    if (stream === pending) stream = null
    throw e
  }
}

export function releaseCamera() {
  cancelIdleStop()
  if (stream) idleTimer = setTimeout(stopCamera, IDLE_STOP_MS)
}

if (typeof window !== 'undefined') window.addEventListener('pagehide', stopCamera)
