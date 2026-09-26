import { useEffect, useState } from 'react'
import { ArrowCounterClockwise, Broadcast, Clock } from '@phosphor-icons/react'
import { api, errorText, type ClockState, type PublishRun } from '../api'

const CLOCK_REFRESH_MS = 30_000
const HOURS_PER_DAY = 24
// A run summary stays up this long, then clears itself.
const MESSAGE_VISIBLE_MS = 7000

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

function clockParts(iso: string): { date: string; time: string } {
  const now = new Date(iso)
  return {
    date: now.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }),
    time: now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
  }
}

interface ClockBarProps {
  // Called after a publishing run so views showing posts reload.
  onPublished: () => void
}

// The demo clock: shows "now" (including any fast-forward) and runs due posts through the adapters on demand.
export function ClockBar({ onPublished }: ClockBarProps) {
  const [clock, setClock] = useState<ClockState | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null)

  useEffect(() => {
    const refresh = () => api.getClock().then(setClock).catch((caught) => setMessage({ text: errorText(caught), error: true }))
    refresh()
    const timer = window.setInterval(refresh, CLOCK_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(null), MESSAGE_VISIBLE_MS)
    return () => window.clearTimeout(timer)
  }, [message])

  async function resetToRealTime() {
    setBusy(true)
    try {
      setClock(await api.resetClock())
      setMessage({
        text: 'Back to real time. Posts published during the fast-forward keep their times; their metrics pause until real time catches up.',
        error: false,
      })
      onPublished()
    } catch (caught) {
      setMessage({ text: errorText(caught), error: true })
    } finally {
      setBusy(false)
    }
  }

  async function run(action: () => Promise<PublishRun>) {
    setBusy(true)
    try {
      const result = await action()
      setMessage({ text: runSummary(result), error: false })
      setClock(await api.getClock())
      onPublished()
    } catch (caught) {
      setMessage({ text: errorText(caught), error: true })
    } finally {
      setBusy(false)
    }
  }

  const parts = clock ? clockParts(clock.now) : null
  const fastForwarded = clock !== null && clock.offset_hours > 0

  return (
    <div className="clock" role="group" aria-label="Demo clock">
      <span className="clock-now" title="Demo clock. Posts publish when it reaches their scheduled time.">
        <Clock size={16} aria-hidden="true" />
        {parts ? (
          <>
            <span className="clock-date">{parts.date}</span>
            <span className="mono clock-time">{parts.time}</span>
          </>
        ) : (
          <span className="mono">--:--</span>
        )}
        {fastForwarded && <span className="clock-offset mono">+{clock.offset_hours.toFixed(0)}h</span>}
      </span>
      <span className="clock-controls">
        <button type="button" className="clock-btn" disabled={busy} onClick={() => run(() => api.advanceClock(1))} title="Move the demo clock forward one hour">
          +1h
        </button>
        <button
          type="button"
          className="clock-btn"
          disabled={busy}
          onClick={() => run(() => api.advanceClock(HOURS_PER_DAY))}
          title="Move the demo clock forward one day"
        >
          +1d
        </button>
        <button
          type="button"
          className="clock-btn clock-btn-icon"
          disabled={busy || !fastForwarded}
          onClick={resetToRealTime}
          title="Reset to the real current time"
          aria-label="Reset to the real current time"
        >
          <ArrowCounterClockwise size={15} aria-hidden="true" />
        </button>
      </span>
      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => run(api.publishDueNow)}>
        <Broadcast size={15} aria-hidden="true" /> Publish due
      </button>
      {message && (
        <div className={message.error ? 'toast toast-error' : 'toast'} role="status">
          {message.text}
        </div>
      )}
    </div>
  )
}
