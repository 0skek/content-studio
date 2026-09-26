import { useEffect, useState } from 'react'
import { api, errorText, type AdapterVerdict, type Channel } from '../api'

const BYTES_PER_MEGABYTE = 1024 * 1024
const WRONG_RATIO_SIDE = 1024
// Noise at twice the channel's size keeps the ratio right but makes a PNG far larger than any channel allows.
const OVERSIZE_SCALE = 2
const JPEG_QUALITY = 0.9
const CAPTION_FILLER = 'Eid outfits for the whole family, ready in store this week. '
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

function formatMegabytes(bytes: number): string {
  return `${(bytes / BYTES_PER_MEGABYTE).toFixed(2)} MB`
}

interface AdapterBenchProps {
  channels: Channel[]
}

// Sends any caption and image straight to a channel's mock adapter, to show it rejecting constraint violations.
export function AdapterBench({ channels }: AdapterBenchProps) {
  const [channelId, setChannelId] = useState(channels[0]?.id ?? '')
  const [caption, setCaption] = useState('Eid outfits for the whole family. Visit us this week!')
  const [hashtags, setHashtags] = useState('#Eid')
  const [image, setImage] = useState<ImageSource | null>(null)
  const [verdict, setVerdict] = useState<AdapterVerdict | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const channel = channels.find((candidate) => candidate.id === channelId) ?? channels[0]

  useEffect(() => {
    return () => {
      if (image) URL.revokeObjectURL(image.previewUrl)
    }
  }, [image])

  if (!channel) return <p className="muted">Loading channels…</p>

  async function makeImage(kind: 'valid' | 'wrong-ratio' | 'oversized') {
    setError(null)
    setVerdict(null)
    try {
      if (kind === 'valid') {
        const blob = await canvasBlob(channel.width, channel.height, paintGradient(channel.width, channel.height), 'image/jpeg')
        setImage(imageSource(`Exact size ${channel.width}×${channel.height}`, blob))
      } else if (kind === 'wrong-ratio') {
        const side = WRONG_RATIO_SIDE
        const blob = await canvasBlob(side, side, paintGradient(side, side), 'image/jpeg')
        setImage(imageSource(`Square ${side}×${side} (wrong ratio)`, blob))
      } else {
        const width = channel.width * OVERSIZE_SCALE
        const height = channel.height * OVERSIZE_SCALE
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

  function fillOversizedCaption() {
    setVerdict(null)
    const target = channel.caption_max_chars + CAPTION_OVERSHOOT
    setCaption(CAPTION_FILLER.repeat(Math.ceil(target / CAPTION_FILLER.length)).slice(0, target))
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

  const lengthUnit = channel.length_counting === 'x_weighted' ? 'weighted characters' : 'characters'

  return (
    <section className="adapter-bench">
      <header>
        <h2>Adapter test bench</h2>
        <p className="muted">
          Send any caption and image straight to a channel's mock adapter, the same check every scheduled post goes
          through. Violations are rejected with reasons; nothing is resized, trimmed or stored.
        </p>
      </header>

      <div className="bench-grid">
        <div className="bench-form">
          <label>
            Channel
            <select
              value={channel.id}
              onChange={(event) => {
                setChannelId(event.target.value)
                setVerdict(null)
                setImage(null)
              }}
            >
              {channels.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.display_name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted limits">
            Limits: {channel.width}×{channel.height} ({channel.aspect_ratio}) · {channel.max_file_size_mb} MB ·{' '}
            {channel.caption_max_chars} {lengthUnit} · {channel.max_hashtags} hashtags
          </p>

          <label>
            Caption
            <textarea rows={6} value={caption} onChange={(event) => setCaption(event.target.value)} />
          </label>
          <button type="button" className="preset" onClick={fillOversizedCaption}>
            Make caption {CAPTION_OVERSHOOT} over the limit
          </button>

          <label>
            Hashtags
            <input value={hashtags} onChange={(event) => setHashtags(event.target.value)} placeholder="#Eid #Dhaka" />
          </label>

          <fieldset>
            <legend>Image</legend>
            <div className="preset-row">
              <button type="button" className="preset" onClick={() => makeImage('valid')}>
                Exact size
              </button>
              <button type="button" className="preset" onClick={() => makeImage('wrong-ratio')}>
                Wrong ratio
              </button>
              <button type="button" className="preset" onClick={() => makeImage('oversized')}>
                Oversized file
              </button>
            </div>
            <input type="file" accept="image/*" onChange={(event) => uploadImage(event.target.files?.[0])} />
            {image && (
              <p className="muted">
                {image.label} · {formatMegabytes(image.blob.size)}
              </p>
            )}
          </fieldset>

          <button type="button" className="submit" disabled={busy || !image} onClick={submit}>
            {busy ? 'Sending…' : `Submit to ${channel.display_name} adapter`}
          </button>
          {error && <p className="error">{error}</p>}
        </div>

        <div className="bench-result">
          {image && <img className="bench-preview" src={image.previewUrl} alt={image.label} />}
          {verdict && (
            <div className={`verdict ${verdict.accepted ? 'verdict-accepted' : 'verdict-rejected'}`} role="status">
              <p className="verdict-title">{verdict.accepted ? 'Accepted — would publish' : 'Rejected by the adapter'}</p>
              {verdict.reasons.length > 0 && (
                <ul>
                  {verdict.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
              <p className="muted">
                Measured: {verdict.measurements.width ?? '?'}×{verdict.measurements.height ?? '?'} ·{' '}
                {formatMegabytes(verdict.measurements.file_size_bytes)} · {verdict.measurements.published_length}/
                {channel.caption_max_chars} {lengthUnit} · {verdict.measurements.hashtag_count}/{channel.max_hashtags} hashtags
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
