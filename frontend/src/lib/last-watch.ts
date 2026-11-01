import { readStored, writeStored } from '@/lib/storage'

const KEY = 'watchtiming.watch'

/** The watch last chosen for reading, remembered per browser (null: none). */
export function lastWatchId(): number | null {
  const id = Number(readStored(KEY))
  return Number.isInteger(id) && id > 0 ? id : null
}

export function rememberWatch(id: number | null): void {
  writeStored(KEY, id === null ? null : String(id))
}
