import { useEffect, useRef, useState } from 'react'
import { Aperture, LoaderCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { acquireCamera, cameraErrorMessage, releaseCamera } from '@/lib/camera'
import { type CapturedFrame, captureFrame } from '@/lib/frame'

// Undefined outside a secure context (plain HTTP).
const hasCamera = () => typeof navigator.mediaDevices?.getUserMedia === 'function'
const NO_CAMERA = 'This browser has no camera access (it needs HTTPS).'

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
    let cancelled = false
    if (!hasCamera()) return
    const video = videoRef.current
    // The page's one stream (lib/camera.ts): reopening the camera doesn't ask for permission
    // again on iOS, and the stream stops by itself once unused for a while.
    acquireCamera()
      .then(async (s) => {
        if (cancelled || !video) return
        video.srcObject = s
        await video.play()
        if (!cancelled) setReady(true)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(cameraErrorMessage(e))
      })
    return () => {
      cancelled = true
      if (video) video.srcObject = null
      releaseCamera()
    }
  }, [])

  async function capture() {
    const video = videoRef.current
    if (!video) return
    setError(null) // A previous capture error; camera-start errors keep the button disabled.
    try {
      onCapture(await captureFrame(video))
    } catch (e) {
      setError(cameraErrorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-2 lg:min-h-0 lg:flex-1">
      {/* Shows the centered square, as the photo view does at first; the whole frame is captured. */}
      <div className="lg:min-h-0 lg:flex-1 lg:square-fit">
        <div className="preview-square relative overflow-hidden rounded-lg bg-muted">
          <video ref={videoRef} className="size-full object-cover" playsInline muted />
          {!ready && !error && (
            <LoaderCircle className="absolute inset-0 m-auto animate-spin text-muted-foreground" />
          )}
        </div>
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
