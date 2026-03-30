import { type FC, type KeyboardEvent, useRef } from 'react'

interface TextInputProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  placeholder?: string
  disabled?: boolean
}

export const TextInput: FC<TextInputProps> = ({
  value,
  onChange,
  onSubmit,
  placeholder = 'Describe the product you want to buy...',
  disabled = false,
}) => {
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSubmit()
    }
  }

  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      placeholder={placeholder}
      disabled={disabled}
      rows={1}
      style={{
        flex: 1,
        resize: 'none',
        background: 'transparent',
        border: 'none',
        outline: 'none',
        color: '#f0f0f0',
        fontSize: 15,
        lineHeight: 1.5,
        padding: '10px 12px',
        fontFamily: 'inherit',
      }}
    />
  )
}
