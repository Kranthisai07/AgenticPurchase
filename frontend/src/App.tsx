import { useEffect, type FC } from 'react'
import { ChatArea } from './components/Chat/ChatArea'
import { InputBar } from './components/Input/InputBar'
import { CheckoutFlow } from './components/Checkout/CheckoutFlow'
import { RankedOfferList } from './components/Offers/RankedOfferList'
import { initSession } from './core/sessionManager'
import { useOfferStore } from './store/offerStore'
import { useSagaStore } from './store/sagaStore'
import { useSessionStore } from './store/sessionStore'

export const App: FC = () => {
  const { setSession } = useSessionStore()
  const { status } = useSagaStore()
  const { rankedOffers, selectedOffer, selectOffer } = useOfferStore()

  useEffect(() => {
    initSession()
      .then(({ sessionId, userId }) => setSession(sessionId, userId))
      .catch(console.error)
  }, [setSession])

  const showOffers = rankedOffers.length > 0 && status === 'ranking'
  const showCheckout = selectedOffer !== null

  return (
    <div
      style={{
        display: 'flex',
        height: '100dvh',
        width: '100vw',
        background: '#0f0f0f',
      }}
    >
      {/* Chat panel */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          maxWidth: showOffers || showCheckout ? 520 : '100%',
          borderRight: showOffers || showCheckout ? '1px solid #1e1e1e' : 'none',
        }}
      >
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid #1e1e1e',
            fontWeight: 700,
            fontSize: 16,
          }}
        >
          Agentic Purchase
        </div>
        <ChatArea />
        <InputBar />
      </div>

      {/* Offers panel */}
      {showOffers && !showCheckout && (
        <div
          style={{
            width: 480,
            overflowY: 'auto',
            padding: 16,
            borderRight: '1px solid #1e1e1e',
          }}
        >
          <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>
            Top Offers
          </h2>
          <RankedOfferList onSelect={(offer) => selectOffer(offer)} />
        </div>
      )}

      {/* Checkout panel */}
      {showCheckout && selectedOffer && (
        <div style={{ width: 420, overflowY: 'auto' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid #1e1e1e', fontWeight: 700 }}>
            Checkout
          </div>
          <CheckoutFlow
            offer={selectedOffer}
            offerIndex={rankedOffers.indexOf(selectedOffer)}
          />
        </div>
      )}
    </div>
  )
}
