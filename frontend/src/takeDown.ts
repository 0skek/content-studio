import { api, type TakenDown } from './api'
import type { Confirm } from './confirm'

// Asks first, then takes the post down. Returns null if the user cancelled.
export async function confirmAndTakeDown(postId: number, channelName: string, confirm: Confirm): Promise<TakenDown | null> {
  const confirmed = await confirm({
    title: `Take post #${postId} down from ${channelName}?`,
    body:
      'It leaves the feed, its metrics are cleared, and it goes back to Approved so you can schedule it again. ' +
      'Weekly reports citing it are deleted.',
    confirmLabel: 'Take down',
    tone: 'danger',
  })
  return confirmed ? api.takeDownPost(postId) : null
}

export function takeDownSummary(result: TakenDown): string {
  const reports = result.deleted_report_ids.map((id) => `#${id}`).join(', ')
  return (
    `Post #${result.post.id} was taken down and is back in Approved.` +
    (result.deleted_report_ids.length > 0 ? ` Reports ${reports} cited it, so they were deleted.` : '')
  )
}
