import { useCallback } from 'react'
import { apiClient } from '../core/apiClient'
import { sseManager } from '../core/sseManager'
import { useOfferStore } from '../store/offerStore'
import { useSagaStore } from '../store/sagaStore'
import { useSessionStore } from '../store/sessionStore'

interface StartSagaResponse {
  saga_id: string
  session_id: string
  stream_url: string
}

export function useSaga() {
  const { sessionId, userId } = useSessionStore()
  const {
    setSagaId,
    setStatus,
    addAgentProgress,
    updateAgentProgress,
    addMessage,
    setClarificationQuestions,
    setNearTieQuestion,
    reset: resetSaga,
  } = useSagaStore()
  const { setRankedOffers, applyTrustUpdate, reset: resetOffers } = useOfferStore()

  const startSaga = useCallback(
    async (userText: string, imageFile?: File) => {
      if (!sessionId || !userId) throw new Error('No active session')

      resetSaga()
      resetOffers()

      const form = new FormData()
      form.append('session_id', sessionId)
      form.append('user_id', userId)
      if (userText) form.append('user_text', userText)
      if (imageFile) form.append('image', imageFile)

      addMessage({ role: 'user', content: userText })

      const response = await apiClient.post<StartSagaResponse>('/saga', form)
      setSagaId(response.saga_id)
      setStatus('created')

      // Connect SSE stream
      sseManager.connect(response.saga_id, {
        onAgentStarted: (data) => {
          addAgentProgress({ agent: data.agent, status: 'running', message: data.message })
          setStatus(data.agent as never)
        },
        onAgentComplete: (data) => {
          updateAgentProgress(data.agent, { status: 'complete', duration_ms: data.duration_ms })
        },
        onAgentFailed: (data) => {
          updateAgentProgress(data.agent, { status: 'failed', error: data.error })
        },
        onClarificationNeeded: (data) => {
          setClarificationQuestions(data.questions)
          setStatus('awaiting_user')
          addMessage({
            role: 'assistant',
            content: data.questions.join('\n'),
          })
        },
        onOffersReady: (data) => {
          setRankedOffers(data.offers, data.ranking_explanation)
          setStatus('ranking')
          addMessage({
            role: 'assistant',
            content: `I found ${data.offers.length} offers. ${data.ranking_explanation}`,
          })
        },
        onTrustScored: (data) => applyTrustUpdate(data),
        onCheckoutReady: () => setStatus('checkout'),
        onSagaComplete: (data) => {
          setStatus('complete')
          addMessage({
            role: 'assistant',
            content: `Purchase complete! Receipt: ${data.receipt_id}. ${data.summary}`,
          })
        },
        onSagaFailed: (data) => {
          setStatus('failed')
          addMessage({ role: 'assistant', content: data.user_message })
        },
        onStreamEnd: () => sseManager.disconnect(),
      })
    },
    [sessionId, userId, setSagaId, setStatus, addAgentProgress, updateAgentProgress, addMessage, setClarificationQuestions, resetSaga, resetOffers, setRankedOffers, applyTrustUpdate]
  )

  const resumeSaga = useCallback(
    async (sagaId: string, resumeAt: string, userResponse?: string) => {
      await apiClient.post(`/saga/${sagaId}/resume`, {
        resume_at: resumeAt,
        user_response: userResponse,
      })
    },
    []
  )

  return { startSaga, resumeSaga }
}
