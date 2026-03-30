import type { FC } from 'react'
import { sanitizeText } from '../../core/sanitize'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  imageUrl?: string
  timestamp: Date
}

export const MessageBubble: FC<MessageBubbleProps> = ({ role, content, imageUrl, timestamp }) => {
  const isUser = role === 'user'

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 12,
      }}
    >
      <div
        style={{
          maxWidth: '72%',
          padding: '10px 14px',
          borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
          background: isUser ? '#2563eb' : '#1e1e1e',
          color: '#f0f0f0',
          fontSize: 14,
          lineHeight: 1.5,
        }}
      >
        {imageUrl && (
          <img
            src={imageUrl}
            alt="uploaded"
            style={{ width: '100%', borderRadius: 8, marginBottom: 8 }}
          />
        )}
        <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{sanitizeText(content)}</p>
        <span style={{ fontSize: 11, opacity: 0.5, display: 'block', marginTop: 4 }}>
          {timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
    </div>
  )
}
