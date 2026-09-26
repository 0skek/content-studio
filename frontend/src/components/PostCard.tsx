import { useState } from 'react'
import {
  ArrowCounterClockwise,
  Broadcast,
  CalendarBlank,
  Check,
  MagnifyingGlassPlus,
  WarningCircle,
  X,
} from '@phosphor-icons/react'
import { api, errorText, type Channel, type Language, type Post, type PostStatus, type TakenDown } from '../api'
import { useConfirm } from '../confirm'
import { formatCount, formatTime } from '../format'
import { confirmAndTakeDown } from '../takeDown'
import { ImageLightbox } from './ImageLightbox'

const LANGUAGE_LABELS: Record<Language, string> = { bn: 'বাংলা', en: 'English' }
const STATUS_LABELS: Record<PostStatus, string> = {
  draft: 'Draft',
  approved: 'Approved',
  discarded: 'Discarded',
  scheduled: 'Scheduled',
  published: 'Published',
  rejected: 'Rejected',
}
const BYTES_PER_KILOBYTE = 1024
const BYTES_PER_MEGABYTE = BYTES_PER_KILOBYTE * 1024
const MILLISECONDS_PER_HOUR = 60 * 60 * 1000
// Scheduling options, measured from the demo clock's "now" (which includes any fast-forward).
const SCHEDULE_OPTIONS = [
  { label: 'Now', hours: 0 },
  { label: 'In 1 hour', hours: 1 },
  { label: 'In 1 day', hours: 24 },
]
// A meter turns amber past this share of its limit, so a near miss is visible before the adapter sees it.
const NEAR_LIMIT_SHARE = 0.9

function formatFileSize(bytes: number): string {
  if (bytes >= BYTES_PER_MEGABYTE) return `${(bytes / BYTES_PER_MEGABYTE).toFixed(1)} MB`
  return `${Math.round(bytes / BYTES_PER_KILOBYTE)} KB`
}

function Meter({ label, value, limit }: { label: string; value: number; limit: number }) {
  const share = limit > 0 ? Math.min(1, value / limit) : 1
  const level = value > limit ? 'over' : share >= NEAR_LIMIT_SHARE ? 'near' : 'ok'
  return (
    <div className={`meter meter-${level}`}>
      <span className="meter-text">
        <span className="mono">
          {formatCount(value)}/{formatCount(limit)}
        </span>{' '}
        {label}
      </span>
      <span className="meter-track" aria-hidden="true">
        <span className="meter-fill" style={{ width: `${share * 100}%` }} />
      </span>
    </div>
  )
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
  const confirm = useConfirm()
  const [enlargedPost, setEnlargedPost] = useState<Post | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [scheduleHours, setScheduleHours] = useState(SCHEDULE_OPTIONS[1].hours)

  const lengthUnit = channel.length_counting === 'x_weighted' ? 'weighted chars' : 'chars'
  const ready = post.generation_status === 'ready'
  const failed = post.generation_status === 'failed'
  const isReadyDraft = post.status === 'draft' && ready
  const canRetry = post.status === 'discarded' || (post.status === 'draft' && failed)

  function imageTitle(shown: Post): string {
    return `${channel.display_name} · ${LANGUAGE_LABELS[shown.language]} · post #${shown.id} · ${shown.status} · ${shown.width}×${shown.height}`
  }

  async function runAction(action: () => Promise<unknown>) {
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

  async function handleDiscard() {
    const confirmed = await confirm({
      title: `Discard post #${post.id}?`,
      body: 'It stays in this slot’s history. Retry it afterwards to generate a new image and copy for this slot.',
      confirmLabel: 'Discard',
      tone: 'danger',
    })
    if (confirmed) runAction(() => api.discardPost(post.id))
  }

  function handleTakeDown() {
    runAction(async () => {
      const result = await confirmAndTakeDown(post.id, channel.display_name, confirm)
      if (result) onTakenDown(result)
    })
  }

  return (
    <article className={`post status-${post.status} gen-${post.generation_status}`}>
      <div className="post-media" style={{ aspectRatio: `${channel.width} / ${channel.height}` }}>
        {ready && post.image_url ? (
          <button
            type="button"
            className="post-image"
            onClick={() => setEnlargedPost(post)}
            aria-label={`Enlarge image: ${imageTitle(post)}`}
          >
            <img src={post.image_url} alt={post.headline ?? ''} width={post.width ?? undefined} height={post.height ?? undefined} />
            <span className="zoom-hint" aria-hidden="true">
              <MagnifyingGlassPlus size={16} weight="bold" />
            </span>
          </button>
        ) : failed ? (
          <div className="post-placeholder failed">
            <WarningCircle size={28} aria-hidden="true" />
            <span>Generation failed</span>
          </div>
        ) : (
          <div className="post-placeholder generating">
            <span className="spinner" aria-hidden="true" />
            <span>{post.generation_status === 'pending' ? 'Queued' : 'Generating image and copy'}</span>
          </div>
        )}
        <span className="post-lang" lang={post.language}>
          {LANGUAGE_LABELS[post.language]}
        </span>
      </div>

      <div className="post-body" lang={post.language}>
        <div className="post-status-row">
          <span className={`status status-${post.status}`}>
            <span className="dot" aria-hidden="true" />
            {STATUS_LABELS[post.status]}
          </span>
          <span className="post-id mono">
            #{post.id}
            {post.parent_post_id !== null && <span className="muted"> · retry of #{post.parent_post_id}</span>}
          </span>
        </div>

        {failed && <p className="card-error">{post.generation_error}</p>}

        {ready && (
          <>
            <h3 className="post-headline">{post.headline}</h3>
            <p className="post-caption">{post.caption}</p>
            {post.hashtags.length > 0 && <p className="post-tags">{post.hashtags.map((tag) => `#${tag}`).join(' ')}</p>}
            <div className="post-specs">
              <Meter label={lengthUnit} value={post.published_length} limit={channel.caption_max_chars} />
              <Meter label="hashtags" value={post.hashtags.length} limit={channel.max_hashtags} />
              <p className="spec-line mono">
                <span>
                  {post.width}×{post.height}
                </span>
                {post.file_size_bytes !== null && <span>{formatFileSize(post.file_size_bytes)}</span>}
              </p>
            </div>
          </>
        )}

        {post.status === 'scheduled' && post.scheduled_at && (
          <p className="publish-state scheduled">
            <CalendarBlank size={16} aria-hidden="true" /> Publishes {formatTime(post.scheduled_at)}
          </p>
        )}
        {post.status === 'published' && post.published_at && (
          <p className="publish-state published">
            <Broadcast size={16} aria-hidden="true" /> Live on {channel.display_name} since {formatTime(post.published_at)}
          </p>
        )}
        {post.status === 'rejected' && (
          <p className="card-error">
            <strong>Rejected by the {channel.display_name} adapter:</strong> {post.rejection_reason}
          </p>
        )}
        {actionError && (
          <p className="card-error" role="alert">
            {actionError}
          </p>
        )}
      </div>

      {post.status === 'approved' && (
        <footer className="post-actions">
          <div className="segmented" role="radiogroup" aria-label="When to publish">
            {SCHEDULE_OPTIONS.map((option) => (
              <label key={option.label} className="segment">
                <input
                  type="radio"
                  name={`schedule-${post.id}`}
                  checked={scheduleHours === option.hours}
                  disabled={busy}
                  onChange={() => setScheduleHours(option.hours)}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => runAction(schedule)}>
            <CalendarBlank size={16} aria-hidden="true" /> Schedule
          </button>
        </footer>
      )}

      {isReadyDraft && (
        <footer className="post-actions">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={handleDiscard}>
            <X size={16} aria-hidden="true" /> Discard
          </button>
          <button type="button" className="btn btn-approve" disabled={busy} onClick={() => runAction(() => api.approvePost(post.id))}>
            <Check size={16} weight="bold" aria-hidden="true" /> Approve
          </button>
        </footer>
      )}

      {canRetry && (
        <footer className="post-actions">
          <button type="button" className="btn btn-secondary btn-block" disabled={busy} onClick={() => runAction(() => api.retryPost(post.id))}>
            <ArrowCounterClockwise size={16} aria-hidden="true" /> {busy ? 'Starting…' : 'Retry this slot'}
          </button>
        </footer>
      )}

      {post.status === 'published' && (
        <footer className="post-actions">
          <button type="button" className="btn btn-ghost btn-danger-ghost btn-block" disabled={busy} onClick={handleTakeDown}>
            Take down
          </button>
        </footer>
      )}

      {earlierVersions.length > 0 && (
        <div className="post-history">
          <p className="history-label">Earlier versions</p>
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
                <span className="history-meta mono">
                  #{version.id} · {version.generation_status === 'failed' ? 'failed' : version.status}
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
