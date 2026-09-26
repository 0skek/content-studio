import { createContext, useContext, type ReactNode } from 'react'

export interface ConfirmOptions {
  title: string
  body: ReactNode
  confirmLabel: string
  // Danger styles the confirm button for actions that delete or undo something.
  tone?: 'danger' | 'default'
}

export type Confirm = (options: ConfirmOptions) => Promise<boolean>

// Resolves true when the user confirms, false when they cancel or press Esc. Provided by ConfirmProvider.
export const ConfirmContext = createContext<Confirm>(() => Promise.resolve(false))

export function useConfirm(): Confirm {
  return useContext(ConfirmContext)
}
