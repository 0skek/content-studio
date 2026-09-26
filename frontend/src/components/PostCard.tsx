import { useState } from 'react'
import { api, errorText, type Channel, type Language, type Post, type TakenDown } from '../api'
import { formatTime } from '../format'
import { confirmAndTakeDown } from '../takeDown'
import { ImageLightbox } from './ImageLightbox'

const LANGUAGE_LABELS: Record<Language, string> = { bn: 'বাংলা', en: 'English' }
const BYTES_PER_KILOBYTE = 1024
const BYTES_PER_MEGABYTE = BYTES_PER_KILOBYTE * 1024
const MILLISECONDS_PER_HOUR = 60 * 60 * 1000
// Scheduling options, measured from the demo clock's "now" (which includes any fast-forward).
const SCHEDULE_OPTIONS = [
  { label: 'now', hours: 0 },
  { label: 'in 1 hour', hours: 1 },
  { label: 'in 1 day', hours: 24 },
]

function formatFileSize(bytes: number): string {
  if (bytes >= BYTES_PER_MEGABYTE) return `${(bytes / BYTES_PER_MEGABYTE).toFixed(1)} MB`
  return `${Math.round(bytes / BYTES_PER_KILOBYTE)} KB`
}

interface PostCardProps {
  post: Post
  channel: Channel
  // Older posts in this slot's retry chain, oldest first.
  earlierVersions: Post[]
  // Called after an approve/discard/retry so the brief reloads.
  onChanged: () => void
  // Called after a take-down, which may also have deleted reports.
  onTakenDown: (result: TakenDown) => void
}

export function PostCard({ post, channel, earlierVersions, onChanged, onTakenDown }: PostCardProps) {
  const [enlargedPost, setEnlargedPost] = useState<Post | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [scheduleHours, setScheduleHours] = useState(SCHEDULE_OPTIONS[1].hours)

  const lengthUnit = channel.length_counting === 'x_weighted' ? 'weighted characters' : 'characters'
  const isReadyDraft = post.status === 'draft' && post.generation_status === 'ready'
  const canRetry = post.status === 'discarded' || (post.status === 'draft' && post.generation_status === 'failed')

  function imageTitle(shown: Post): string {
    return `${channel.display_name} · ${LANGUAGE_LABELS[shown.language]} · post #${shown.id} · ${shown.status} · ${shown.width}×${shown.height}`
  }

  async function runAction(action: () => Promise<Post>) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      onChanged()
    } catch (caught) {
      setActionError(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function schedule() {
    const clock = await api.getClock()
    const scheduledAt = new Date(new Date(clock.now).getTime() + scheduleHours * MILLISECONDS_PER_HOUR)
    return api.schedulePost(post.id, scheduledAt)
  }

  function handleDiscard() {
    if (window.confirm(`Discard post #${post.id}? You can retry it afterwards to get a new version.`)) {
      runAction(() => api.discardPost(post.id))
    }
  }

  return (
    <article className={`post-card status-${post.status} generation-${post.generation_status}`} lang={post.language}>
      <header>
        <span>
          {channel.display_name} · {LANGUAGE_LABELS[post.language]} · post #{post.id}
          {post.parent_post_id !== null && <span className="muted"> · retry of #{post.parent_post_id}</span>}
        </span>
        <span className="badges">
          <span className={`badge badge-status-${post.status}`}>{post.status}</span>
          <span className={`badge badge-${post.generation_status}`}>{post.generation_status}</span>
        </span>
      </header>

      {post.generation_status === 'ready' && post.image_url ? (
        <button type="button" className="image-button" onClick={() => setEnlargedPost(post)} aria-label={`Enlarge image: ${imageTitle(post)}`}>
          <img src={post.image_url} alt={post.headline ?? ''} width={post.width ?? undefined} height={post.height ?? undefined} />
        </button>
      ) : (
        <div className="image-placeholder" style={{ aspectRatio: `${channel.width} / ${channel.height}` }}>
          {post.generation_status === 'failed' ? 'No image' : <span className="spinner">Generating…</span>}
        </div>
      )}

      {post.generation_status === 'failed' && <p className="error card-message">{post.generation_error}</p>}

      {post.generation_status === 'ready' && (
        <div className="post-copy">
          <p className="headline">{post.headline}</p>
          <p className="caption">{post.caption}</p>
          <p className="hashtags">{post.hashtags.map((tag) => `#${tag}`).join(' ')}</p>
          <p className="meta">
            {post.width}×{post.height} · {post.file_size_bytes !== null && formatFileSize(post.file_size_bytes)} ·{' '}
            {post.published_length}/{channel.caption_max_chars} {lengthUnit} · {post.hashtags.length}/{channel.max_hashtags}{' '}
            hashtags
          </p>
        </div>
      )}

      {post.status === 'scheduled' && post.scheduled_at && (
        <p className="publish-state">Scheduled for {formatTime(post.scheduled_at)}</p>
      )}
      {post.status === 'published' && post.published_at && (
        <div className="publish-row">
          <p className="publish-state published">Published by the {channel.display_name} adapter · {formatTime(post.published_at)}</p>
          <button
            type="button"
            className="delete-button small-button"
            disabled={busy}
            onClick={() =>
              runAction(async () => {
                const result = await confirmAndTakeDown(post.id, channel.display_name)
                if (result) onTakenDown(result)
                return result?.post ?? post
              })
            }
          >
            Take down
          </button>
        </div>
      )}
      {post.status === 'rejected' && (
        <p className="error card-message">
          Rejected by the {channel.display_name} adapter: {post.rejection_reason}
        </p>
      )}

      {post.status === 'approved' && (
        <div className="post-actions">
          <select
            aria-label="When to publish"
            value={scheduleHours}
            disabled={busy}
            onChange={(event) => setScheduleHours(Number(event.target.value))}
          >
            {SCHEDULE_OPTIONS.map((option) => (
              <option key={option.label} value={option.hours}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="button" className="approve" disabled={busy} onClick={() => runAction(schedule)}>
            Schedule
          </button>
        </div>
      )}

      {(isReadyDraft || canRetry) && (
        <div className="post-actions">
          {isReadyDraft && (
            <>
              <button type="button" className="approve" disabled={busy} onClick={() => runAction(() => api.approvePost(post.id))}>
                Approve
              </button>
              <button type="button" className="discard" disabled={busy} onClick={handleDiscard}>
                Discard
              </button>
            </>
          )}
          {canRetry && (
            <button type="button" className="retry" disabled={busy} onClick={() => runAction(() => api.retryPost(post.id))}>
              {busy ? 'Starting…' : 'Retry'}
            </button>
          )}
        </div>
      )}
      {actionError && <p className="error card-message">{actionError}</p>}

      {earlierVersions.length > 0 && (
        <div className="earlier-versions">
          <p className="muted">Earlier versions</p>
          <ul>
            {earlierVersions.map((version) => (
              <li key={version.id}>
                {version.image_url ? (
                  <button
                    type="button"
                    className="thumbnail"
                    onClick={() => setEnlargedPost(version)}
                    aria-label={`Enlarge image: ${imageTitle(version)}`}
                  >
                    <img src={version.image_url} alt="" />
                  </button>
                ) : (
                  <span className="thumbnail thumbnail-empty">no image</span>
                )}
                <span className="muted">
                  #{version.id} · {version.status}
                  {version.generation_status === 'failed' && ' (generation failed)'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {enlargedPost?.image_url && (
        <ImageLightbox
          src={enlargedPost.image_url}
          alt={enlargedPost.headline ?? ''}
          title={imageTitle(enlargedPost)}
          onClose={() => setEnlargedPost(null)}
        />
      )}
    </article>
  )
}
