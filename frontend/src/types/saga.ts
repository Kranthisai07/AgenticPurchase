export type SagaStatus =
  | 'idle'
  | 'created'
  | 'vision'
  | 'intent'
  | 'sourcing'
  | 'trust'
  | 'ranking'
  | 'awaiting_user'
  | 'checkout'
  | 'complete'
  | 'failed'

export interface AgentProgress {
  agent: string
  status: 'running' | 'complete' | 'failed'
  message?: string
  duration_ms?: number
  error?: string
}
