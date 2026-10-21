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
    <div className="flex flex-wrap gap-2">
      <Button size="touch" disabled={disabled} onClick={() => setCameraOpen(true)}>
        <Camera /> Open camera
      </Button>
      <LibraryButton disabled={disabled} onFile={onFile} />
    </div>
  )
}
