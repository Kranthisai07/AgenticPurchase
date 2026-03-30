import { useCallback, useState } from 'react'
import { useStripe, useElements, CardElement } from '@stripe/react-stripe-js'
import { apiClient } from '../core/apiClient'
import { useSagaStore } from '../store/sagaStore'
import type { CheckoutStatus } from '../types/checkout'

export function useCheckout() {
  const stripe = useStripe()
  const elements = useElements()
  const { sagaId } = useSagaStore()
  const [status, setStatus] = useState<CheckoutStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const initiateCheckout = useCallback(
    async (selectedOfferIndex: number, shippingAddress: Record<string, string>) => {
      if (!stripe || !elements || !sagaId) return
      setStatus('pending')
      setError(null)

      const cardElement = elements.getElement(CardElement)
      if (!cardElement) return

      // Tokenize card — raw card data stays in Stripe's iframe
      const { paymentMethod, error: pmError } = await stripe.createPaymentMethod({
        type: 'card',
        card: cardElement,
      })

      if (pmError || !paymentMethod) {
        setError(pmError?.message ?? 'Failed to tokenize card')
        setStatus('failed')
        return
      }

      // Send token (not card data) to backend via saga resume
      await apiClient.post(`/saga/${sagaId}/resume`, {
        resume_at: 'offer_selection',
        selected_offer_index: selectedOfferIndex,
        stripe_payment_method_id: paymentMethod.id,
        shipping_address: shippingAddress,
      })

      setStatus('confirming')
      // SSE stream will emit checkout_ready with client_secret
    },
    [stripe, elements, sagaId]
  )

  const confirmPayment = useCallback(
    async (clientSecret: string) => {
      if (!stripe) return
      setStatus('confirming')

      const { error: confirmError } = await stripe.confirmCardPayment(clientSecret)
      if (confirmError) {
        setError(confirmError.message ?? 'Payment confirmation failed')
        setStatus('failed')
      } else {
        setStatus('complete')
      }
    },
    [stripe]
  )

  return { status, error, initiateCheckout, confirmPayment }
}
