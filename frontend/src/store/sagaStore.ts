import { create } from 'zustand'
import type { AgentProgress, SagaStatus } from '../types/saga'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  imageUrl?: string
  timestamp: Date
}

interface SagaState {
  sagaId: string | null
  status: SagaStatus
  agentProgress: AgentProgress[]
  messages: Message[]
  clarificationQuestions: string[]
  nearTieQuestion: string | null

  setSagaId: (id: string) => void
  setStatus: (status: SagaStatus) => void
  addAgentProgress: (progress: AgentProgress) => void
  updateAgentProgress: (agent: string, update: Partial<AgentProgress>) => void
  addMessage: (msg: Omit<Message, 'id' | 'timestamp'>) => void
  setClarificationQuestions: (questions: string[]) => void
  setNearTieQuestion: (q: string | null) => void
  reset: () => void
}

const initialState = {
  sagaId: null,
  status: 'idle' as SagaStatus,
  agentProgress: [],
  messages: [],
  clarificationQuestions: [],
  nearTieQuestion: null,
}

export const useSagaStore = create<SagaState>((set) => ({
  ...initialState,

  setSagaId: (sagaId) => set({ sagaId }),
  setStatus: (status) => set({ status }),

  addAgentProgress: (progress) =>
    set((s) => ({ agentProgress: [...s.agentProgress, progress] })),

  updateAgentProgress: (agent, update) =>
    set((s) => ({
      agentProgress: s.agentProgress.map((p) =>
        p.agent === agent ? { ...p, ...update } : p
      ),
    })),

  addMessage: (msg) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { ...msg, id: crypto.randomUUID(), timestamp: new Date() },
      ],
    })),

  setClarificationQuestions: (clarificationQuestions) =>
    set({ clarificationQuestions }),

  setNearTieQuestion: (nearTieQuestion) => set({ nearTieQuestion }),

  reset: () => set(initialState),
}))
