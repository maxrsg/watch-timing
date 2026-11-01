import type { WatchSummary } from '@/api/client'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const NONE = 'none'

/** Which watch is being measured; "none" reads without saving. */
export function WatchPicker({
  watches,
  value,
  onChange,
}: {
  watches: WatchSummary[]
  value: number | null
  onChange: (id: number | null) => void
}) {
  if (watches.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        <a href="#watches" className="font-medium text-foreground underline underline-offset-4">
          Add a watch
        </a>{' '}
        to save readings and see its rate.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="watch-picker" className="text-muted-foreground">
        Watch
      </Label>
      <Select
        value={value === null ? NONE : String(value)}
        onValueChange={(v) => onChange(v === NONE ? null : Number(v))}
      >
        <SelectTrigger id="watch-picker" size="touch" className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {watches.map((w) => (
            <SelectItem key={w.id} value={String(w.id)} className="min-h-11">
              {w.name}
            </SelectItem>
          ))}
          <SelectItem value={NONE} className="min-h-11 text-muted-foreground">
            No watch (don't save)
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}
