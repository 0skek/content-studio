import { useEffect, useState } from 'react'
import {
  api,
  errorText,
  type Channel,
  type Evidence,
  type EvidenceBucket,
  type EvidenceGroup,
  type EvidencePost,
  type Language,
  type Report,
  type ReportClaim,
} from '../api'
import { formatCount, formatRate } from '../format'
import { GroupedBarChart, type ChartSeries, type ChartValue } from './charts/GroupedBarChart'

const LANGUAGE_LABELS: Record<Language, string> = { bn: 'Bengali', en: 'English' }
const LANGUAGE_SERIES: ChartSeries[] = [
  { key: 'bn', label: 'Bengali', color: 'var(--series-1)' },
  { key: 'en', label: 'English', color: 'var(--series-2)' },
]
const HASHTAG_SERIES: ChartSeries[] = [
  { key: 'few_hashtags', label: '0–3 hashtags', color: 'var(--series-3)' },
  { key: 'many_hashtags', label: '4+ hashtags', color: 'var(--series-4)' },
]
const LENGTH_SERIES: ChartSeries[] = [
  { key: 'short', label: 'Short (≤ 140 chars)', color: 'var(--series-3)' },
  { key: 'long', label: 'Long (> 140 chars)', color: 'var(--series-4)' },
]
const ELAPSED_TICK_MS = 1000
// Past this many citations, the rest fold into a "+N more" chip (hover lists them); the table has them all.
const MAX_CITATION_CHIPS = 6
const MILLISECONDS_PER_SECOND = 1000

interface ReportsViewProps {
  channels: Channel[]
  // Changes when reports were removed elsewhere (deleting a brief deletes reports citing its posts).
  reportsVersion: number
  // The view stays mounted while hidden; it reloads the list each time it is shown.
  visible: boolean
  // Called after a report is saved or deleted, so the brief form offers the latest insights.
  onReportsChanged: () => void
  // Lets the header show that a report is being written while another tab is open.
  onGeneratingChange: (generating: boolean) => void
}

function percent(rate: number): string {
  return formatRate(rate)
}

// "First sentence. The rest." -> a bold lead sentence, so each finding can be skimmed.
function splitLead(text: string): [string, string] {
  const match = text.trim().match(/^(.+?[.!?])\s+(.+)$/s)
  return match ? [match[1], match[2]] : [text.trim(), '']
}

function pooledRate(posts: EvidencePost[], pick: (post: EvidencePost) => number): number | null {
  const impressions = posts.reduce((sum, post) => sum + post.impressions, 0)
  return impressions > 0 ? posts.reduce((sum, post) => sum + pick(post), 0) / impressions : null
}

function groupValue(group: EvidenceGroup | undefined, rate: 'engagement_rate' | 'click_through_rate'): ChartValue | null {
  const value = group?.[rate]
  if (!group || value === null || value === undefined) return null
  const posts = group.post_ids.length
  return { value, detail: `${posts} post${posts === 1 ? '' : 's'} · ${formatCount(group.impressions)} impressions` }
}

function Citations({ claim, postsById }: { claim: ReportClaim; postsById: Map<number, EvidencePost> }) {
  const shown = claim.post_ids.slice(0, MAX_CITATION_CHIPS)
  const folded = claim.post_ids.slice(MAX_CITATION_CHIPS)
  return (
    <span className="citations">
      {shown.map((postId) => {
        const post = postsById.get(postId)
        const title = post
          ? `Post #${postId}: ${post.channel} · ${LANGUAGE_LABELS[post.language]} · ${formatRate(post.engagement_rate)} engagement · ${post.brief_title}`
          : `Post #${postId}`
        return (
          <span key={postId} className="citation" title={title}>
            #{postId}
          </span>
        )
      })}
      {folded.length > 0 && (
        <span className="citation citation-more" title={`Also cites ${folded.map((postId) => `#${postId}`).join(', ')}`}>
          +{folded.length} more
        </span>
      )}
    </span>
  )
}

function StatTiles({ evidence, channelName }: { evidence: Evidence; channelName: (id: string) => string }) {
  const posts = evidence.posts
  const bestChannel = evidence.groups
    .filter((group) => group.kind === 'channel' && group.engagement_rate !== null)
    .sort((first, second) => (second.engagement_rate ?? 0) - (first.engagement_rate ?? 0))[0]
  const engagement = pooledRate(posts, (post) => post.engagements)
  const clicks = pooledRate(posts, (post) => post.clicks)
  return (
    <div className="stat-tiles">
      <div className="stat-tile">
        <span className="stat-label">Posts published</span>
        <span className="stat-value">{posts.length}</span>
      </div>
      <div className="stat-tile">
        <span className="stat-label">Impressions</span>
        <span className="stat-value">{formatCount(posts.reduce((sum, post) => sum + post.impressions, 0))}</span>
      </div>
      <div className="stat-tile">
        <span className="stat-label">Engagement rate</span>
        <span className="stat-value">{formatRate(engagement)}</span>
      </div>
      <div className="stat-tile">
        <span className="stat-label">Click-through rate</span>
        <span className="stat-value">{formatRate(clicks)}</span>
      </div>
      {bestChannel && (
        <div className="stat-tile">
          <span className="stat-label">Most engaging channel</span>
          <span className="stat-value">{channelName(bestChannel.channel)}</span>
          <span className="stat-note">{formatRate(bestChannel.engagement_rate)} engagement rate</span>
        </div>
      )}
    </div>
  )
}

function Charts({ evidence, channels }: { evidence: Evidence; channels: Channel[] }) {
  const reported = channels.filter((channel) => evidence.groups.some((group) => group.channel === channel.id))
  const categories = reported.map((channel) => ({ key: channel.id, label: channel.display_name }))
  const find = (kind: EvidenceGroup['kind'], channel: string, match: (group: EvidenceGroup) => boolean) =>
    evidence.groups.find((group) => group.kind === kind && group.channel === channel && match(group))
  const byLanguage = (channel: string, language: string) =>
    find('channel_language', channel, (group) => group.language === language)
  const byBucket = (kind: EvidenceGroup['kind'], channel: string, bucket: string) =>
    find(kind, channel, (group) => group.bucket === (bucket as EvidenceBucket))

  return (
    <div className="viz-root chart-grid">
      <GroupedBarChart
        title="Engagement rate by channel and language"
        subtitle="(likes + comments + shares) ÷ impressions, pooled over the week's posts"
        categories={categories}
        series={LANGUAGE_SERIES}
        valueOf={(channel, language) => groupValue(byLanguage(channel, language), 'engagement_rate')}
        format={percent}
      />
      <GroupedBarChart
        title="Click-through rate by channel and language"
        subtitle="clicks ÷ impressions"
        categories={categories}
        series={LANGUAGE_SERIES}
        valueOf={(channel, language) => groupValue(byLanguage(channel, language), 'click_through_rate')}
        format={percent}
      />
      <GroupedBarChart
        title="Hashtag count and engagement rate"
        subtitle="Do more hashtags help? Posts grouped by how many hashtags they carried"
        categories={categories}
        series={HASHTAG_SERIES}
        valueOf={(channel, bucket) => groupValue(byBucket('channel_hashtags', channel, bucket), 'engagement_rate')}
        format={percent}
      />
      <GroupedBarChart
        title="Post length and click-through rate"
        subtitle="Caption plus hashtags, counted the way each channel counts"
        categories={categories}
        series={LENGTH_SERIES}
        valueOf={(channel, bucket) => groupValue(byBucket('channel_length', channel, bucket), 'click_through_rate')}
        format={percent}
      />
    </div>
  )
}

function EvidenceTable({ report, channelName }: { report: Report; channelName: (id: string) => string }) {
  if (!report.evidence) return null
  const cited = new Set(report.cited_post_ids)
  const rows = [...report.evidence.posts].sort((first, second) => (second.engagement_rate ?? 0) - (first.engagement_rate ?? 0))
  return (
    <details className="evidence">
      <summary>All {rows.length} posts behind this report</summary>
      <table>
        <thead>
          <tr>
            <th scope="col">Post</th>
            <th scope="col">Channel</th>
            <th scope="col">Language</th>
            <th scope="col">Brief</th>
            <th scope="col" className="numeric">Impressions</th>
            <th scope="col" className="numeric">Engagement</th>
            <th scope="col" className="numeric">Click-through</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((post) => (
            <tr key={post.post_id}>
              <td>
                #{post.post_id}
                {cited.has(post.post_id) && <span className="cited-tag">cited</span>}
              </td>
              <td>{channelName(post.channel)}</td>
              <td>{LANGUAGE_LABELS[post.language]}</td>
              <td>{post.brief_title}</td>
              <td className="numeric">{formatCount(post.impressions)}</td>
              <td className="numeric">{formatRate(post.engagement_rate)}</td>
              <td className="numeric">{formatRate(post.click_through_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

function ReportCard({ report, channels, onDelete }: { report: Report; channels: Channel[]; onDelete: (report: Report) => void }) {
  const { summary, findings, insights } = report.content
  const postsById = new Map((report.evidence?.posts ?? []).map((post) => [post.post_id, post]))
  const channelName = (id: string) => channels.find((channel) => channel.id === id)?.display_name ?? id
  return (
    <article className="report-card">
      <header className="report-head">
        <div>
          <h3>Weekly report #{report.id}</h3>
          <p className="muted small">
            Week from {report.week_start} · cites {report.cited_post_ids.length} posts, every one checked against the
            week's published posts
          </p>
        </div>
        <button type="button" className="delete-button" onClick={() => onDelete(report)}>
          Delete report
        </button>
      </header>

      {report.evidence && <StatTiles evidence={report.evidence} channelName={channelName} />}

      <div className="report-summary">
        <span className="section-label">Summary</span>
        <p>
          {summary.text} <Citations claim={summary} postsById={postsById} />
        </p>
      </div>

      {report.evidence && <Charts evidence={report.evidence} channels={channels} />}

      <section className="report-section">
        <h4>Findings</h4>
        <ol className="findings">
          {findings.map((finding) => {
            const [lead, rest] = splitLead(finding.text)
            return (
              <li key={finding.text}>
                <strong>{lead}</strong> {rest} <Citations claim={finding} postsById={postsById} />
              </li>
            )
          })}
        </ol>
      </section>

      <section className="report-section do-next">
        <h4>Do next: insights for the next brief</h4>
        <ul>
          {insights.map((insight) => {
            const [lead, rest] = splitLead(insight.text)
            return (
              <li key={insight.text}>
                <span className="do-next-icon" aria-hidden="true">
                  →
                </span>
                <span>
                  <strong>{lead}</strong> {rest} <Citations claim={insight} postsById={postsById} />
                </span>
              </li>
            )
          })}
        </ul>
        <p className="muted small">These appear on the New brief form, ticked, and go into the generation prompts.</p>
      </section>

      <EvidenceTable report={report} channelName={channelName} />
    </article>
  )
}

function GeneratingPanel({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), ELAPSED_TICK_MS)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.round((now - startedAt) / MILLISECONDS_PER_SECOND))
  return (
    <div className="generating-panel" role="status" aria-live="polite">
      <div className="generating-bar" aria-hidden="true">
        <span />
      </div>
      <div className="generating-body">
        <span className="generating-spinner" aria-hidden="true" />
        <div>
          <p className="generating-title">Writing this week's report… {seconds}s</p>
          <p className="muted">This usually takes 10–60 seconds. You can switch tabs; it keeps going.</p>
          <ul className="generating-steps">
            <li>The last 7 days of published posts and their metrics are gathered in code.</li>
            <li>The AI writes a summary, findings and insights from those numbers.</li>
            <li>Every cited post ID is checked; if one is wrong, the AI rewrites the report (up to 3 tries).</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

// Weekly AI-written reports. Their insights appear on the brief form and go into the next brief's prompts.
export function ReportsView({ channels, reportsVersion, visible, onReportsChanged, onGeneratingChange }: ReportsViewProps) {
  const [reports, setReports] = useState<Report[] | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!visible) return
    api
      .listReports()
      .then(setReports)
      .catch((caught) => setError(errorText(caught)))
  }, [reportsVersion, visible])

  async function deleteReport(report: Report) {
    const confirmed = window.confirm(
      `Delete weekly report #${report.id}?\n\nIts ${report.insights.length} insights stop being offered on the brief form. ` +
        'Briefs that already applied them keep them.',
    )
    if (!confirmed) return
    try {
      await api.deleteReport(report.id)
      setReports((current) => (current ?? []).filter((kept) => kept.id !== report.id))
      onReportsChanged()
    } catch (caught) {
      setError(errorText(caught))
    }
  }

  async function generate() {
    setStartedAt(Date.now())
    onGeneratingChange(true)
    setError(null)
    try {
      const report = await api.generateReport()
      setReports((current) => [report, ...(current ?? [])])
      onReportsChanged()
    } catch (caught) {
      setError(errorText(caught))
    } finally {
      setStartedAt(null)
      onGeneratingChange(false)
    }
  }

  const generating = startedAt !== null
  return (
    <section className="reports">
      <header className="reports-header">
        <div>
          <h2>Weekly reports</h2>
          <p className="muted">
            Written by the AI from the last 7 days of published posts (demo clock). Every claim cites post IDs, checked
            in code. Insights feed the next brief.
          </p>
        </div>
        <button type="button" className="generate-report" disabled={generating} onClick={generate}>
          {generating ? (
            <>
              <span className="button-spinner" aria-hidden="true" /> Writing…
            </>
          ) : (
            'Generate this week’s report'
          )}
        </button>
      </header>

      {generating && <GeneratingPanel startedAt={startedAt} />}
      {error && (
        <div className="report-error" role="alert">
          <strong>The report could not be written.</strong> {error}
        </div>
      )}
      {reports && reports.length === 0 && !generating && <p className="muted">No reports yet.</p>}
      <div className={generating ? 'reports-list refreshing' : 'reports-list'}>
        {reports && reports.length > 0 && <ReportCard report={reports[0]} channels={channels} onDelete={deleteReport} />}
        {reports && reports.length > 1 && (
          <section className="older-reports">
            <h3>Earlier reports</h3>
            {reports.slice(1).map((report) => (
              <details key={report.id} className="older-report">
                <summary>
                  Weekly report #{report.id} · week from {report.week_start} · {report.content.findings.length} findings
                </summary>
                <ReportCard report={report} channels={channels} onDelete={deleteReport} />
              </details>
            ))}
          </section>
        )}
      </div>
    </section>
  )
}
