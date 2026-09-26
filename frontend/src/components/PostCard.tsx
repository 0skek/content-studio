import { useState } from 'react'
import { api, errorText, type Channel, type Language, type Post } from '../api'
import { ImageLightbox } from './ImageLightbox'

const LANGUAGE_LABELS: Record<Language, string> = { bn: 'বাংলা', en: 'English' }
const BYTES_PER_KILOBYTE = 1024
const BYTES_PER_MEGABYTE = BYTES_PER_KILOBYTE * 1024

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
}

export function PostCard({ post, channel, earlierVersions, onChanged }: PostCardProps) {
  const [enlargedPost, setEnlargedPost] = useState<Post | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

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
