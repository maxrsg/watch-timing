import { useEffect, useState } from 'react'
import type { HandRole, HandTips, Overlay, OverlayRole, PhotoPoint } from '@/api/client'
import { cropSquare } from '@/lib/crop'
import { cn } from '@/lib/utils'

const HAND_CLASS: Record<OverlayRole, string> = {
  hour: 'stroke-overlay-hour stroke-4',
  minute: 'stroke-overlay-minute stroke-3',
  second: 'stroke-overlay-second stroke-2',
  other: 'stroke-muted-foreground stroke-1',
}

const HANDLE_CLASS: Record<HandRole, string> = {
  hour: 'fill-overlay-hour',
  minute: 'fill-overlay-minute',
  second: 'fill-overlay-second',
}

const ROLES: HandRole[] = ['hour', 'minute', 'second']

/**
 * A square part of the photo (centered, or zoomed in on the dial once it's found), drawn in an
 * SVG whose coordinates are the photo's own pixels (the same coordinates the server uses): tap
 * 12 o'clock, see the detected dial and hands, or drag the hand tips into place (`tips` +
 * `onMoveTip`). Only the display is cropped; the upload is the whole photo.
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
  // Browsers draw photos upright (EXIF orientation applied, in SVG too), and naturalWidth/Height
  // are the upright size: the same frame the server reads the tap in.
  const [loaded, setLoaded] = useState<{ src: string; width: number; height: number } | null>(null)
  const [dragging, setDragging] = useState<HandRole | null>(null)
  useEffect(() => {
    const image = new Image()
    image.onload = () => setLoaded({ src, width: image.naturalWidth, height: image.naturalHeight })
    image.src = src
    return () => {
      image.onload = null
    }
  }, [src])
  const size = loaded?.src === src ? loaded : null
  const crop = size ? cropSquare(size, overlay) : null
  // Marks keep their size on screen whatever the crop.
  const unit = crop?.side ?? 0
  const marker = 0.012 * unit
  const editing = Boolean(tips && onMoveTip && overlay)

  /** The pointer in photo pixels, or null while the SVG isn't laid out (no screen transform). */
  function toPhoto(e: React.PointerEvent<SVGSVGElement>): PhotoPoint | null {
    const ctm = e.currentTarget.getScreenCTM()
    if (!ctm) return null
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse())
    return { x: p.x, y: p.y }
  }

  if (!size || !crop) return <div className="preview-square rounded-lg bg-muted" />
  return (
    // While dragging hands: no one-finger panning (it would scroll the page), but pinch-zoom
    // stays on for placing the thin seconds hand precisely.
    <svg
      viewBox={`${crop.x} ${crop.y} ${crop.side} ${crop.side}`}
      className={cn(
        'preview-square block overflow-hidden rounded-lg bg-muted select-none',
        editing ? 'touch-pinch-zoom' : 'touch-manipulation cursor-crosshair',
      )}
      role="img"
      aria-label={editing ? 'Drag the hand tips into place' : "Your photo of the watch: tap the 12 o'clock marker"}
      onPointerMove={(e) => {
        const point = dragging && onMoveTip ? toPhoto(e) : null
        if (dragging && onMoveTip && point) onMoveTip(dragging, point)
      }}
      onPointerUp={(e) => {
        if (dragging) {
          setDragging(null)
        } else if (!editing) {
          const point = toPhoto(e)
          if (point) onTap(point)
        }
      }}
      onPointerCancel={() => setDragging(null)}
    >
      <image href={src} width={size.width} height={size.height} />
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
  )
}
