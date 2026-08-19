import type { TripPlanResponse, TripRequest } from '@/types/trip'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const message = body?.detail || body?.message || `请求失败（${response.status}）`
    throw new ApiError(message, response.status)
  }

  return response.json() as Promise<T>
}

export function generateTripPlan(payload: TripRequest): Promise<TripPlanResponse> {
  return request<TripPlanResponse>('/api/trip/plan', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function healthCheck(): Promise<{ status: string }> {
  return request<{ status: string }>('/health')
}
