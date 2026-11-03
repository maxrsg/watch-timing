import type { Rate } from '@/api/client'
import { fastSlowClass, formatSignedRate } from '@/lib/format'
import { cn } from '@/lib/utils'

/** A session's rate, "+3.2 s/d", colored fast/slow; a hint while there isn't one yet. */
export function RateText({ rate, className }: { rate: Rate | null; className?: string }) {
  if (!rate) return <span className={cn('text-muted-foreground', className)}>No rate yet</span>
  return (
    <span className={cn('font-semibold tabular-nums', fastSlowClass(rate.rate_s_per_day), className)}>
      {formatSignedRate(rate.rate_s_per_day)}
    </span>
  )
}
