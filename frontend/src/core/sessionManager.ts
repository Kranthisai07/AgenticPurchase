import { apiClient } from './apiClient'

interface CreateSessionResponse {
  session_id: string
  user_id: string
  expires_at: string
}

export async function initSession(): Promise<{ sessionId: string; userId: string }> {
  const existingSessionId = sessionStorage.getItem('session_id')
  const existingUserId = sessionStorage.getItem('user_id')

  if (existingSessionId && existingUserId) {
    return { sessionId: existingSessionId, userId: existingUserId }
  }

  const response = await apiClient.post<CreateSessionResponse>('/sessions', {})
  sessionStorage.setItem('session_id', response.session_id)
  sessionStorage.setItem('user_id', response.user_id)
  return { sessionId: response.session_id, userId: response.user_id }
}
