import { create } from 'zustand'

interface SessionState {
  sessionId: string | null
  userId: string | null
  setSession: (sessionId: string, userId: string) => void
  clearSession: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  sessionId: sessionStorage.getItem('session_id'),
  userId: sessionStorage.getItem('user_id'),
  setSession: (sessionId, userId) => {
    sessionStorage.setItem('session_id', sessionId)
    sessionStorage.setItem('user_id', userId)
    set({ sessionId, userId })
  },
  clearSession: () => {
    sessionStorage.removeItem('session_id')
    sessionStorage.removeItem('user_id')
    set({ sessionId: null, userId: null })
  },
}))
