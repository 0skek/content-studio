// Typed access to the FastAPI backend. Shapes mirror backend/app/schemas.py.

export type Language = 'bn' | 'en'
export type GenerationStatus = 'pending' | 'generating' | 'ready' | 'failed'
export type PostStatus = 'draft' | 'approved' | 'discarded' | 'scheduled' | 'published' | 'rejected'
export type LengthCounting = 'characters' | 'x_weighted'

export interface Post {
  id: number
  brief_id: number
  channel: string
  language: Language
  headline: string | null
  caption: string
  hashtags: string[]
  image_prompt: string | null
  image_path: string | null
  image_url: string | null
  width: number | null
  height: number | null
  file_size_bytes: number | null
  published_length: number
  generation_status: GenerationStatus
  generation_error: string | null
  status: PostStatus
  rejection_reason: string | null
  parent_post_id: number | null
  scheduled_at: string | null
  published_at: string | null
}

export interface BriefSummary {
  id: number
  title: string
  languages: Language[]
  created_at: string
}

// An insight a brief was created with, as recorded on the brief.
export interface InsightUsed {
  id: number
  report_id: number
  text: string
}

export interface Brief extends BriefSummary {
  goal: string
  audience: string
  tone: string
  insights_used: InsightUsed[]
  posts: Post[]
}

export interface Insight {
  id: number
  report_id: number
  text: string
  created_at: string
}

export interface ReportClaim {
  text: string
  post_ids: number[]
}

// The numbers a report was written from (saved with it), used for its charts and evidence table.
export interface EvidencePost {
  post_id: number
  brief_id: number
  brief_title: string
  channel: string
  language: Language
  headline: string | null
  hashtags: number
  published_length: number
  impressions: number
  engagements: number
  clicks: number
  engagement_rate: number | null
  click_through_rate: number | null
}

export type EvidenceGroupKind = 'channel' | 'channel_language' | 'channel_hashtags' | 'channel_length'
export type EvidenceBucket = 'few_hashtags' | 'many_hashtags' | 'short' | 'long'

export interface EvidenceGroup {
  kind: EvidenceGroupKind
  channel: string
  language: Language | null
  bucket: EvidenceBucket | null
  label: string
  post_ids: number[]
  impressions: number
  engagements: number
  clicks: number
  engagement_rate: number | null
  click_through_rate: number | null
}

export interface Evidence {
  window_start: string
  window_end: string
  posts: EvidencePost[]
  groups: EvidenceGroup[]
}

export interface Report {
  id: number
  week_start: string
  content: { summary: ReportClaim; findings: ReportClaim[]; insights: ReportClaim[] }
  // Null for reports saved before evidence was stored with them.
  evidence: Evidence | null
  cited_post_ids: number[]
  insights: Insight[]
}

export interface BriefInput {
  title: string
  goal: string
  audience: string
  tone: string
  languages: Language[]
  insight_ids: number[]
}

export interface Channel {
  id: string
  display_name: string
  width: number
  height: number
  aspect_ratio: string
  max_file_size_mb: number
  caption_max_chars: number
  max_hashtags: number
  length_counting: LengthCounting
}

export interface Health {
  status: string
  text_provider: string
  image_provider: string
  // False when local development providers (Ollama / local image server) are active.
  production_providers: boolean
}

// The demo clock: real time plus however far it has been fast-forwarded.
export interface ClockState {
  now: string
  offset_hours: number
}

export interface PublishRun {
  now: string
  published: number[]
  rejected: number[]
  metrics_ingested: number[]
}

// A published post's latest metrics snapshot. Rates are null until it has impressions.
export interface Performance {
  post_id: number
  channel: string
  language: Language
  published_at: string | null
  fetched_at: string | null
  impressions: number
  likes: number
  comments: number
  shares: number
  clicks: number
  engagements: number
  engagement_rate: number | null
  click_through_rate: number | null
}

export interface ComparisonRow {
  language: Language
  // channel id -> this language's published post on that channel, or null if none is published there.
  cells: Record<string, Performance | null>
  best_engagement_channel: string | null
  best_click_channel: string | null
}

export interface ChannelSummary {
  channel: string
  post_ids: number[]
  impressions: number
  engagements: number
  clicks: number
  engagement_rate: number | null
  click_through_rate: number | null
}

export interface Comparison {
  brief_id: number
  channels: string[]
  rows: ComparisonRow[]
  channel_summaries: ChannelSummary[]
  definitions: Record<string, string>
}

export interface FeedPost {
  post: Post
  brief_title: string
  performance: Performance
}

export interface AdapterMeasurements {
  width: number | null
  height: number | null
  file_size_bytes: number
  published_length: number
  hashtag_count: number
}

export interface AdapterVerdict {
  channel: string
  accepted: boolean
  reasons: string[]
  measurements: AdapterMeasurements
}

export interface AdapterSubmission {
  caption: string
  hashtags: string
  image: Blob
}

export class ApiError extends Error {}

const HTTP_UNPROCESSABLE = 422
const HTTP_NO_CONTENT = 204

// A post taken down from its feed: back to approved, and reports that cited it deleted.
export interface TakenDown {
  post: Post
  deleted_report_ids: number[]
}

// What deleting a brief removed; reports that cited its posts go with it.
export interface DeletedBrief {
  brief_id: number
  post_ids: number[]
  report_ids: number[]
}

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((issue: ValidationIssue) => `${(issue.loc ?? []).slice(1).join('.')}: ${issue.msg}`)
        .join('; ')
    }
  } catch {
    // Not JSON: fall back to the status code below.
  }
  return `Request failed with HTTP ${response.status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('Cannot reach the backend. Is it running on port 8000?')
  }
  if (!response.ok) throw new ApiError(await errorMessage(response))
  if (response.status === HTTP_NO_CONTENT) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/health'),
  listChannels: () => request<Channel[]>('/channels'),
  listBriefs: () => request<BriefSummary[]>('/briefs'),
  getBrief: (briefId: number) => request<Brief>(`/briefs/${briefId}`),
  createBrief: (input: BriefInput) =>
    request<Brief>('/briefs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }),
  approvePost: (postId: number) => request<Post>(`/posts/${postId}/approve`, { method: 'POST' }),
  discardPost: (postId: number) => request<Post>(`/posts/${postId}/discard`, { method: 'POST' }),
  // Returns the new draft; its generation runs in the background.
  retryPost: (postId: number) => request<Post>(`/posts/${postId}/retry`, { method: 'POST' }),
  schedulePost: (postId: number, scheduledAt: Date) =>
    request<Post>(`/posts/${postId}/schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheduled_at: scheduledAt.toISOString() }),
    }),
  getClock: () => request<ClockState>('/clock'),
  advanceClock: (hours: number) =>
    request<PublishRun>('/clock/advance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours }),
    }),
  resetClock: () => request<ClockState>('/clock/reset', { method: 'POST' }),
  publishDueNow: () => request<PublishRun>('/publisher/run-due', { method: 'POST' }),
  getComparison: (briefId: number) => request<Comparison>(`/briefs/${briefId}/comparison`),
  getFeeds: () => request<Record<string, FeedPost[]>>('/feeds'),
  // Writes this week's report with the text model; can take a while.
  generateReport: () => request<Report>('/reports', { method: 'POST' }),
  listReports: () => request<Report[]>('/reports'),
  deleteBrief: (briefId: number) => request<DeletedBrief>(`/briefs/${briefId}`, { method: 'DELETE' }),
  deleteReport: (reportId: number) => request<void>(`/reports/${reportId}`, { method: 'DELETE' }),
  takeDownPost: (postId: number) => request<TakenDown>(`/posts/${postId}/take-down`, { method: 'POST' }),
  latestInsights: () => request<Insight[]>('/insights/latest'),
  submitToAdapter,
}

// A rejection is an answer, not a failure: the adapter replies 422 with the same verdict shape as an acceptance.
async function submitToAdapter(channelId: string, submission: AdapterSubmission): Promise<AdapterVerdict> {
  const form = new FormData()
  form.append('caption', submission.caption)
  form.append('hashtags', submission.hashtags)
  form.append('image', submission.image, 'post-image')
  let response: Response
  try {
    response = await fetch(`/adapters/${channelId}/submit`, { method: 'POST', body: form })
  } catch {
    throw new ApiError('Cannot reach the backend. Is it running on port 8000?')
  }
  if (response.ok) return (await response.json()) as AdapterVerdict
  if (response.status === HTTP_UNPROCESSABLE) {
    const body = await response.clone().json().catch(() => null)
    if (body?.detail && typeof body.detail === 'object' && 'accepted' in body.detail) return body.detail as AdapterVerdict
  }
  throw new ApiError(await errorMessage(response))
}

export function isGenerating(post: Post): boolean {
  return post.generation_status === 'pending' || post.generation_status === 'generating'
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
