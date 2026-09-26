import { useState } from 'react'
import type { Channel, Language, Post } from '../api'
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
}

export function PostCard({ post, channel }: PostCardProps) {
  const [enlarged, setEnlarged] = useState(false)
  const lengthUnit = channel.length_counting === 'x_weighted' ? 'weighted characters' : 'characters'
  const imageTitle = `${channel.display_name} · ${LANGUAGE_LABELS[post.language]} · post #${post.id} · ${post.width}×${post.height}`

  return (
    <article className={`post-card status-${post.generation_status}`} lang={post.language}>
      <header>
        <span>
          {channel.display_name} · {LANGUAGE_LABELS[post.language]} · post #{post.id}
        </span>
        <span className={`badge badge-${post.generation_status}`}>{post.generation_status}</span>
      </header>

      {post.generation_status === 'ready' && post.image_url ? (
        <button type="button" className="image-button" onClick={() => setEnlarged(true)} aria-label={`Enlarge image: ${imageTitle}`}>
          <img src={post.image_url} alt={post.headline ?? ''} width={post.width ?? undefined} height={post.height ?? undefined} />
        </button>
      ) : (
        <div className="image-placeholder" style={{ aspectRatio: `${channel.width} / ${channel.height}` }}>
          {post.generation_status === 'failed' ? 'No image' : <span className="spinner">Generating…</span>}
        </div>
      )}

      {post.generation_status === 'failed' && <p className="error">{post.generation_error}</p>}

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

      {enlarged && post.image_url && (
        <ImageLightbox src={post.image_url} alt={post.headline ?? ''} title={imageTitle} onClose={() => setEnlarged(false)} />
      )}
    </article>
  )
}
