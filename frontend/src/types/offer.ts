export type TrustLevel = 'LOW_RISK' | 'MEDIUM_RISK' | 'HIGH_RISK' | 'INSUFFICIENT_DATA'

export interface TrustSignals {
  rating: number | null
  review_count: number | null
  account_age_days: number | null
  has_return_policy: boolean | null
  fulfilled_orders: number | null
  feedback_percentage: number | null
}

export interface TrustScore {
  score: number
  level: TrustLevel
  signals: TrustSignals
  explanation: string
  data_source: 'ebay_api' | 'insufficient'
}

export interface Money {
  amount: number
  currency: string
}

export interface Offer {
  offer_id: string
  source: 'ebay' | 'serpapi'
  title: string
  description: string | null
  price: Money
  url: string
  image_urls: string[]
  seller_id: string
  seller_name: string
  free_shipping: boolean
  estimated_delivery_days: number | null
  condition: 'new' | 'used' | 'refurbished' | 'unknown'
}

export interface ScoredOffer extends Offer {
  trust_score: TrustScore
}

export interface RankedOffer extends ScoredOffer {
  composite_score: number
  rank: number
  price_score: number
  relevance_score: number
  rating_score: number
  shipping_score: number
}
