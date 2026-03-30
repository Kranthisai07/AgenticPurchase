import type { FC } from 'react'
import { useOfferStore } from '../../store/offerStore'
import { OfferCard } from './OfferCard'
import type { RankedOffer } from '../../types/offer'

interface RankedOfferListProps {
  onSelect: (offer: RankedOffer) => void
}

export const RankedOfferList: FC<RankedOfferListProps> = ({ onSelect }) => {
  const { rankedOffers, selectedOffer, rankingExplanation, selectOffer } = useOfferStore()

  if (!rankedOffers.length) return null

  const handleSelect = (offer: RankedOffer) => {
    selectOffer(offer)
    onSelect(offer)
  }

  return (
    <div style={{ padding: '12px 0' }}>
      {rankingExplanation && (
        <p style={{ fontSize: 13, color: '#888', marginBottom: 10 }}>{rankingExplanation}</p>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rankedOffers.map((offer) => (
          <OfferCard
            key={offer.offer_id}
            offer={offer}
            onSelect={handleSelect}
            isSelected={selectedOffer?.offer_id === offer.offer_id}
          />
        ))}
      </div>
    </div>
  )
}
