import { CartesianGrid, ComposedChart, Line, ReferenceLine, Scatter, XAxis, YAxis } from 'recharts'
import type { Session } from '@/api/client'
import { type ChartConfig, ChartContainer, ChartTooltip } from '@/components/ui/chart'
import { formatDateTime, formatDialTime, formatSignedSeconds, sourceLabel } from '@/lib/format'

const DAY_MS = 86_400_000

const config = {
  deviation: { label: 'Deviation', color: 'var(--primary)' },
  fit: { label: 'Rate', color: 'var(--muted-foreground)' },
} satisfies ChartConfig

type Point = { t: number; deviation: number; reading: string; source: string }

function PointTooltip({ active, payload }: { active?: boolean; payload?: { payload?: unknown }[] }) {
  const point = payload?.[0]?.payload as Point | undefined
  if (!active || !point || !('reading' in point)) return null
  return (
    <div className="grid gap-0.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs shadow-xl">
      <span className="text-muted-foreground">{formatDateTime(point.t)}</span>
      <span className="font-medium tabular-nums">{formatSignedSeconds(point.deviation)}</span>
      <span className="text-muted-foreground tabular-nums">
        dial {point.reading} · {sourceLabel(point.source)}
      </span>
    </div>
  )
}

/**
 * Deviation against reference time for one session: the measurements as points and the
 * regression as a line (one per reference source, each with its own offset).
 */
export function DeviationChart({ session }: { session: Session }) {
  const points: Point[] = session.measurements.map((m) => ({
    t: Date.parse(m.reference_time_utc),
    deviation: m.deviation_s,
    reading: formatDialTime(m.hours, m.minutes, m.seconds),
    source: m.source_key,
  }))
  const rate = session.rate
  const fits = rate
    ? Object.entries(rate.intercepts).map(([source, intercept]) => {
        const ts = points.filter((p) => p.source === source).map((p) => p.t)
        const epoch = Date.parse(rate.epoch)
        const at = (t: number) => ({ t, fit: intercept + (rate.rate_s_per_day * (t - epoch)) / DAY_MS })
        return { source, line: [at(Math.min(...ts)), at(Math.max(...ts))] }
      })
    : []

  return (
    <ChartContainer config={config} className="aspect-auto h-56 w-full">
      <ComposedChart margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(t: number) => formatDateTime(t)}
          tickLine={false}
          axisLine={false}
          minTickGap={24}
        />
        <YAxis
          dataKey="deviation"
          type="number"
          width={52}
          tickFormatter={(s: number) => formatSignedSeconds(s)}
          tickLine={false}
          axisLine={false}
        />
        <ReferenceLine y={0} stroke="var(--border)" />
        {fits.map(({ source, line }) => (
          <Line
            key={source}
            data={line}
            dataKey="fit"
            stroke="var(--color-fit)"
            strokeWidth={2}
            strokeDasharray="4 4"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
        ))}
        <Scatter data={points} dataKey="deviation" fill="var(--color-deviation)" isAnimationActive={false} />
        <ChartTooltip cursor={false} content={<PointTooltip />} />
      </ComposedChart>
    </ChartContainer>
  )
}
