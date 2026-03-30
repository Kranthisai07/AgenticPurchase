import { useEffect, useRef, type FC } from 'react'
import { useSagaStore } from '../../store/sagaStore'
import { MessageBubble } from './MessageBubble'
import { SagaProgress } from './SagaProgress'

export const ChatArea: FC = () => {
  const { messages, agentProgress } = useSagaStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, agentProgress])

  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {messages.length === 0 && (
        <div
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'column',
            gap: 12,
            opacity: 0.4,
          }}
        >
          <span style={{ fontSize: 40 }}>🛒</span>
          <p style={{ fontSize: 16 }}>Describe a product or upload a photo to get started</p>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          role={msg.role}
          content={msg.content}
          imageUrl={msg.imageUrl}
          timestamp={msg.timestamp}
        />
      ))}

      <SagaProgress agentProgress={agentProgress} />

      <div ref={bottomRef} />
    </div>
  )
}
