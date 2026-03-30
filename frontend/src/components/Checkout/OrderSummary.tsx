import type { FC } from 'react'
import type { RankedOffer } from '../../types/offer'
import { sanitizeText, sanitizeUrl } from '../../core/sanitize'

interface OrderSummaryProps {
  offer: RankedOffer
}

export const OrderSummary: FC<OrderSummaryProps> = ({ offer }) => (
  <div
    style={{
      padding: 14,
      background: '#111',
      borderRadius: 10,
      marginBottom: 16,
    }}
  >
    <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#f0f0f0' }}>
      Order Summary
    </h3>
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      {offer.image_urls[0] && (
        <img
          src={sanitizeUrl(offer.image_urls[0])}
          alt={sanitizeText(offer.title)}
          style={{ width: 56, height: 56, borderRadius: 6, objectFit: 'cover' }}
        />
      )}
      <div style={{ flex: 1 }}>
        <p style={{ fontSize: 13, color: '#f0f0f0', margin: 0 }}>{sanitizeText(offer.title)}</p>
        <p style={{ fontSize: 12, color: '#888', margin: '2px 0' }}>From: {sanitizeText(offer.seller_name)}</p>
        <p style={{ fontSize: 15, fontWeight: 700, color: '#10b981', margin: '4px 0 0' }}>
          ${offer.price.amount.toFixed(2)} {offer.price.currency}
        </p>
        {offer.free_shipping && (
          <p style={{ fontSize: 11, color: '#10b981', margin: 0 }}>+ Free shipping</p>
        )}
      </div>
    </div>
  </div>
)
