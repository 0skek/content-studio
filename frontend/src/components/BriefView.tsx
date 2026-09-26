import { useEffect, useState } from 'react'
import { api, errorText, isGenerating, type Brief, type Channel } from '../api'
import { PostCard } from './PostCard'

const POLL_INTERVAL_MS = 2000

interface BriefViewProps {
  briefId: number
  channels: Channel[]
}

// Mount with key={briefId} so switching briefs starts from a clean state.
export function BriefView({ briefId, channels }: BriefViewProps) {
  const [brief, setBrief] = useState<Brief | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let pollTimer: number | undefined

    async function load() {
      try {
        const loaded = await api.getBrief(briefId)
        if (cancelled) return
        setBrief(loaded)
        setError(null)
        if (loaded.posts.some(isGenerating)) pollTimer = window.setTimeout(load, POLL_INTERVAL_MS)
      } catch (caught) {
        if (cancelled) return
        setError(errorText(caught))
        pollTimer = window.setTimeout(load, POLL_INTERVAL_MS)
      }
    }

    load()
    return () => {
      cancelled = true
      window.clearTimeout(pollTimer)
    }
  }, [briefId])

  if (!brief) return <section className="brief-view">{error ? <p className="error">{error}</p> : <p>Loading…</p>}</section>

  const readyCount = brief.posts.filter((post) => post.generation_status === 'ready').length
  const failedCount = brief.posts.filter((post) => post.generation_status === 'failed').length

  return (
    <section className="brief-view">
      <header className="brief-header">
        <h2>
          #{brief.id} {brief.title}
        </h2>
        <dl>
          <dt>Goal</dt>
          <dd>{brief.goal}</dd>
          <dt>Audience</dt>
          <dd>{brief.audience}</dd>
          <dt>Tone</dt>
          <dd>{brief.tone}</dd>
        </dl>
        <p className="progress">
          {readyCount} of {brief.posts.length} ready
          {failedCount > 0 && <span className="error"> · {failedCount} failed</span>}
          {brief.posts.some(isGenerating) && <span className="muted"> · generating…</span>}
        </p>
        {error && <p className="error">{error}</p>}
      </header>

      {channels.map((channel) => (
        <div key={channel.id} className="channel-row">
          <h3>
            {channel.display_name}{' '}
            <span className="muted">
              {channel.width}×{channel.height} · {channel.aspect_ratio}
            </span>
          </h3>
          <div className="channel-posts">
            {brief.languages.map((language) => {
              const post = brief.posts.find((candidate) => candidate.channel === channel.id && candidate.language === language)
              return post ? <PostCard key={post.id} post={post} channel={channel} /> : null
            })}
          </div>
        </div>
      ))}
    </section>
  )
}
