// Display formatting shared by several components.

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const PERCENT = 100

export function formatRate(rate: number | null): string {
  return rate === null ? '—' : `${(rate * PERCENT).toFixed(2)}%`
}

export function formatCount(count: number): string {
  return count.toLocaleString()
}

// "First sentence. The rest." -> a bold lead sentence and the rest, so long claims can be skimmed.
export function splitLead(text: string): [string, string] {
  const match = text.trim().match(/^(.+?[.!?।])\s+(.+)$/s)
  return match ? [match[1], match[2]] : [text.trim(), '']
}
