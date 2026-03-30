export type CheckoutStatus = 'idle' | 'pending' | 'confirming' | 'complete' | 'failed'

export interface CheckoutState {
  status: CheckoutStatus
  client_secret: string | null
  receipt_id: string | null
  amount: number | null
  currency: string | null
  error: string | null
}

export interface Receipt {
  receipt_id: string
  summary: string
}
