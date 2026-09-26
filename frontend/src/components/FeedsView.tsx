import { useEffect, useState } from 'react'
import { api, errorText, type Channel, type FeedPost, type TakenDown } from '../api'
import { formatCount, formatTime } from '../format'
import { confirmAndTakeDown, takeDownSummary } from '../takeDown'

const FEED_REFRESH_MS = 5000
const MOCK_ACCOUNT_NAME = 'Your Brand'
const MOCK_HANDLE = '@yourbrand'

interface FeedsViewProps {
  channels: Channel[]
  // Changes when the clock bar published posts or ingested metrics.
  refreshToken: number
  // Called after a post is taken down, so the brief view and reports catch up.
  onTakenDown: (result: TakenDown) => void
}

function hashtagLine(item: FeedPost): string {
  return item.post.hashtags.map((tag) => `#${tag}`).join(' ')
}

function Stats({ item, labels }: { item: FeedPost; labels: [string, string, string, string] }) {
  const { likes, comments, shares, impressions } = item.performance
  const [likeLabel, commentLabel, shareLabel, viewLabel] = labels
  return (
    <p className="feed-stats">
      <span>
        {formatCount(likes)} {likeLabel}
      </span>
      <span>
        {formatCount(comments)} {commentLabel}
      </span>
      <span>
        {formatCount(shares)} {shareLabel}
      </span>
      <span>
        {formatCount(impressions)} {viewLabel}
      </span>
    </p>
  )
}

type TakeDownHandler = (item: FeedPost) => void

function Footer({ item, onTakeDown }: { item: FeedPost; onTakeDown: TakeDownHandler }) {
  return (
    <div className="feed-footer">
      <p className="muted">
        post #{item.post.id} · {item.brief_title} · published {item.post.published_at && formatTime(item.post.published_at)} via
        the mock adapter
      </p>
      <button type="button" className="delete-button small-button" onClick={() => onTakeDown(item)}>
        Take down
      </button>
    </div>
  )
}

function InstagramPost({ item, onTakeDown }: { item: FeedPost; onTakeDown: TakeDownHandler }) {
  return (
    <article className="feed-post instagram" lang={item.post.language}>
      <header className="feed-author">
        <span className="avatar" aria-hidden="true" />
        <strong>{MOCK_HANDLE.slice(1)}</strong>
      </header>
      {item.post.image_url && <img src={item.post.image_url} alt={item.post.headline ?? ''} />}
      <Stats item={item} labels={['♥ likes', '💬 comments', '↗ shares', 'views']} />
      <p className="feed-text">
        <strong>{MOCK_HANDLE.slice(1)}</strong> {item.post.caption}
      </p>
      <p className="feed-tags">{hashtagLine(item)}</p>
      <Footer item={item} onTakeDown={onTakeDown} />
    </article>
  )
}

function LinkedInPost({ item, onTakeDown }: { item: FeedPost; onTakeDown: TakeDownHandler }) {
  return (
    <article className="feed-post linkedin" lang={item.post.language}>
      <header className="feed-author">
        <span className="avatar square" aria-hidden="true" />
        <span>
          <strong>{MOCK_ACCOUNT_NAME}</strong>
          <span className="muted small"> · Company page</span>
        </span>
      </header>
      <p className="feed-text">{item.post.caption}</p>
      <p className="feed-tags">{hashtagLine(item)}</p>
      {item.post.image_url && <img src={item.post.image_url} alt={item.post.headline ?? ''} />}
      <Stats item={item} labels={['👍 reactions', 'comments', 'reposts', 'impressions']} />
      <Footer item={item} onTakeDown={onTakeDown} />
    </article>
  )
}

function XPost({ item, onTakeDown }: { item: FeedPost; onTakeDown: TakeDownHandler }) {
  return (
    <article className="feed-post x" lang={item.post.language}>
      <header className="feed-author">
        <span className="avatar" aria-hidden="true" />
        <span>
          <strong>{MOCK_ACCOUNT_NAME}</strong> <span className="muted">{MOCK_HANDLE}</span>
        </span>
      </header>
      <p className="feed-text">
        {item.post.caption} <span className="feed-tags">{hashtagLine(item)}</span>
      </p>
      {item.post.image_url && <img src={item.post.image_url} alt={item.post.headline ?? ''} />}
      <Stats item={item} labels={['♥ likes', 'replies', 'reposts', 'views']} />
      <Footer item={item} onTakeDown={onTakeDown} />
    </article>
  )
}

const RENDERERS: Record<string, (props: { item: FeedPost; onTakeDown: TakeDownHandler }) => React.JSX.Element> = {
  instagram: InstagramPost,
  linkedin: LinkedInPost,
  x: XPost,
}

// What each mock channel has "published": exactly the image and caption its adapter accepted, with live metrics.
export function FeedsView({ channels, refreshToken, onTakenDown }: FeedsViewProps) {
  const [feeds, setFeeds] = useState<Record<string, FeedPost[]> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function takeDown(item: FeedPost) {
    const channelName = channels.find((channel) => channel.id === item.post.channel)?.display_name ?? item.post.channel
    try {
      const result = await confirmAndTakeDown(item.post.id, channelName)
      if (!result) return
      setFeeds((current) =>
        current
          ? { ...current, [item.post.channel]: current[item.post.channel].filter((kept) => kept.post.id !== item.post.id) }
          : current,
      )
      setNotice(takeDownSummary(result))
      onTakenDown(result)
    } catch (caught) {
      setError(errorText(caught))
    }
  }

  useEffect(() => {
    let cancelled = false
    const load = () =>
      api
        .getFeeds()
        .then((loaded) => {
          if (cancelled) return
          setFeeds(loaded)
          setError(null)
        })
        .catch((caught) => !cancelled && setError(errorText(caught)))
    load()
    const timer = window.setInterval(load, FEED_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refreshToken])

  return (
    <section className="feeds">
      <p className="muted feeds-intro">
        Mock channels: nothing leaves this machine. Each column shows what that channel's adapter accepted and
        "published", with the metrics it reports. Use the clock bar to move time forward and watch them grow.
      </p>
      {error && <p className="error">{error}</p>}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="feed-columns">
        {channels.map((channel) => {
          const Renderer = RENDERERS[channel.id] ?? XPost
          const items = feeds?.[channel.id] ?? []
          return (
            <div key={channel.id} className={`feed-column feed-${channel.id}`}>
              <h2>
                {channel.display_name} <span className="mock-tag">mock</span>
              </h2>
              {feeds && items.length === 0 && <p className="muted">Nothing published yet.</p>}
              {items.map((item) => (
                <Renderer key={item.post.id} item={item} onTakeDown={takeDown} />
              ))}
            </div>
          )
        })}
      </div>
    </section>
  )
}
