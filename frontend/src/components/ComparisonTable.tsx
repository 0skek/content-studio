import type { Channel, Comparison, Language } from '../api'
import { formatCount, formatRate } from '../format'
import { ChannelIcon } from './Brand'

const LANGUAGE_LABELS: Record<Language, string> = { bn: 'বাংলা', en: 'English' }

interface ComparisonTableProps {
  comparison: Comparison
  channels: Channel[]
}

function Rate({ value, label, best }: { value: number | null; label: string; best: boolean }) {
  return (
    <div className={best ? 'rate best' : 'rate'}>
      <span className="rate-value mono">{formatRate(value)}</span>
      <span className="rate-label">{label}</span>
      {best && <span className="best-tag">Best</span>}
    </div>
  )
}

// Like-for-like: the same brief's post on each channel, side by side per language, compared by rates.
export function ComparisonTable({ comparison, channels }: ComparisonTableProps) {
  const channelName = (id: string) => channels.find((channel) => channel.id === id)?.display_name ?? id
  const hasPublished = comparison.rows.some((row) => Object.values(row.cells).some((cell) => cell !== null))
  if (!hasPublished) return null

  return (
    <section className="comparison" aria-labelledby="comparison-title">
      <header className="section-head">
        <h2 id="comparison-title">Performance across channels</h2>
        <p>
          The same brief in the same language, side by side. Ranked by rates, never raw totals: engagement ={' '}
          <span className="mono">{comparison.definitions.engagement_rate}</span>, click-through ={' '}
          <span className="mono">{comparison.definitions.click_through_rate}</span>.
        </p>
      </header>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Language</th>
              {comparison.channels.map((id) => (
                <th key={id} scope="col">
                  <span className="th-channel">
                    <ChannelIcon channel={id} size={16} />
                    {channelName(id)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comparison.rows.map((row) => (
              <tr key={row.language}>
                <th scope="row" lang={row.language}>
                  {LANGUAGE_LABELS[row.language]}
                </th>
                {comparison.channels.map((id) => {
                  const cell = row.cells[id]
                  if (!cell) {
                    return (
                      <td key={id} className="cell-empty">
                        Not published
                      </td>
                    )
                  }
                  return (
                    <td key={id}>
                      <Rate value={cell.engagement_rate} label="engagement" best={row.best_engagement_channel === id} />
                      <Rate value={cell.click_through_rate} label="click-through" best={row.best_click_channel === id} />
                      <div className="cell-detail mono">
                        #{cell.post_id} · {formatCount(cell.impressions)} impr · {formatCount(cell.engagements)} eng ·{' '}
                        {formatCount(cell.clicks)} clicks
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
                    <span className="cell-empty">—</span>
                  ) : (
                    <>
                      <Rate value={summary.engagement_rate} label="engagement" best={false} />
                      <Rate value={summary.click_through_rate} label="click-through" best={false} />
                      <div className="cell-detail mono">
                        {summary.post_ids.map((id) => `#${id}`).join(' ')} · {formatCount(summary.impressions)} impr
                      </div>
                    </>
                  )}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  )
}
