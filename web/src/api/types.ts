// The service's /api/state snapshot (version 2 fields only).

export interface LightState {
  on: boolean | null
  level: number | null // 2..254
  mireds: number | null
  kelvin: number | null
}

export interface Caps {
  model: string | null
  manufacturer: string | null
  supports_ct: boolean
  min_mireds: number
  max_mireds: number
}

export type Owner = 'off' | 'manual' | 'motion' | 'sunrise'

export interface Lamp {
  ieee: string
  name: string
  room: string
  model: string | null
  paired: boolean
  available: boolean
  caps: Caps
  kelvin_range: [number, number]
  kelvin_step: number
  state: LightState
  error: string | null
  wakeup: boolean
  power_on: 'on' | 'previous'
  owner: Owner | null
}

export interface Alarm {
  enabled: boolean
  time: string // HH:MM, local
}

export interface Ramp {
  duration_min: number
  gamma: number
  warm_kelvin: number
  cool_kelvin: number
  hold_min: number
}

export interface SunriseRun {
  kind: 'alarm' | 'test'
  key: string | null
  light: string | null
  phase: 'starting' | 'ramp' | 'hold' | 'done'
  start: string
  end: string
  off: string | null
  progress: number
  failures: number
}

export interface Upcoming {
  key: string
  alarm: string // UTC ISO
  start: string
  skipped: boolean
}

export type DeviceKind = 'light' | 'motion' | 'remote' | 'other'

export interface DeviceInfo {
  ieee: string
  name: string
  room: string
  kind: DeviceKind
  model: string | null
  manufacturer: string | null
  nwk: string | null
  last_seen: number | null // unix seconds
  initialized: boolean
  paired: boolean
  wakeup: boolean
}

export interface RunRecord {
  kind: 'alarm' | 'test'
  key: string | null
  light: string | null
  result: string
  failures: number
  finished: string
}

export interface Snapshot {
  now: string
  timezone: string
  clock_synced: boolean | null
  radio: { type: string; fake: boolean }
  lights: Lamp[]
  wakeup: { light: string | null; alarms: Alarm[]; ramp: Ramp }
  night: { start: string; end: string }
  sunrise: SunriseRun | null
  upcoming: Upcoming[]
  last_run: RunRecord | null
  last_test: RunRecord | null
  pairing_until: string | null
  last_event: string | null
  devices: DeviceInfo[]
  auth_required: boolean
}
