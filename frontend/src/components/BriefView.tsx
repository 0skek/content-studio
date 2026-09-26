import { useEffect, useState } from 'react'
import { Lightbulb, Trash, WarningCircle } from '@phosphor-icons/react'
import {
  api,
  errorText,
  isGenerating,
  type Brief,
  type Channel,
  type Comparison,
  type DeletedBrief,
  type Language,
  type Post,
  type TakenDown,
} from '../api'
import { useConfirm } from '../confirm'
import { formatCount, formatTime } from '../format'
import { ChannelIcon } from './Brand'
import { ComparisonTable } from './ComparisonTable'
import { PostCard } from './PostCard'

const POLL_INTERVAL_MS = 2000

interface BriefViewProps {
  briefId: number
  channels: Channel[]
  // Changes when something outside this view (the clock bar) published posts.
  refreshToken: number
  onDeleted: (deleted: DeletedBrief) => void
  onTakenDown: (result: TakenDown) => void
}

// Keep polling while the background job generates or the background scheduler may publish.
function needsPolling(post: Post): boolean {
  return isGenerating(post) || post.status === 'scheduled'
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

// Where each current post is in the pipeline. Generation problems count before post status.
type Stage = 'generating' | 'failed' | 'draft' | 'approved' | 'scheduled' | 'published' | 'rejected' | 'discarded'
const STAGES: { stage: Stage; label: string }[] = [
  { stage: 'generating', label: 'Generating' },
  { stage: 'draft', label: 'Drafts' },
  { stage: 'approved', label: 'Approved' },
  { stage: 'scheduled', label: 'Scheduled' },
  { stage: 'published', label: 'Published' },
  { stage: 'failed', label: 'Failed' },
  { stage: 'rejected', label: 'Rejected' },
  { stage: 'discarded', label: 'Discarded' },
]
// Always shown, even at zero, so the pipeline reads left to right; the others appear only when they happen.
const MAIN_STAGES: Stage[] = ['draft', 'approved', 'scheduled', 'published']

function stageOf(post: Post): Stage {
  if (isGenerating(post)) return 'generating'
  if (post.generation_status === 'failed' && post.status === 'draft') return 'failed'
  return post.status
}

function Pipeline({ posts }: { posts: Post[] }) {
  const counts = new Map<Stage, number>()
  for (const post of posts) counts.set(stageOf(post), (counts.get(stageOf(post)) ?? 0) + 1)
  const shown = STAGES.filter(({ stage }) => MAIN_STAGES.includes(stage) || (counts.get(stage) ?? 0) > 0)
  return (
    <section className="pipeline" aria-label="Where this brief's posts are">
      <div className="pipeline-bar" aria-hidden="true">
        {STAGES.map(({ stage }) =>
          (counts.get(stage) ?? 0) > 0 ? (
            <span key={stage} className={`pipeline-seg stage-${stage}`} style={{ flexGrow: counts.get(stage) }} />
          ) : null,
        )}
      </div>
      <ol className="pipeline-stages">
        {shown.map(({ stage, label }) => (
          <li key={stage} className={`stage-${stage}`} data-empty={(counts.get(stage) ?? 0) === 0 || undefined}>
            <span className="pipeline-count">{counts.get(stage) ?? 0}</span>
            <span className="pipeline-label">
              <span className="dot" aria-hidden="true" />
              {label}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function BriefSkeleton() {
  return (
    <div className="brief-skeleton" aria-hidden="true">
      <div className="skeleton skeleton-line short" />
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-line" />
      <div className="skeleton-cards">
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    </div>
  )
}

// Mount with key={briefId} so switching briefs starts from a clean state.
export function BriefView({ briefId, channels, refreshToken, onDeleted, onTakenDown }: BriefViewProps) {
  const confirm = useConfirm()
  const [brief, setBrief] = useState<Brief | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Bumped after approve/discard/retry to reload now (and resume polling if something is generating).
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    let pollTimer: number | undefined

    async function load() {
      try {
        const loaded = await api.getBrief(briefId)
        const hasPublished = loaded.posts.some((post) => post.status === 'published')
        const loadedComparison = hasPublished ? await api.getComparison(briefId) : null
        if (cancelled) return
        setBrief(loaded)
        setComparison(loadedComparison)
        setError(null)
        if (loaded.posts.some(needsPolling)) pollTimer = window.setTimeout(load, POLL_INTERVAL_MS)
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
  }, [briefId, reloadToken, refreshToken])

  if (!brief) {
    return error ? (
      <p className="form-error" role="alert">
        {error}
      </p>
    ) : (
      <BriefSkeleton />
    )
  }

  const reload = () => setReloadToken((token) => token + 1)

  async function handleDelete() {
    if (!brief) return
    const confirmed = await confirm({
      title: `Delete brief #${brief.id}?`,
      body: (
        <>
          <p>
            <strong>{brief.title}</strong>
          </p>
          <p>
            This removes its {brief.posts.length} posts (retries included), their images and metrics, and any weekly
            report that cites them. It can't be undone.
          </p>
        </>
      ),
      confirmLabel: 'Delete brief',
      tone: 'danger',
    })
    if (!confirmed) return
    try {
      onDeleted(await api.deleteBrief(brief.id))
    } catch (caught) {
      setError(errorText(caught))
    }
  }

  const currentPosts = channels.flatMap((channel) =>
    brief.languages.flatMap((language) => slotPosts(brief, channel.id, language)?.current ?? []),
  )
  const generatingCount = currentPosts.filter(isGenerating).length

  return (
    <article className="brief">
      <header className="brief-head">
        <div className="brief-head-top">
          <p className="eyebrow">
            <span className="mono">Brief #{brief.id}</span> · created {formatTime(brief.created_at)}
          </p>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-danger-ghost"
            onClick={handleDelete}
            disabled={generatingCount > 0}
            title={generatingCount > 0 ? 'Wait for generation to finish before deleting' : 'Delete this brief and everything built from it'}
          >
            <Trash size={14} aria-hidden="true" /> Delete brief
          </button>
        </div>
        <h1 className="brief-title">{brief.title}</h1>
        <dl className="brief-facts">
          <div className="fact-goal">
            <dt>Goal</dt>
            <dd>{brief.goal}</dd>
          </div>
          <div>
            <dt>Audience</dt>
            <dd>{brief.audience}</dd>
          </div>
          <div>
            <dt>Tone</dt>
            <dd>{brief.tone}</dd>
          </div>
        </dl>
        {brief.insights_used.length > 0 && (
          <details className="applied-insights">
            <summary>
              <Lightbulb size={16} weight="duotone" aria-hidden="true" />
              {brief.insights_used.length} insight{brief.insights_used.length === 1 ? '' : 's'} from report #
              {brief.insights_used[0].report_id} steered this brief
            </summary>
            <ul>
              {brief.insights_used.map((insight) => (
                <li key={insight.id}>{insight.text}</li>
              ))}
            </ul>
          </details>
        )}
      </header>

      <Pipeline posts={currentPosts} />
      {error && (
        <p className="form-error" role="alert">
          <WarningCircle size={16} weight="bold" aria-hidden="true" /> {error}
        </p>
      )}

      {channels.map((channel) => {
        const orientation = channel.width >= channel.height ? 'landscape' : 'portrait'
        return (
          <section key={channel.id} className="channel-section" aria-labelledby={`channel-${channel.id}`}>
            <header className="channel-head">
              <h2 id={`channel-${channel.id}`}>
                <ChannelIcon channel={channel.id} size={20} />
                {channel.display_name}
              </h2>
              <p className="spec-line mono">
                <span>
                  {channel.width}×{channel.height}
                </span>
                <span>{channel.aspect_ratio}</span>
                <span>≤ {channel.max_file_size_mb} MB</span>
                <span>≤ {formatCount(channel.caption_max_chars)} chars</span>
                <span>≤ {channel.max_hashtags} tags</span>
              </p>
            </header>
            <div className={`post-grid post-grid-${orientation}`}>
              {brief.languages.map((language) => {
                const slot = slotPosts(brief, channel.id, language)
                return slot ? (
                  <PostCard
                    key={slot.current.id}
                    post={slot.current}
                    channel={channel}
                    earlierVersions={slot.earlier}
                    onChanged={reload}
                    onTakenDown={onTakenDown}
                  />
                ) : null
              })}
            </div>
          </section>
        )
      })}

      {comparison && <ComparisonTable comparison={comparison} channels={channels} />}
    </article>
  )
}
