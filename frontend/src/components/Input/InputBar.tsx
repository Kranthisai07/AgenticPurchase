import { type FC, useState } from 'react'
import { useSaga } from '../../hooks/useSaga'
import { useSagaStore } from '../../store/sagaStore'
import { CameraCapture } from './CameraCapture'
import { ImageUpload } from './ImageUpload'
import { TextInput } from './TextInput'

export const InputBar: FC = () => {
  const [text, setText] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [showCamera, setShowCamera] = useState(false)
  const { status } = useSagaStore()
  const { startSaga } = useSaga()

  const isDisabled = status !== 'idle' && status !== 'failed'

  const handleSubmit = async () => {
    if (!text.trim() && !selectedFile) return
    await startSaga(text, selectedFile ?? undefined)
    setText('')
    setSelectedFile(null)
  }

  return (
    <>
      {showCamera && (
        <CameraCapture
          onCapture={(file) => setSelectedFile(file)}
          onClose={() => setShowCamera(false)}
        />
      )}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          background: '#1a1a1a',
          borderTop: '1px solid #2a2a2a',
          borderRadius: '0 0 12px 12px',
        }}
      >
        <ImageUpload onSelect={setSelectedFile} />
        <button
          type="button"
          onClick={() => setShowCamera(true)}
          title="Take photo"
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: '#aaa', padding: 4 }}
        >
          📷
        </button>
        <TextInput
          value={text}
          onChange={setText}
          onSubmit={handleSubmit}
          disabled={isDisabled}
        />
        <button
          onClick={handleSubmit}
          disabled={isDisabled || (!text.trim() && !selectedFile)}
          style={{
            padding: '8px 16px',
            borderRadius: 18,
            background: isDisabled ? '#333' : '#2563eb',
            color: '#fff',
            border: 'none',
            cursor: isDisabled ? 'not-allowed' : 'pointer',
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          Search
        </button>
      </div>
    </>
  )
}
