import { useEffect, useState } from 'react'
import { ArrowRight, CheckCircle, Flask, Image as ImageIcon, UploadSimple, XCircle } from '@phosphor-icons/react'
import { api, errorText, type AdapterVerdict, type Channel } from '../api'
import { ChannelIcon } from './Brand'

const BYTES_PER_MEGABYTE = 1024 * 1024
// A wrong-ratio test image: square for channels that aren't square, and 2:1 for the one that is.
const WRONG_RATIO_SIDE = 1024
const WRONG_RATIO_WIDE_FACTOR = 2
// Random noise barely compresses (about 4 bytes a pixel as PNG), so scaling the channel's own size up until the
// noise outweighs its file limit keeps the ratio right but makes the file too big for that channel.
const OVERSIZE_MIN_SCALE = 2
const NOISE_BYTES_PER_PIXEL = 4
const OVERSIZE_MARGIN = 1.25
const JPEG_QUALITY = 0.9
// Durga Puja sample text for a Kolkata shop, in Bengali (West Bengal usage: পুজো, ঠাকুর দেখা, সঙ্গে) and in English.
// Each fits every channel's limits as written, so only the presets below break them.
type SampleVariant = 'bn' | 'en'
const SAMPLES: Record<SampleVariant, { label: string; caption: string; hashtags: string; filler: string }> = {
  bn: {
    label: 'বাংলা · Kolkata',
    caption:
      'পুজো এসে গেল! ষষ্ঠী থেকে দশমী, পরিবারের সঙ্গে ঠাকুর দেখার প্রতিটা দিন সাজুন নতুন তাঁতের শাড়ি আর পাঞ্জাবিতে। ' +
      'এই সপ্তাহেই চলে আসুন আমাদের দোকানে।',
    hashtags: '#দুর্গাপুজো #শুভশারদীয়া',
    filler: 'পুজোর নতুন তাঁতের শাড়ি আর পাঞ্জাবি এসে গেছে, এই সপ্তাহেই দোকানে চলে আসুন। ',
  },
  en: {
    label: 'English · Kolkata',
    caption:
      'Pujo is almost here! From Shashthi to Dashami, go pandal hopping with family in a new taant sari or panjabi. ' +
      'Visit our Gariahat store this week.',
    hashtags: '#DurgaPuja #Kolkata',
    filler: 'New taant saris and panjabis for Pujo are in store now, visit us this week. ',
  },
}
const SAMPLE_VARIANTS: SampleVariant[] = ['bn', 'en']
// Each constraint the problem statement names, and the control on this page that breaks it for the chosen channel.
const LAB_CHECKS: { constraint: string; how: (channel: Channel) => string }[] = [
  { constraint: 'Aspect ratio', how: (channel) => `Image preset “Wrong ratio” (${channel.aspect_ratio} ±2% allowed)` },
  { constraint: 'File size', how: (channel) => `Image preset “Oversized file” (${channel.max_file_size_mb} MB allowed)` },
  {
    constraint: 'Character limit',
    how: (channel) => `“Make it 20 over the limit” on the caption (${channel.caption_max_chars} allowed)`,
  },
  { constraint: 'Hashtag count', how: (channel) => `Add hashtags past ${channel.max_hashtags}, this channel’s limit` },
]
const CAPTION_OVERSHOOT = 20

// previewUrl is an object URL for the blob; it is revoked when the image is replaced.
type ImageSource = { label: string; blob: Blob; previewUrl: string }

function imageSource(label: string, blob: Blob): ImageSource {
  return { label, blob, previewUrl: URL.createObjectURL(blob) }
}

function canvasBlob(width: number, height: number, paint: (context: CanvasRenderingContext2D) => void, type: string) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('This browser cannot draw test images.')
  paint(context)
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('Could not encode the test image.'))), type, JPEG_QUALITY),
  )
}

function paintGradient(width: number, height: number) {
  return (context: CanvasRenderingContext2D) => {
    const gradient = context.createLinearGradient(0, 0, width, height)
    gradient.addColorStop(0, '#0f766e')
    gradient.addColorStop(1, '#f59e0b')
    context.fillStyle = gradient
    context.fillRect(0, 0, width, height)
  }
}

function paintNoise(width: number, height: number) {
  return (context: CanvasRenderingContext2D) => {
    const pixels = context.createImageData(width, height)
    for (let index = 0; index < pixels.data.length; index += 1) pixels.data[index] = Math.random() * 256
    context.putImageData(pixels, 0, 0)
  }
}

// The adapter measures the caption plus a blank line and the hashtag line, after NFC normalisation, which splits
// letters like য় into two code points (backend/app/caption_length.py). Bengali letters weigh 1 on X as well, so for
// the samples this is the exact length the adapter will count.
function publishedSuffixLength(hashtags: string): number {
  const tags = hashtags
    .split(/[\s,]+/)
    .map((tag) => tag.replace(/^#+/, ''))
    .filter(Boolean)
  return tags.length === 0 ? 0 : `\n\n${tags.map((tag) => `#${tag}`).join(' ')}`.normalize('NFC').length
}

function formatMegabytes(bytes: number): string {
  return `${(bytes / BYTES_PER_MEGABYTE).toFixed(2)} MB`
}

interface AdapterBenchProps {
  channels: Channel[]
}

// Sends any caption and image straight to a channel's mock adapter, to show it rejecting constraint violations.
export function AdapterBench({ channels }: AdapterBenchProps) {
  const [channelId, setChannelId] = useState(channels[0]?.id ?? '')
  const [variant, setVariant] = useState<SampleVariant>('bn')
  const [caption, setCaption] = useState(SAMPLES.bn.caption)
  const [hashtags, setHashtags] = useState(SAMPLES.bn.hashtags)
  const [image, setImage] = useState<ImageSource | null>(null)
  const [verdict, setVerdict] = useState<AdapterVerdict | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  const channel = channels.find((candidate) => candidate.id === channelId) ?? channels[0]

  useEffect(() => {
    return () => {
      if (image) URL.revokeObjectURL(image.previewUrl)
    }
  }, [image])

  if (!channel) return <div className="page"><div className="report-skeleton skeleton" aria-hidden="true" /></div>

  async function makeImage(kind: 'valid' | 'wrong-ratio' | 'oversized') {
    setError(null)
    setVerdict(null)
    try {
      if (kind === 'valid') {
        const blob = await canvasBlob(channel.width, channel.height, paintGradient(channel.width, channel.height), 'image/jpeg')
        setImage(imageSource(`Exact size ${channel.width}×${channel.height}`, blob))
      } else if (kind === 'wrong-ratio') {
        const channelIsSquare = channel.width === channel.height
        const width = channelIsSquare ? WRONG_RATIO_SIDE * WRONG_RATIO_WIDE_FACTOR : WRONG_RATIO_SIDE
        const height = WRONG_RATIO_SIDE
        const blob = await canvasBlob(width, height, paintGradient(width, height), 'image/jpeg')
        setImage(imageSource(`${channelIsSquare ? 'Wide' : 'Square'} ${width}×${height} (wrong ratio)`, blob))
      } else {
        const pixelsNeeded = (channel.max_file_size_mb * BYTES_PER_MEGABYTE * OVERSIZE_MARGIN) / NOISE_BYTES_PER_PIXEL
        const scale = Math.max(OVERSIZE_MIN_SCALE, Math.sqrt(pixelsNeeded / (channel.width * channel.height)))
        const width = Math.round(channel.width * scale)
        const height = Math.round(channel.height * scale)
        const blob = await canvasBlob(width, height, paintNoise(width, height), 'image/png')
        setImage(imageSource(`Noise ${width}×${height} PNG (right ratio, oversized file)`, blob))
      }
    } catch (caught) {
      setError(errorText(caught))
    }
  }

  function uploadImage(file: File | undefined) {
    setVerdict(null)
    if (file) setImage(imageSource(file.name, file))
  }

  function applySample(next: SampleVariant) {
    setVariant(next)
    setCaption(SAMPLES[next].caption)
    setHashtags(SAMPLES[next].hashtags)
    setVerdict(null)
  }

  function fillOversizedCaption() {
    setVerdict(null)
    const target = Math.max(CAPTION_OVERSHOOT, channel.caption_max_chars + CAPTION_OVERSHOOT - publishedSuffixLength(hashtags))
    const filler = SAMPLES[variant].filler.normalize('NFC')
    setCaption(filler.repeat(Math.ceil(target / filler.length)).slice(0, target))
  }

  async function submit() {
    if (!image) {
      setError('Pick or make an image first.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      setVerdict(await api.submitToAdapter(channel.id, { caption, hashtags, image: image.blob }))
    } catch (caught) {
      setError(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  const lengthUnit = channel.length_counting === 'x_weighted' ? 'weighted chars' : 'chars'

  return (
    <section className="page bench">
      <header className="page-head">
        <p className="eyebrow lab-eyebrow">
          <Flask size={14} weight="duotone" aria-hidden="true" /> Experiment corner · for the hackathon
        </p>
        <h1>Adapter bench</h1>
        <p className="lede">
          Send any caption and image straight to a channel's mock adapter, the same check every scheduled post goes
          through. Violations are rejected with a reason. Nothing is resized, trimmed or stored.
        </p>
      </header>

      <section className="lab-brief" aria-label="Why this tab exists">
        <div className="lab-quote">
          <span className="section-label">Problem statement · toughest test</span>
          <blockquote>
            “A post that violates a platform constraint (aspect ratio, file size, character limit) is submitted to the
            adapter layer and must be rejected, not silently accepted.”
          </blockquote>
          <p className="lab-note">
            This tab exists to show that requirement on its own. It is not part of the publishing flow: nothing sent
            here is stored, scheduled or published. In the Studio, a scheduled post that breaks a limit goes through
            the same adapter and ends up Rejected, with the reason on its card.
          </p>
        </div>
        <dl className="lab-checks">
          {LAB_CHECKS.map((check) => (
            <div key={check.constraint}>
              <dt>{check.constraint}</dt>
              <dd>{check.how(channel)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="bench-grid">
        <div className="panel bench-form">
          <div className="field">
            <span className="field-label" id="bench-channel-label">
              Channel
            </span>
            <div className="segmented segmented-wide" role="radiogroup" aria-labelledby="bench-channel-label">
              {channels.map((option) => (
                <label key={option.id} className="segment">
                  <input
                    type="radio"
                    name="bench-channel"
                    checked={option.id === channel.id}
                    onChange={() => {
                      setChannelId(option.id)
                      setVerdict(null)
                      setImage(null)
                    }}
                  />
                  <span>
                    <ChannelIcon channel={option.id} size={16} />
                    {option.display_name}
                  </span>
                </label>
              ))}
            </div>
            <p className="spec-line mono">
              <span>
                {channel.width}×{channel.height}
              </span>
              <span>{channel.aspect_ratio} ±2%</span>
              <span>≤ {channel.max_file_size_mb} MB</span>
              <span>
                ≤ {channel.caption_max_chars} {lengthUnit}
              </span>
              <span>≤ {channel.max_hashtags} tags</span>
            </p>
          </div>

          <div className="field">
            <span className="field-label" id="bench-sample-label">
              Sample text · Durga Puja
            </span>
            <div className="segmented segmented-wide" role="radiogroup" aria-labelledby="bench-sample-label">
              {SAMPLE_VARIANTS.map((key) => (
                <label key={key} className="segment">
                  <input
                    type="radio"
                    name="bench-sample"
                    checked={variant === key}
                    onChange={() => applySample(key)}
                    // Clicking the chosen sample again restores its text, e.g. after "20 over the limit".
                    onClick={() => variant === key && applySample(key)}
                  />
                  <span>{SAMPLES[key].label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="field">
            <span className="field-label">
              <label htmlFor="bench-caption">Caption</label>
              <button type="button" className="chip-button" onClick={fillOversizedCaption}>
                Make it {CAPTION_OVERSHOOT} over the limit
              </button>
            </span>
            <textarea
              id="bench-caption"
              lang={variant}
              rows={6}
              value={caption}
              onChange={(event) => setCaption(event.target.value)}
            />
          </div>

          <label className="field">
            <span className="field-label">Hashtags</span>
            <input value={hashtags} onChange={(event) => setHashtags(event.target.value)} lang="bn" placeholder="#দুর্গাপুজো #শুভশারদীয়া" />
          </label>

          <div className="field">
            <span className="field-label">
              Image
              <span className="preset-row">
                <button type="button" className="chip-button" onClick={() => makeImage('valid')}>
                  Exact size
                </button>
                <button type="button" className="chip-button" onClick={() => makeImage('wrong-ratio')}>
                  Wrong ratio
                </button>
                <button type="button" className="chip-button" onClick={() => makeImage('oversized')}>
                  Oversized file
                </button>
              </span>
            </span>
            <label
              className={dragging ? 'dropzone dragging' : 'dropzone'}
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                uploadImage(event.dataTransfer.files[0])
              }}
            >
              <input type="file" accept="image/*" onChange={(event) => uploadImage(event.target.files?.[0])} />
              <UploadSimple size={20} aria-hidden="true" />
              {image ? (
                <span>
                  <strong>{image.label}</strong>
                  <span className="mono muted"> · {formatMegabytes(image.blob.size)}</span>
                </span>
              ) : (
                <span>
                  <strong>Drop an image</strong> or click to choose one, or use a preset above
                </span>
              )}
            </label>
          </div>

          <button type="button" className="btn btn-primary btn-lg btn-block" disabled={busy || !image} onClick={submit}>
            {busy ? (
              <>
                <span className="spinner" aria-hidden="true" /> Sending…
              </>
            ) : (
              <>
                Submit to the {channel.display_name} adapter <ArrowRight size={16} weight="bold" aria-hidden="true" />
              </>
            )}
          </button>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>

        <div className="bench-result">
          <div className="panel bench-preview-panel">
            {image ? (
              <img className="bench-preview" src={image.previewUrl} alt={image.label} />
            ) : (
              <div className="bench-preview-empty">
                <ImageIcon size={32} aria-hidden="true" />
                <p>Pick a preset or drop an image to preview what the adapter will check.</p>
              </div>
            )}
          </div>
          {verdict && (
            <div className={`verdict ${verdict.accepted ? 'verdict-accepted' : 'verdict-rejected'}`} role="status">
              <p className="verdict-title">
                {verdict.accepted ? (
                  <CheckCircle size={26} weight="fill" aria-hidden="true" />
                ) : (
                  <XCircle size={26} weight="fill" aria-hidden="true" />
                )}
                {verdict.accepted ? 'Accepted. This would publish.' : 'Rejected by the adapter'}
              </p>
              {verdict.reasons.length > 0 && (
                <ul className="verdict-reasons">
                  {verdict.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
              <table className="measure-table">
                <thead>
                  <tr>
                    <th scope="col">Check</th>
                    <th scope="col">Measured</th>
                    <th scope="col">Limit</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Image size</th>
                    <td className="mono">
                      {verdict.measurements.width ?? '?'}×{verdict.measurements.height ?? '?'}
                    </td>
                    <td className="mono">
                      {channel.aspect_ratio} ±2% ({channel.width}×{channel.height})
                    </td>
                  </tr>
                  <tr>
                    <th scope="row">File size</th>
                    <td className="mono">{formatMegabytes(verdict.measurements.file_size_bytes)}</td>
                    <td className="mono">{channel.max_file_size_mb} MB</td>
                  </tr>
                  <tr>
                    <th scope="row">Length</th>
                    <td className="mono">{verdict.measurements.published_length}</td>
                    <td className="mono">
                      {channel.caption_max_chars} {lengthUnit}
                    </td>
                  </tr>
                  <tr>
                    <th scope="row">Hashtags</th>
                    <td className="mono">{verdict.measurements.hashtag_count}</td>
                    <td className="mono">{channel.max_hashtags}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
