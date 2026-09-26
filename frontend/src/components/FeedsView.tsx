import { useEffect, useState } from 'react'
import {
  BookmarkSimple,
  ChartBar,
  ChatCircle,
  DotsThree,
  GlobeHemisphereWest,
  Heart,
  PaperPlaneTilt,
  Repeat,
  ShareFat,
  ThumbsUp,
} from '@phosphor-icons/react'
import { api, errorText, type Channel, type FeedPost, type TakenDown } from '../api'
import { useConfirm } from '../confirm'
import { formatCount, formatTime } from '../format'
import { confirmAndTakeDown, takeDownSummary } from '../takeDown'
import { ChannelIcon, LogoMark } from './Brand'

const FEED_REFRESH_MS = 5000
const MOCK_ACCOUNT_NAME = 'Your Brand'
const MOCK_HANDLE = 'yourbrand'
const ICON = 20

interface FeedsViewProps {
  channels: Channel[]
  // Changes when the clock bar published posts or ingested metrics.
  refreshToken: number
  // Called after a post is taken down, so the brief view and reports catch up.
  onTakenDown: (result: TakenDown) => void
}

type TakeDownHandler = (item: FeedPost) => void
interface PostProps {
  item: FeedPost
  onTakeDown: TakeDownHandler
}

function Tags({ item }: { item: FeedPost }) {
  if (item.post.hashtags.length === 0) return null
  return <span className="feed-tags">{item.post.hashtags.map((tag) => `#${tag}`).join(' ')}</span>
}

function Avatar({ shape = 'round' }: { shape?: 'round' | 'square' }) {
  return (
    <span className={`feed-avatar ${shape}`} aria-hidden="true">
      <LogoMark size={20} />
    </span>
  )
}

function Provenance({ item, onTakeDown }: PostProps) {
  return (
    <div className="feed-provenance">
      <p>
        <span className="mono">#{item.post.id}</span> · {item.brief_title} · published{' '}
        {item.post.published_at && formatTime(item.post.published_at)} by the mock adapter
      </p>
      <button type="button" className="btn btn-ghost btn-xs btn-danger-ghost" onClick={() => onTakeDown(item)}>
        Take down
      </button>
    </div>
  )
}

function InstagramPost({ item, onTakeDown }: PostProps) {
  const { likes, comments, impressions } = item.performance
  return (
    <article className="feed-post ig" lang={item.post.language}>
      <header className="feed-author">
        <span className="ig-ring">
          <Avatar />
        </span>
        <strong>{MOCK_HANDLE}</strong>
        <DotsThree size={ICON} weight="bold" className="feed-more" aria-hidden="true" />
      </header>
      {item.post.image_url && <img className="feed-image" src={item.post.image_url} alt={item.post.headline ?? ''} />}
      <div className="ig-actions" aria-hidden="true">
        <Heart size={24} />
        <ChatCircle size={24} />
        <PaperPlaneTilt size={24} />
        <BookmarkSimple size={24} className="ig-save" />
      </div>
      <p className="feed-stat-line">
        <strong>{formatCount(likes)} likes</strong>
      </p>
      <p className="feed-text">
        <strong>{MOCK_HANDLE}</strong> {item.post.caption} <Tags item={item} />
      </p>
      <p className="feed-subtle">
        View all {formatCount(comments)} comments · {formatCount(impressions)} views
      </p>
      <Provenance item={item} onTakeDown={onTakeDown} />
    </article>
  )
}

function FacebookPost({ item, onTakeDown }: PostProps) {
  const { likes, comments, shares, impressions } = item.performance
  return (
    <article className="feed-post fb" lang={item.post.language}>
      <header className="feed-author">
        <Avatar />
        <span className="feed-author-text">
          <strong>{MOCK_ACCOUNT_NAME}</strong>
          <span className="feed-subtle fb-meta">
            Just now · <GlobeHemisphereWest size={12} aria-label="Public" />
          </span>
        </span>
        <DotsThree size={ICON} weight="bold" className="feed-more" aria-hidden="true" />
      </header>
      <p className="feed-text">
        {item.post.caption}
        {'\n'}
        <Tags item={item} />
      </p>
      {item.post.image_url && <img className="feed-image" src={item.post.image_url} alt={item.post.headline ?? ''} />}
      <p className="fb-counts feed-subtle">
        <span>
          <span className="fb-reaction" aria-hidden="true">
            <ThumbsUp size={11} weight="fill" />
          </span>
          {formatCount(likes)}
        </span>
        <span>
          {formatCount(comments)} comments · {formatCount(shares)} shares · {formatCount(impressions)} views
        </span>
      </p>
      <div className="fb-actions" aria-hidden="true">
        <span>
          <ThumbsUp size={ICON} /> Like
        </span>
        <span>
          <ChatCircle size={ICON} /> Comment
        </span>
        <span>
          <ShareFat size={ICON} /> Share
        </span>
      </div>
      <Provenance item={item} onTakeDown={onTakeDown} />
    </article>
  )
}

function XPost({ item, onTakeDown }: PostProps) {
  const { likes, comments, shares, impressions } = item.performance
  return (
    <article className="feed-post xp" lang={item.post.language}>
      <div className="xp-row">
        <Avatar />
        <div className="xp-main">
          <header className="xp-author">
            <strong>{MOCK_ACCOUNT_NAME}</strong>
            <span className="feed-subtle">@{MOCK_HANDLE}</span>
          </header>
          <p className="feed-text">
            {item.post.caption} <Tags item={item} />
          </p>
          {item.post.image_url && <img className="feed-image" src={item.post.image_url} alt={item.post.headline ?? ''} />}
          <div className="xp-stats feed-subtle">
            <span>
              <ChatCircle size={18} aria-hidden="true" /> {formatCount(comments)}
              <span className="sr-only"> replies</span>
            </span>
            <span>
              <Repeat size={18} aria-hidden="true" /> {formatCount(shares)}
              <span className="sr-only"> reposts</span>
            </span>
            <span>
              <Heart size={18} aria-hidden="true" /> {formatCount(likes)}
              <span className="sr-only"> likes</span>
            </span>
            <span>
              <ChartBar size={18} aria-hidden="true" /> {formatCount(impressions)}
              <span className="sr-only"> views</span>
            </span>
          </div>
        </div>
      </div>
      <Provenance item={item} onTakeDown={onTakeDown} />
    </article>
  )
}

const RENDERERS: Record<string, (props: PostProps) => React.JSX.Element> = {
  instagram: InstagramPost,
  facebook: FacebookPost,
  x: XPost,
}

// What each mock channel has "published": exactly the image and caption its adapter accepted, with live metrics.
export function FeedsView({ channels, refreshToken, onTakenDown }: FeedsViewProps) {
  const confirm = useConfirm()
  const [feeds, setFeeds] = useState<Record<string, FeedPost[]> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function takeDown(item: FeedPost) {
    const channelName = channels.find((channel) => channel.id === item.post.channel)?.display_name ?? item.post.channel
    try {
      const result = await confirmAndTakeDown(item.post.id, channelName, confirm)
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
    <section className="page feeds">
      <header className="page-head">
        <p className="eyebrow">Publishing</p>
        <h1>Channel feeds</h1>
        <p className="lede">
          What each mock channel's adapter accepted and "published", with the metrics it reports. Nothing leaves this
          machine. Move the demo clock forward to watch the numbers grow.
        </p>
      </header>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
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
            <section key={channel.id} className={`feed-column feed-${channel.id}`} aria-labelledby={`feed-${channel.id}`}>
              <header className="feed-column-head">
                <h2 id={`feed-${channel.id}`}>
                  <ChannelIcon channel={channel.id} size={18} />
                  {channel.display_name}
                </h2>
                <span className="mock-tag">Mock</span>
                <span className="feed-count mono">{feeds ? items.length : '–'}</span>
              </header>
              {feeds === null && <div className="feed-skeleton skeleton" aria-hidden="true" />}
              {feeds && items.length === 0 && (
                <div className="feed-empty">
                  <ChannelIcon channel={channel.id} size={28} />
                  <p>Nothing published yet. Approve and schedule a post, then publish it with the demo clock.</p>
                </div>
              )}
              {items.map((item) => (
                <Renderer key={item.post.id} item={item} onTakeDown={takeDown} />
              ))}
            </section>
          )
        })}
      </div>
    </section>
  )
}
