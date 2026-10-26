import { useState } from 'react'
import { Check } from 'lucide-react'
import type { TypedTime } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { type TypedTimeFields, parseTypedTime } from '@/lib/typed-time'

const FIELDS = [
  { key: 'hours', label: 'Hours', inputMode: 'numeric' },
  { key: 'minutes', label: 'Minutes', inputMode: 'numeric' },
  { key: 'seconds', label: 'Seconds', inputMode: 'decimal' },
] as const

const EMPTY: TypedTimeFields = { hours: '', minutes: '', seconds: '' }

/**
 * Type the time the watch shows in the photo: always on offer, for when the reading isn't good
 * enough. The fields start empty; `placeholders` shows the current reading for reference.
 */
export function TypedTimeForm({
  placeholders,
  busy,
  onSubmit,
}: {
  placeholders: TypedTimeFields
  busy: boolean
  onSubmit: (time: TypedTime) => void
}) {
  const [fields, setFields] = useState(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const typed = Object.values(fields).some((v) => v.trim())

  return (
    <form
      className="flex flex-col gap-3"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        const time = parseTypedTime(fields)
        if (typeof time === 'string') setError(time)
        else onSubmit(time)
      }}
    >
      <div className="flex flex-col gap-0.5">
        <p className="font-medium">
          Or type the time <span className="font-normal text-muted-foreground">(optional)</span>
        </p>
        <p className="text-sm text-muted-foreground">If the reading is off, type what the dial shows.</p>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {FIELDS.map(({ key, label, inputMode }) => (
          <div key={key} className="flex flex-col gap-1.5">
            <Label htmlFor={`typed-${key}`} className="text-muted-foreground">
              {label}
            </Label>
            <Input
              id={`typed-${key}`}
              className="h-11 text-center text-lg tabular-nums"
              inputMode={inputMode}
              enterKeyHint={key === 'seconds' ? 'done' : 'next'}
              autoComplete="off"
              placeholder={placeholders[key]}
              value={fields[key]}
              aria-invalid={error !== null}
              onChange={(e) => {
                setFields((f) => ({ ...f, [key]: e.target.value }))
                setError(null)
              }}
            />
          </div>
        ))}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" size="touch" variant="outline" disabled={busy || !typed}>
        <Check /> Use this time
      </Button>
    </form>
  )
}
