const BASE_URL = import.meta.env.VITE_API_URL ?? ''

interface RequestOptions {
  method?: string
  body?: FormData | Record<string, unknown> | null
  headers?: Record<string, string>
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {} } = options

  const isFormData = body instanceof FormData
  const requestHeaders: Record<string, string> = { ...headers }

  if (!isFormData && body) {
    requestHeaders['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: requestHeaders,
    body: isFormData ? body : body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail ?? `HTTP ${response.status}`)
  }

  return response.json() as Promise<T>
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: FormData | Record<string, unknown>) =>
    request<T>(path, { method: 'POST', body }),
}
