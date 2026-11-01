import { useState } from 'react'
import { Camera } from 'lucide-react'
import { LibraryButton } from '@/components/LibraryButton'
import { LiveCamera } from '@/components/LiveCamera'
import { Button } from '@/components/ui/button'
import type { CapturedFrame } from '@/lib/frame'

/** Open the in-app camera or pick a photo from the library. The camera stays open until closed. */
export function CapturePicker({
  disabled = false,
  onFrame,
  onFile,
}: {
  disabled?: boolean
  onFrame: (frame: CapturedFrame) => void
  onFile: (file: File) => void
}) {
  const [cameraOpen, setCameraOpen] = useState(false)
  if (cameraOpen) {
    return <LiveCamera disabled={disabled} onClose={() => setCameraOpen(false)} onCapture={onFrame} />
  }
  return (
    <div className="flex flex-col gap-3 lg:min-h-0 lg:flex-1">
      {/* Where the viewfinder will be: an empty dial, which also opens the camera. */}
      <div className="lg:min-h-0 lg:flex-1 lg:square-fit">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setCameraOpen(true)}
          aria-label="Open camera"
          className="preview-square flex items-center justify-center rounded-xl border border-dashed border-primary/30 bg-card/60 transition-colors hover:bg-card focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <span className="flex size-3/4 flex-col items-center justify-center gap-3 rounded-full border-2 border-primary/25 text-muted-foreground ring-8 ring-primary/5">
            <Camera className="size-10 text-primary" />
            <span className="font-heading text-lg">Photograph the dial</span>
          </span>
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="touch" className="flex-1" disabled={disabled} onClick={() => setCameraOpen(true)}>
          <Camera /> Open camera
        </Button>
        <LibraryButton className="flex-1" disabled={disabled} onFile={onFile} />
      </div>
    </div>
  )
}
