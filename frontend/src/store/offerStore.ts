import { create } from 'zustand'
import type { RankedOffer, TrustLevel } from '../types/offer'

interface TrustUpdate {
  offer_id: string
  trust_level: TrustLevel
  explanation: string
}

interface OfferState {
  rankedOffers: RankedOffer[]
  rankingExplanation: string
  selectedOffer: RankedOffer | null
  trustUpdates: Record<string, TrustUpdate>

  setRankedOffers: (offers: RankedOffer[], explanation: string) => void
  selectOffer: (offer: RankedOffer) => void
  applyTrustUpdate: (update: TrustUpdate) => void
  reset: () => void
}

export const useOfferStore = create<OfferState>((set) => ({
  rankedOffers: [],
  rankingExplanation: '',
  selectedOffer: null,
  trustUpdates: {},

  setRankedOffers: (rankedOffers, rankingExplanation) =>
    set({ rankedOffers, rankingExplanation }),

  selectOffer: (selectedOffer) => set({ selectedOffer }),

  applyTrustUpdate: (update) =>
    set((s) => ({
      trustUpdates: { ...s.trustUpdates, [update.offer_id]: update },
    })),

  reset: () =>
    set({ rankedOffers: [], rankingExplanation: '', selectedOffer: null, trustUpdates: {} }),
}))
