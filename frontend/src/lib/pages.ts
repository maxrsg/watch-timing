import { Clock, FlaskConical, type LucideIcon, ScanEye } from 'lucide-react'

export type Page = { hash: string; label: string; icon: LucideIcon }

/** The app's pages, by location hash ("" is the start page). */
export const PAGES: Page[] = [
  { hash: '', label: 'Read dial', icon: ScanEye },
  { hash: '#probe', label: 'Timestamp check', icon: FlaskConical },
  { hash: '#clock', label: 'Reference clock', icon: Clock },
]

/** The page for a location hash; unknown hashes and "#" go to the start page. */
export function pageFor(hash: string): Page {
  return PAGES.find((p) => p.hash === hash) ?? PAGES[0]!
}
