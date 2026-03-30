import type { FC } from 'react'
import type { AgentProgress } from '../../types/saga'

interface SagaProgressProps {
  agentProgress: AgentProgress[]
}

const AGENT_LABELS: Record<string, string> = {
  vision: 'Analyzing image',
  intent: 'Understanding request',
  sourcing_ebay: 'Searching eBay',
  sourcing_serpapi: 'Searching Google Shopping',
  trust: 'Evaluating sellers',
  ranking: 'Ranking offers',
  checkout: 'Processing payment',
}

const statusColor = {
  running: '#f59e0b',
  complete: '#10b981',
  failed: '#ef4444',
}

export const SagaProgress: FC<SagaProgressProps> = ({ agentProgress }) => {
  if (!agentProgress.length) return null

  return (
    <div
      style={{
        padding: '8px 14px',
        background: '#111',
        borderRadius: 10,
        marginBottom: 8,
        fontSize: 12,
      }}
    >
      {agentProgress.map((p) => (
        <div
          key={p.agent}
          style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: statusColor[p.status],
              flexShrink: 0,
            }}
          />
          <span style={{ color: '#aaa' }}>
            {AGENT_LABELS[p.agent] ?? p.agent}
            {p.status === 'complete' && p.duration_ms ? ` (${p.duration_ms}ms)` : ''}
            {p.status === 'failed' ? ` — ${p.error}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}
