import type { FC } from 'react'
import type { RankedOffer } from '../../types/offer'
import { TrustBadge } from './TrustBadge'
import { sanitizeText, sanitizeUrl } from '../../core/sanitize'

interface OfferCardProps {
  offer: RankedOffer
  onSelect: (offer: RankedOffer) => void
  isSelected?: boolean
}

export const OfferCard: FC<OfferCardProps> = ({ offer, onSelect, isSelected = false }) => {
  const image = offer.image_urls[0]
  const sourceLabel = { ebay: 'eBay', serpapi: 'Google Shopping' }[offer.source]

  return (
    <div
      onClick={() => onSelect(offer)}
      style={{
        display: 'flex',
        gap: 12,
        padding: 14,
        borderRadius: 12,
        background: isSelected ? '#1e3a5f' : '#1a1a1a',
        border: `1px solid ${isSelected ? '#2563eb' : '#2a2a2a'}`,
        cursor: 'pointer',
        transition: 'all 0.15s',
      }}
    >
      {image && (
        <img
          src={sanitizeUrl(image)}
          alt={sanitizeText(offer.title)}
          style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 8, flexShrink: 0 }}
        />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
          <p
            style={{
              margin: 0,
              fontSize: 14,
              fontWeight: 600,
              color: '#f0f0f0',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            #{offer.rank} {sanitizeText(offer.title)}
          </p>
          <span style={{ fontSize: 15, fontWeight: 700, color: '#10b981', flexShrink: 0 }}>
            ${offer.price.amount.toFixed(2)}
          </span>
        </div>

        <p style={{ margin: '2px 0', fontSize: 12, color: '#888' }}>
          {sanitizeText(offer.seller_name)} · {sourceLabel}
          {offer.free_shipping && <span style={{ color: '#10b981', marginLeft: 6 }}>Free shipping</span>}
        </p>

        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          <TrustBadge
            level={offer.trust_score.level}
            score={offer.trust_score.score}
            explanation={offer.trust_score.explanation}
          />
          <span style={{ fontSize: 11, color: '#666' }}>
            Score: {offer.composite_score.toFixed(1)}/100
          </span>
        </div>
      </div>
    </div>
  )
}
