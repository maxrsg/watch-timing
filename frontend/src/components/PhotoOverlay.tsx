import { useState } from 'react'
import type { Overlay } from '@/api/client'
import { cn } from '@/lib/utils'

export type PhotoPoint = { x: number; y: number }
export type HandRole = 'hour' | 'minute' | 'second'
/** Hand tips the user is placing, in photo pixels. `second: null` = no seconds hand. */
export type HandTips = { hour: PhotoPoint; minute: PhotoPoint; second: PhotoPoint | null }

const HAND_CLASS = {
  hour: 'stroke-overlay-hour stroke-4',
  minute: 'stroke-overlay-minute stroke-3',
  second: 'stroke-overlay-second stroke-2',
  other: 'stroke-muted-foreground stroke-1',
} as const

const HANDLE_CLASS = {
  hour: 'fill-overlay-hour',
  minute: 'fill-overlay-minute',
  second: 'fill-overlay-second',
} as const

const ROLES: HandRole[] = ['hour', 'minute', 'second']

/**
 * The photo with an SVG layer in the photo's own pixel coordinates (the same coordinates the
 * server uses): tap 12 o'clock, see the detected dial and hands, or drag the hand tips into
 * place (`tips` + `onMoveTip`).
 */
export function PhotoOverlay({
  src,
  tap,
  overlay,
  onTap,
  tips,
  onMoveTip,
}: {
  src: string
  tap: PhotoPoint | null
  overlay: Overlay | null
  onTap: (point: PhotoPoint) => void
  tips?: HandTips | null
  onMoveTip?: (role: HandRole, point: PhotoPoint) => void
}) {
  // Browsers display photos upright (EXIF orientation applied), and naturalWidth/Height are the
  // upright size: the same frame the server reads the tap in.
  const [size, setSize] = useState<{ width: number; height: number } | null>(null)
  const [dragging, setDragging] = useState<HandRole | null>(null)
  const unit = size ? Math.max(size.width, size.height) : 0
  const marker = 0.012 * unit
  const editing = Boolean(tips && onMoveTip && overlay)

  function toPhoto(e: React.PointerEvent<SVGSVGElement>): PhotoPoint {
    const box = e.currentTarget.getBoundingClientRect()
    return {
      x: ((e.clientX - box.left) / box.width) * (size?.width ?? 0),
      y: ((e.clientY - box.top) / box.height) * (size?.height ?? 0),
    }
  }

  return (
    // While dragging hands: no one-finger panning (it would scroll the page), but pinch-zoom
    // stays on for placing the thin seconds hand precisely.
    <div
      className={cn(
        'relative overflow-hidden rounded-lg bg-muted select-none',
        editing ? 'touch-pinch-zoom' : 'touch-manipulation',
      )}
    >
      <img
        src={src}
        alt="Your photo of the watch"
        className="block w-full"
        draggable={false}
        onLoad={(e) =>
          setSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })
        }
      />
      {size && (
        <svg
          viewBox={`0 0 ${size.width} ${size.height}`}
          preserveAspectRatio="none"
          className={cn('absolute inset-0 size-full', !editing && 'cursor-crosshair')}
          role="img"
          aria-label={editing ? 'Drag the hand tips into place' : "Tap the 12 o'clock marker"}
          onPointerMove={(e) => {
            if (dragging && onMoveTip) onMoveTip(dragging, toPhoto(e))
          }}
          onPointerUp={(e) => {
            if (dragging) setDragging(null)
            else if (!editing) onTap(toPhoto(e))
          }}
          onPointerCancel={() => setDragging(null)}
        >
          {overlay && (
            <g className="fill-none">
              <ellipse
                cx={overlay.dial_center.x}
                cy={overlay.dial_center.y}
                rx={overlay.dial_semi_major}
                ry={overlay.dial_semi_minor}
                transform={`rotate(${overlay.dial_angle_deg} ${overlay.dial_center.x} ${overlay.dial_center.y})`}
                className="stroke-overlay-dial stroke-2"
                vectorEffect="non-scaling-stroke"
              />
              {!editing &&
                overlay.hands.map((hand, i) => (
                  <line
                    key={i}
                    x1={overlay.pivot.x}
                    y1={overlay.pivot.y}
                    x2={hand.tip.x}
                    y2={hand.tip.y}
                    strokeLinecap="round"
                    strokeDasharray={hand.role === 'other' ? '6 6' : undefined}
                    className={HAND_CLASS[hand.role]}
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              <circle
                cx={overlay.twelve.x}
                cy={overlay.twelve.y}
                r={marker}
                className="stroke-overlay-dial stroke-2"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          )}
          {editing && overlay && tips && (
            <g>
              {ROLES.map((role) => {
                const tip = tips[role]
                if (!tip) return null
                return (
                  <g key={role}>
                    <line
                      x1={overlay.pivot.x}
                      y1={overlay.pivot.y}
                      x2={tip.x}
                      y2={tip.y}
                      strokeLinecap="round"
                      className={cn('fill-none', HAND_CLASS[role])}
                      vectorEffect="non-scaling-stroke"
                    />
                    {/* Large invisible target (≥44 px on a phone), small visible dot. */}
                    <circle
                      cx={tip.x}
                      cy={tip.y}
                      r={0.035 * unit}
                      className="cursor-grab fill-transparent"
                      onPointerDown={(e) => {
                        e.currentTarget.ownerSVGElement?.setPointerCapture(e.pointerId)
                        setDragging(role)
                      }}
                    />
                    <circle
                      cx={tip.x}
                      cy={tip.y}
                      r={0.012 * unit}
                      className={cn('pointer-events-none stroke-background stroke-2', HANDLE_CLASS[role])}
                      vectorEffect="non-scaling-stroke"
                    />
                  </g>
                )
              })}
              <circle
                cx={overlay.pivot.x}
                cy={overlay.pivot.y}
                r={0.006 * unit}
                className="pointer-events-none fill-background"
              />
            </g>
          )}
          {tap && !editing && (
            <g className={cn('fill-none stroke-primary-foreground', overlay && 'opacity-60')}>
              <circle cx={tap.x} cy={tap.y} r={marker * 1.6} className="stroke-3" vectorEffect="non-scaling-stroke" />
              <circle cx={tap.x} cy={tap.y} r={marker * 1.6} className="stroke-primary stroke-1" vectorEffect="non-scaling-stroke" />
            </g>
          )}
        </svg>
      )}
    </div>
  )
}
