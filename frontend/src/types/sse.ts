import type { RankedOffer, TrustLevel } from './offer'

export type SSEEventType =
  | 'session_ready'
  | 'agent_started'
  | 'agent_complete'
  | 'agent_failed'
  | 'clarification_needed'
  | 'offers_ready'
  | 'trust_scored'
  | 'checkout_ready'
  | 'saga_complete'
  | 'saga_failed'
  | 'stream_end'

export interface SessionReadyData {
  session_id: string
  saga_id: string
}

export interface AgentStartedData {
  agent: string
  message: string
}

export interface AgentCompleteData {
  agent: string
  duration_ms: number
}

export interface AgentFailedData {
  agent: string
  error: string
}

export interface ClarificationNeededData {
  questions: string[]
  partial_intent: Record<string, unknown>
}

export interface OffersReadyData {
  offers: RankedOffer[]
  ranking_explanation: string
}

export interface TrustScoredData {
  offer_id: string
  trust_level: TrustLevel
  explanation: string
}

export interface CheckoutReadyData {
  client_secret: string
  amount: number
  currency: string
}

export interface SagaCompleteData {
  receipt_id: string
  summary: string
}

export interface SagaFailedData {
  reason: string
  user_message: string
  retry_allowed: boolean
}

export interface SSEEvent<T = unknown> {
  type: SSEEventType
  data: T
}
