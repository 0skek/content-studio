import type { Channel, Comparison, Language } from '../api'
import { formatCount, formatRate } from '../format'

const LANGUAGE_LABELS: Record<Language, string> = { bn: 'বাংলা', en: 'English' }

interface ComparisonTableProps {
  comparison: Comparison
  channels: Channel[]
}

// Like-for-like: the same brief's post on each channel, side by side per language, compared by rates.
export function ComparisonTable({ comparison, channels }: ComparisonTableProps) {
  const channelName = (id: string) => channels.find((channel) => channel.id === id)?.display_name ?? id
  const hasPublished = comparison.rows.some((row) => Object.values(row.cells).some((cell) => cell !== null))
  if (!hasPublished) return null

  return (
    <section className="comparison">
      <h3>Performance across channels</h3>
      <p className="muted">
        Same brief, same language, side by side. Ranked by rates, not totals: engagement rate ={' '}
        {comparison.definitions.engagement_rate}; click-through rate = {comparison.definitions.click_through_rate}. The
        best channel in each row is highlighted.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Language</th>
            {comparison.channels.map((id) => (
              <th key={id} scope="col">
                {channelName(id)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((row) => (
            <tr key={row.language}>
              <th scope="row">{LANGUAGE_LABELS[row.language]}</th>
              {comparison.channels.map((id) => {
                const cell = row.cells[id]
                if (!cell) {
                  return (
                    <td key={id} className="muted">
                      not published
                    </td>
                  )
                }
                const bestEngagement = row.best_engagement_channel === id
                const bestClicks = row.best_click_channel === id
                return (
                  <td key={id}>
                    <div className={bestEngagement ? 'rate best' : 'rate'}>
                      {formatRate(cell.engagement_rate)} <span className="muted">engagement</span>
                      {bestEngagement && <span className="best-tag">best</span>}
                    </div>
                    <div className={bestClicks ? 'rate best' : 'rate'}>
                      {formatRate(cell.click_through_rate)} <span className="muted">click-through</span>
                      {bestClicks && <span className="best-tag">best</span>}
                    </div>
                    <div className="muted small">
                      post #{cell.post_id} · {formatCount(cell.impressions)} impressions · {formatCount(cell.engagements)}{' '}
                      engagements · {formatCount(cell.clicks)} clicks
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
          <tr className="summary-row">
            <th scope="row">All languages</th>
            {comparison.channel_summaries.map((summary) => (
              <td key={summary.channel}>
                {summary.post_ids.length === 0 ? (
                  <span className="muted">—</span>
                ) : (
                  <>
                    <div className="rate">
                      {formatRate(summary.engagement_rate)} <span className="muted">engagement</span>
                    </div>
                    <div className="rate">
                      {formatRate(summary.click_through_rate)} <span className="muted">click-through</span>
                    </div>
                    <div className="muted small">
                      {summary.post_ids.map((id) => `#${id}`).join(', ')} · {formatCount(summary.impressions)} impressions
                    </div>
                  </>
                )}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </section>
  )
}
