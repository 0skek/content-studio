import { useEffect, useState } from 'react'
import { api, errorText, isGenerating, type Brief, type Channel, type Language, type Post } from '../api'
import { PostCard } from './PostCard'

const POLL_INTERVAL_MS = 2000

interface BriefViewProps {
  briefId: number
  channels: Channel[]
}

// One channel/language slot: its newest post plus the older posts it replaced through retries.
// Retries always get higher ids and each post is retried at most once, so id order is the chain order.
function slotPosts(brief: Brief, channelId: string, language: Language): { current: Post; earlier: Post[] } | null {
  const posts = brief.posts
    .filter((post) => post.channel === channelId && post.language === language)
    .sort((first, second) => first.id - second.id)
  if (posts.length === 0) return null
  return { current: posts[posts.length - 1], earlier: posts.slice(0, -1) }
}

// Mount with key={briefId} so switching briefs starts from a clean state.
export function BriefView({ briefId, channels }: BriefViewProps) {
  const [brief, setBrief] = useState<Brief | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Bumped after approve/discard/retry to reload now (and resume polling if something is generating).
  const [reloadToken, setReloadToken] = useState(0)

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
  }, [briefId, reloadToken])

  if (!brief) return <section className="brief-view">{error ? <p className="error">{error}</p> : <p>Loading…</p>}</section>

  const reload = () => setReloadToken((token) => token + 1)
  const currentPosts = channels.flatMap((channel) =>
    brief.languages.flatMap((language) => slotPosts(brief, channel.id, language)?.current ?? []),
  )
  const countWhere = (matches: (post: Post) => boolean) => currentPosts.filter(matches).length
  const generatingCount = countWhere(isGenerating)
  const failedCount = countWhere((post) => post.generation_status === 'failed')

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
          {countWhere((post) => post.status === 'approved')} approved · {countWhere((post) => post.status === 'draft')} drafts ·{' '}
          {countWhere((post) => post.status === 'discarded')} discarded
          {generatingCount > 0 && <span className="muted"> · {generatingCount} generating…</span>}
          {failedCount > 0 && <span className="error"> · {failedCount} failed</span>}
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
              const slot = slotPosts(brief, channel.id, language)
              return slot ? (
                <PostCard
                  key={slot.current.id}
                  post={slot.current}
                  channel={channel}
                  earlierVersions={slot.earlier}
                  onChanged={reload}
                />
              ) : null
            })}
          </div>
        </div>
      ))}
    </section>
  )
}
