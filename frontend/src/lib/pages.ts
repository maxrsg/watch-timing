import { type LucideIcon, ScanEye, Watch } from 'lucide-react'

export type Page = { hash: string; label: string; icon: LucideIcon }

/** The app's pages, by location hash ("" is the start page). */
export const PAGES: Page[] = [
  { hash: '', label: 'Read dial', icon: ScanEye },
  { hash: '#watches', label: 'Watches', icon: Watch },
]

/** A location hash split into its page ("#watches"), the path after it and its query. */
export type Route = { base: string; rest: string[]; query: URLSearchParams }

/** "#watches/3?owner=…" → base "#watches", rest ["3"], query owner=…. */
export function parseHash(hash: string): Route {
  const [path = '', search = ''] = hash.split('?', 2)
  const [base = '', ...rest] = path.split('/')
  return { base: base === '#' ? '' : base, rest, query: new URLSearchParams(search) }
}

/** The page for a location hash; unknown hashes and "#" go to the start page. */
export function pageFor(hash: string): Page {
  const { base } = parseHash(hash)
  return PAGES.find((p) => p.hash === base) ?? PAGES[0]!
}

/** The watch a "#watches/<id>" hash points at, or null for the list. */
export function watchIdFor(hash: string): number | null {
  const { base, rest } = parseHash(hash)
  const id = Number(rest[0])
  return base === '#watches' && Number.isInteger(id) && id > 0 ? id : null
}

/** A watch's page; with `saved`, the measurement just saved to it (highlighted there). */
export function watchHash(id: number, saved?: number): string {
  return saved === undefined ? `#watches/${id}` : `#watches/${id}?saved=${saved}`
}

/** The measurement a "#watches/<id>?saved=<mid>" hash points at, or null. */
export function savedMeasurementFor(hash: string): number | null {
  const id = Number(parseHash(hash).query.get('saved'))
  return watchIdFor(hash) !== null && Number.isInteger(id) && id > 0 ? id : null
}
