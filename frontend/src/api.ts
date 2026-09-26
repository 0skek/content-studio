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

export interface Brief extends BriefSummary {
  goal: string
  audience: string
  tone: string
  insights_used: unknown[]
  posts: Post[]
}

export interface BriefInput {
  title: string
  goal: string
  audience: string
  tone: string
  languages: Language[]
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

export class ApiError extends Error {}

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
}

export function isGenerating(post: Post): boolean {
  return post.generation_status === 'pending' || post.generation_status === 'generating'
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
