import { type FC, useEffect } from 'react'
import { useCamera } from '../../hooks/useCamera'

interface CameraCaptureProps {
  onCapture: (file: File) => void
  onClose: () => void
}

export const CameraCapture: FC<CameraCaptureProps> = ({ onCapture, onClose }) => {
  const { videoRef, startCamera, capture, stopCamera } = useCamera()

  useEffect(() => {
    startCamera()
    return () => stopCamera()
  }, [startCamera, stopCamera])

  const handleCapture = () => {
    const file = capture()
    if (file) {
      onCapture(file as unknown as File)
      stopCamera()
      onClose()
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: '#000',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
      }}
    >
      <video
        ref={videoRef}
        autoPlay
        playsInline
        style={{ width: '100%', maxWidth: 480, borderRadius: 12 }}
      />
      <div style={{ display: 'flex', gap: 16 }}>
        <button
          onClick={handleCapture}
          style={{
            padding: '12px 32px',
            borderRadius: 24,
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            fontSize: 16,
            cursor: 'pointer',
          }}
        >
          Capture
        </button>
        <button
          onClick={() => { stopCamera(); onClose() }}
          style={{
            padding: '12px 24px',
            borderRadius: 24,
            background: '#333',
            color: '#fff',
            border: 'none',
            fontSize: 16,
            cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
