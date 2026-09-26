// Display formatting shared by several components.

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const PERCENT = 100

export function formatRate(rate: number | null): string {
  return rate === null ? '—' : `${(rate * PERCENT).toFixed(2)}%`
}

export function formatCount(count: number): string {
  return count.toLocaleString()
}
