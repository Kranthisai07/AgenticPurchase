import { CardElement } from '@stripe/react-stripe-js'
import type { FC } from 'react'

export const StripeCardInput: FC = () => (
  <div
    style={{
      padding: '12px 14px',
      background: '#111',
      borderRadius: 8,
      border: '1px solid #2a2a2a',
      marginBottom: 12,
    }}
  >
    <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 8 }}>
      Card details
    </label>
    <CardElement
      options={{
        style: {
          base: {
            color: '#f0f0f0',
            fontSize: '15px',
            fontFamily: '-apple-system, sans-serif',
            '::placeholder': { color: '#555' },
          },
          invalid: { color: '#ef4444' },
        },
      }}
    />
  </div>
)
