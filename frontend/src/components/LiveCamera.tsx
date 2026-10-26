import { useEffect, useRef, useState } from 'react'
import { Aperture, LoaderCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { errorText } from '@/lib/format'
import { type CapturedFrame, captureFrame } from '@/lib/frame'

// Undefined outside a secure context (plain HTTP).
const hasCamera = () => typeof navigator.mediaDevices?.getUserMedia === 'function'
const NO_CAMERA = 'This browser has no camera access (it needs HTTPS).'

function cameraError(e: unknown): string {
  if (e instanceof DOMException && e.name === 'NotAllowedError') {
    return 'Camera access was denied. Allow it in the browser settings and try again.'
  }
  return errorText(e)
}

export function LiveCamera({
  disabled,
  onCapture,
  onClose,
}: {
  disabled: boolean
  onCapture: (frame: CapturedFrame) => void
  onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(() => (hasCamera() ? null : NO_CAMERA))

  useEffect(() => {
    let stream: MediaStream | null = null
    let cancelled = false
    if (!hasCamera()) return
    navigator.mediaDevices
      .getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 3840 },
          height: { ideal: 2160 },
        },
      })
      .then(async (s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop())
          return
        }
        stream = s
        const video = videoRef.current
        if (!video) return
        video.srcObject = s
        await video.play()
        if (!cancelled) setReady(true)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(cameraError(e))
      })
    return () => {
      cancelled = true
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  async function capture() {
    const video = videoRef.current
    if (!video) return
    setError(null) // A previous capture error; camera-start errors keep the button disabled.
    try {
      onCapture(await captureFrame(video))
    } catch (e) {
      setError(cameraError(e))
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Shows the centered square, as the photo view does at first; the whole frame is captured. */}
      <div className="preview-square relative overflow-hidden rounded-lg bg-muted">
        <video ref={videoRef} className="size-full object-cover" playsInline muted />
        {!ready && !error && (
          <LoaderCircle className="absolute inset-0 m-auto animate-spin text-muted-foreground" />
        )}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="touch" className="flex-1" disabled={!ready || disabled} onClick={capture}>
          <Aperture /> Capture
        </Button>
        <Button size="touch" variant="outline" onClick={onClose} aria-label="Close camera">
          <X />
        </Button>
      </div>
    </div>
  )
}
