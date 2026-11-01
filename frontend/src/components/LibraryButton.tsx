import { Images } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Pick a photo from the library. No `capture` attribute: on iOS that strips the EXIF time. */
export function LibraryButton({
  disabled,
  onFile,
  className,
}: {
  disabled: boolean
  onFile: (f: File) => void
  className?: string
}) {
  return (
    // asChild puts `disabled` on a <label>, so style aria-disabled; focus lands on the hidden input.
    <Button
      asChild
      size="touch"
      variant="outline"
      className={cn(
        'has-focus-visible:border-ring has-focus-visible:ring-3 has-focus-visible:ring-ring/50 aria-disabled:pointer-events-none aria-disabled:opacity-50',
        className,
      )}
    >
      <label aria-disabled={disabled}>
        <Images /> Choose from library
        <input
          className="sr-only"
          type="file"
          accept="image/*"
          disabled={disabled}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) onFile(file)
          }}
        />
      </label>
    </Button>
  )
}
