import type { Alarm, Ramp, Snapshot } from './types'

const TOKEN_KEY = 'kotivalo-token'

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return '' // storage blocked (private mode)
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* storage blocked: the token lasts for this page only */
  }
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request(method: string, path: string, body?: unknown): Promise<Snapshot> {
  const headers: Record<string, string> = { 'X-Token': getToken() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'unreachable')
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, data.error ?? `HTTP ${response.status}`)
  return data as Snapshot
}

export const api = {
  state: () => request('GET', '/api/state'),
  lamp: (ieee: string, action: 'on' | 'off' | 'toggle' | 'level' | 'kelvin', value?: number) =>
    request('POST', `/api/lights/${ieee}`, { action, value }),
  refreshLamp: (ieee: string) => request('POST', `/api/lights/${ieee}/refresh`, {}),
  wakeup: (change: { light?: string | null; alarms?: Alarm[]; ramp?: Ramp }) =>
    request('PUT', '/api/wakeup', change),
  night: (start: string, end: string) => request('PUT', '/api/night', { start, end }),
  device: (ieee: string, change: { name?: string; room?: string }) =>
    request('PUT', `/api/devices/${ieee}`, change),
  removeDevice: (ieee: string) => request('DELETE', `/api/devices/${ieee}`),
  skip: (key: string, skip: boolean) => request('POST', '/api/skip', { key, skip }),
  testSunrise: (minutes: number) => request('POST', '/api/sunrise/test', { minutes }),
  stopSunrise: () => request('POST', '/api/sunrise/stop', {}),
  permit: (seconds: number) => request('POST', '/api/permit', { seconds }),
}

export function eventsUrl(): string {
  const token = getToken()
  return token ? `/api/events?token=${encodeURIComponent(token)}` : '/api/events'
}
