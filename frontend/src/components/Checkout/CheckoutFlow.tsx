import { Elements } from '@stripe/react-stripe-js'
import { loadStripe } from '@stripe/stripe-js'
import { type FC, useState } from 'react'
import { useCheckout } from '../../hooks/useCheckout'
import type { RankedOffer } from '../../types/offer'
import { OrderSummary } from './OrderSummary'
import { StripeCardInput } from './StripeElements'

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY ?? '')

interface CheckoutFlowProps {
  offer: RankedOffer
  offerIndex: number
  clientSecret?: string
}

const CheckoutForm: FC<CheckoutFlowProps> = ({ offer, offerIndex, clientSecret }) => {
  const { status, error, initiateCheckout, confirmPayment } = useCheckout()
  const [name, setName] = useState('')
  const [address, setAddress] = useState({ line1: '', city: '', state: '', postal_code: '', country: 'US' })

  const handlePay = async () => {
    if (clientSecret) {
      await confirmPayment(clientSecret)
    } else {
      await initiateCheckout(offerIndex, { name, ...address })
    }
  }

  if (status === 'complete') {
    return (
      <div style={{ textAlign: 'center', padding: 24, color: '#10b981' }}>
        <p style={{ fontSize: 24, marginBottom: 8 }}>✓</p>
        <p style={{ fontSize: 16, fontWeight: 600 }}>Payment successful!</p>
      </div>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      <OrderSummary offer={offer} />

      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 4 }}>Full name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2a2a2a', borderRadius: 8, color: '#f0f0f0', fontSize: 14 }}
        />
      </div>

      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 4 }}>Address</label>
        <input
          value={address.line1}
          onChange={(e) => setAddress({ ...address, line1: e.target.value })}
          placeholder="Street address"
          style={{ width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2a2a2a', borderRadius: 8, color: '#f0f0f0', fontSize: 14, marginBottom: 6 }}
        />
        <div style={{ display: 'flex', gap: 6 }}>
          <input value={address.city} onChange={(e) => setAddress({ ...address, city: e.target.value })} placeholder="City" style={{ flex: 1, padding: '10px 12px', background: '#111', border: '1px solid #2a2a2a', borderRadius: 8, color: '#f0f0f0', fontSize: 14 }} />
          <input value={address.state} onChange={(e) => setAddress({ ...address, state: e.target.value })} placeholder="State" style={{ width: 80, padding: '10px 12px', background: '#111', border: '1px solid #2a2a2a', borderRadius: 8, color: '#f0f0f0', fontSize: 14 }} />
          <input value={address.postal_code} onChange={(e) => setAddress({ ...address, postal_code: e.target.value })} placeholder="ZIP" style={{ width: 90, padding: '10px 12px', background: '#111', border: '1px solid #2a2a2a', borderRadius: 8, color: '#f0f0f0', fontSize: 14 }} />
        </div>
      </div>

      <StripeCardInput />

      {error && <p style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{error}</p>}

      <button
        onClick={handlePay}
        disabled={status === 'pending' || status === 'confirming'}
        style={{
          width: '100%',
          padding: '14px',
          background: status === 'pending' ? '#333' : '#2563eb',
          color: '#fff',
          border: 'none',
          borderRadius: 10,
          fontSize: 15,
          fontWeight: 600,
          cursor: status === 'pending' ? 'not-allowed' : 'pointer',
        }}
      >
        {status === 'pending' || status === 'confirming' ? 'Processing...' : `Pay $${offer.price.amount.toFixed(2)}`}
      </button>
    </div>
  )
}

export const CheckoutFlow: FC<CheckoutFlowProps> = (props) => (
  <Elements stripe={stripePromise}>
    <CheckoutForm {...props} />
  </Elements>
)
