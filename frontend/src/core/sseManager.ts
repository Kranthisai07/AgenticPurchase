import type {
  AgentCompleteData,
  AgentFailedData,
  AgentStartedData,
  CheckoutReadyData,
  ClarificationNeededData,
  OffersReadyData,
  SagaCompleteData,
  SagaFailedData,
  SSEEventType,
  TrustScoredData,
} from '../types/sse'

type EventHandler<T> = (data: T) => void

export interface SSEHandlers {
  onAgentStarted?: EventHandler<AgentStartedData>
  onAgentComplete?: EventHandler<AgentCompleteData>
  onAgentFailed?: EventHandler<AgentFailedData>
  onClarificationNeeded?: EventHandler<ClarificationNeededData>
  onOffersReady?: EventHandler<OffersReadyData>
  onTrustScored?: EventHandler<TrustScoredData>
  onCheckoutReady?: EventHandler<CheckoutReadyData>
  onSagaComplete?: EventHandler<SagaCompleteData>
  onSagaFailed?: EventHandler<SagaFailedData>
  onStreamEnd?: () => void
  onError?: (error: Event) => void
}

export class SSEManager {
  private source: EventSource | null = null
  private sagaId: string | null = null

  connect(sagaId: string, handlers: SSEHandlers): void {
    this.disconnect()
    this.sagaId = sagaId
    const BASE_URL = import.meta.env.VITE_API_URL ?? ''
    this.source = new EventSource(`${BASE_URL}/saga/${sagaId}/stream`)

    const parseAndCall = <T>(
      handler: EventHandler<T> | undefined,
      event: MessageEvent
    ) => {
      if (!handler) return
      try {
        handler(JSON.parse(event.data) as T)
      } catch {
        console.error('SSE parse error', event.data)
      }
    }

    this.source.addEventListener('agent_started', (e) =>
      parseAndCall(handlers.onAgentStarted, e as MessageEvent)
    )
    this.source.addEventListener('agent_complete', (e) =>
      parseAndCall(handlers.onAgentComplete, e as MessageEvent)
    )
    this.source.addEventListener('agent_failed', (e) =>
      parseAndCall(handlers.onAgentFailed, e as MessageEvent)
    )
    this.source.addEventListener('clarification_needed', (e) =>
      parseAndCall(handlers.onClarificationNeeded, e as MessageEvent)
    )
    this.source.addEventListener('offers_ready', (e) =>
      parseAndCall(handlers.onOffersReady, e as MessageEvent)
    )
    this.source.addEventListener('trust_scored', (e) =>
      parseAndCall(handlers.onTrustScored, e as MessageEvent)
    )
    this.source.addEventListener('checkout_ready', (e) =>
      parseAndCall(handlers.onCheckoutReady, e as MessageEvent)
    )
    this.source.addEventListener('saga_complete', (e) =>
      parseAndCall(handlers.onSagaComplete, e as MessageEvent)
    )
    this.source.addEventListener('saga_failed', (e) =>
      parseAndCall(handlers.onSagaFailed, e as MessageEvent)
    )
    this.source.addEventListener('stream_end', () => {
      handlers.onStreamEnd?.()
      this.disconnect()
    })

    if (handlers.onError) {
      this.source.onerror = handlers.onError
    }
  }

  disconnect(): void {
    if (this.source) {
      this.source.close()
      this.source = null
    }
  }

  get isConnected(): boolean {
    return this.source?.readyState === EventSource.OPEN
  }
}

export const sseManager = new SSEManager()
