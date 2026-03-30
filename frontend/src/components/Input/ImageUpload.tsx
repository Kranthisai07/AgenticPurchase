import { type ChangeEvent, type FC, useRef, useState } from 'react'

interface ImageUploadProps {
  onSelect: (file: File) => void
}

export const ImageUpload: FC<ImageUploadProps> = ({ onSelect }) => {
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const url = URL.createObjectURL(file)
    setPreview(url)
    onSelect(file)
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {preview && (
        <img
          src={preview}
          alt="preview"
          style={{ width: 36, height: 36, borderRadius: 6, objectFit: 'cover' }}
        />
      )}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        title="Upload image"
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: 20,
          color: '#aaa',
          padding: 4,
        }}
      >
        📎
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleChange}
      />
    </div>
  )
}
