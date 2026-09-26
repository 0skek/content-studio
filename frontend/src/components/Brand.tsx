import { FacebookLogo, InstagramLogo, XLogo, type Icon } from '@phosphor-icons/react'

// The mark: three frames in three different shapes (portrait, square, wide), one brief made native to each channel.
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="4.5" y="4" width="12" height="15" rx="1.5" stroke="currentColor" strokeWidth="2" />
      <rect x="15" y="8" width="12.5" height="12.5" rx="1.5" fill="var(--accent)" />
      <rect x="8.5" y="18.5" width="16" height="9" rx="1.5" stroke="currentColor" strokeWidth="2" fill="var(--bg)" />
    </svg>
  )
}

const CHANNEL_ICONS: Record<string, Icon> = {
  instagram: InstagramLogo,
  facebook: FacebookLogo,
  x: XLogo,
}

export function ChannelIcon({ channel, size = 18 }: { channel: string; size?: number }) {
  const Glyph = CHANNEL_ICONS[channel]
  return Glyph ? <Glyph size={size} weight="regular" aria-hidden="true" className="channel-icon" /> : null
}
