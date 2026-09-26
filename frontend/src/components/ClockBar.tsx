import { useEffect, useState } from 'react'
import { api, errorText, type ClockState, type PublishRun } from '../api'
import { formatTime } from '../format'

const CLOCK_REFRESH_MS = 30_000
const HOURS_PER_DAY = 24

function runSummary(run: PublishRun): string {
  if (run.published.length === 0 && run.rejected.length === 0) {
    return run.metrics_ingested.length > 0
      ? `Nothing was due. Metrics updated for ${run.metrics_ingested.length} posts.`
      : 'Nothing was due.'
  }
  const parts = []
  if (run.published.length > 0) parts.push(`published ${run.published.map((id) => `#${id}`).join(', ')}`)
  if (run.rejected.length > 0) parts.push(`rejected ${run.rejected.map((id) => `#${id}`).join(', ')}`)
  const metrics = run.metrics_ingested.length > 0 ? ` Metrics updated for ${run.metrics_ingested.length} posts.` : ''
  return `Adapters ${parts.join(' · ')}.${metrics}`
}

interface ClockBarProps {
  // Called after a publishing run so views showing posts reload.
  onPublished: () => void
}

// The demo clock: shows "now" (including any fast-forward) and runs due posts through the adapters on demand.
export function ClockBar({ onPublished }: ClockBarProps) {
  const [clock, setClock] = useState<ClockState | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    const refresh = () => api.getClock().then(setClock).catch((caught) => setMessage(errorText(caught)))
    refresh()
    const timer = window.setInterval(refresh, CLOCK_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [])

  async function resetToRealTime() {
    setBusy(true)
    try {
      setClock(await api.resetClock())
      setMessage('Back to real time. Posts published during the fast-forward keep their times; their metrics pause until real time catches up.')
      onPublished()
    } catch (caught) {
      setMessage(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function run(action: () => Promise<PublishRun>) {
    setBusy(true)
    try {
      const result = await action()
      setMessage(runSummary(result))
      setClock(await api.getClock())
      onPublished()
    } catch (caught) {
      setMessage(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="clock-bar">
      <span className="clock-now" title="Posts publish when this clock reaches their scheduled time.">
        🕒 {clock ? formatTime(clock.now) : '…'}
        {clock && clock.offset_hours > 0 && <span className="muted"> (+{clock.offset_hours.toFixed(0)}h fast-forward)</span>}
      </span>
      <button type="button" disabled={busy} onClick={() => run(() => api.advanceClock(1))}>
        +1 hour
      </button>
      <button type="button" disabled={busy} onClick={() => run(() => api.advanceClock(HOURS_PER_DAY))}>
        +1 day
      </button>
      <button type="button" disabled={busy} onClick={() => run(api.publishDueNow)}>
        Publish due now
      </button>
      <button
        type="button"
        disabled={busy || !clock || clock.offset_hours === 0}
        onClick={resetToRealTime}
        title="Drop the fast-forward and return to the real current time"
      >
        Reset to current time
      </button>
      {message && <span className="clock-message">{message}</span>}
    </div>
  )
}
