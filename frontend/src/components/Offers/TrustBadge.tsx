import type { FC } from 'react'
import type { TrustLevel } from '../../types/offer'

interface TrustBadgeProps {
  level: TrustLevel
  score: number
  explanation: string
}

const LEVEL_CONFIG: Record<TrustLevel, { label: string; color: string; bg: string }> = {
  LOW_RISK: { label: 'Trusted', color: '#10b981', bg: '#064e3b20' },
  MEDIUM_RISK: { label: 'Moderate', color: '#f59e0b', bg: '#78350f20' },
  HIGH_RISK: { label: 'High Risk', color: '#ef4444', bg: '#7f1d1d20' },
  INSUFFICIENT_DATA: { label: 'Limited Info', color: '#6b7280', bg: '#11182720' },
}

export const TrustBadge: FC<TrustBadgeProps> = ({ level, score, explanation }) => {
  const config = LEVEL_CONFIG[level]

  return (
    <div
      title={explanation}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 20,
        background: config.bg,
        border: `1px solid ${config.color}40`,
        fontSize: 11,
        color: config.color,
        fontWeight: 600,
        cursor: 'help',
      }}
    >
      <span>{config.label}</span>
      {score > 0 && <span style={{ opacity: 0.7 }}>{score.toFixed(0)}</span>}
    </div>
  )
}
