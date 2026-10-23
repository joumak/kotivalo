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
  dimmable: boolean // false: on/off only (a smart plug)
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
  reachable: boolean | null // null until the service has talked to it
  last_report: number | null // unix seconds of the lamp's last report
  wakeup: boolean
  power_on: 'on' | 'previous'
  owner: Owner
  owner_until: string | null // motion: switches off then (null while the room is occupied)
  profile: 'day' | 'night' | null // motion: which profile switched it on
  has_motion: boolean // a motion sensor controls it
  motion_paused: boolean // switched off by hand: motion waits until the room has been empty
  hand_only: boolean // "Vain käsin": nothing automatic changes it until released (an alarm ends it)
  members: string[] // a fixture's bulbs; empty for a single bulb
}

export interface Profile {
  level: number // 2..254
  kelvin: number
}

export interface MotionRule {
  sensor: string
  lights: string[]
  enabled: boolean
  dark_lux: number | null // only when darker than this (a bright/dim sensor: only when dim); null = always
  off_after_min: number
  day: Profile
  night: Profile
}

export interface Sensor {
  ieee: string
  name: string
  room: string
  occupied: boolean
  last_report: string | null
  lux: number | null
  bright: boolean | null // a sensor that only tells bright from dim (the SNZB-06P)
  battery: number | null
  configured: boolean
  rule: MotionRule | null
}

export type RemoteAction =
  | 'on'
  | 'off'
  | 'toggle'
  | 'brighter'
  | 'dimmer'
  | 'brighter_hold'
  | 'dimmer_hold'
  | 'dim_stop'
  | 'warmer'
  | 'cooler'
  | 'warmer_hold'
  | 'cooler_hold'
  | 'arrow_stop'

export interface Remote {
  ieee: string
  name: string
  room: string
  model: string | null
  configured: boolean // its buttons are bound to the Pi
  battery: number | null // known after its first report since the service started
  last_action: RemoteAction | null
  last_press: string | null // ISO
  lights: string[] // the lamps it controls
  firmware: FirmwareUpdate | null // an update started since the service started
}

export interface FirmwareUpdate {
  state: 'waiting' | 'updating' | 'done' | 'failed' | 'none'
  progress: number // percent
}

export interface WeatherPoint {
  time: string // UTC ISO, the start of the hour
  temperature: number // °C
  symbol: string | null // MET symbol code, e.g. "partlycloudy_day"
  wind: number | null // m/s
  precipitation: number | null // mm in the following hour
}

export interface WeatherPlace {
  name: string
  lat: number
  lon: number
}

export interface Weather {
  location: WeatherPlace | null
  forecast: { updated: string | null; now: WeatherPoint; hours: WeatherPoint[] } | null
  stale: boolean // the last good forecast is too old to show
}

export interface Place extends WeatherPlace {
  region: string
  country: string
}

export type MasterCommand = 'on' | 'off' | 'cancel'

export interface MasterStatus {
  any_on: boolean
  remembered: string[] // lamps lit at the last master-off; "on" brings them back
  off_at: string | null // a delayed master-off (UTC ISO)
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

export type DeviceKind = 'light' | 'motion' | 'remote' | 'other' | 'fixture'

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
  dimmable: boolean // false for a smart plug (a lamp that only switches)
  members: string[] // a fixture's bulbs
  fixture: string | null // the fixture a bulb belongs to
  parent: string | null // the device a second (third...) channel is on
  channel: number | null // 1, 2... on a multi-channel device (a 2-gang dimmer)
}

export interface RunRecord {
  kind: 'alarm' | 'test'
  key: string | null
  light: string | null
  result: string
  failures: number
  finished: string
}

export interface Radio {
  type: string // xbee | ezsp | znp
  fake: boolean // `serve --fake`: simulated devices, no radio
  manufacturer: string | null
  model: string | null
  firmware: string | null
  channel: number | null
  pan_id: string | null // "0xAE6B"
  started: number | null // unix seconds
  heard: number | null // unix seconds: the last frame from any device
}

export interface Snapshot {
  boot: string // changes when the service restarts
  seq: number // grows with every snapshot of one boot
  now: string
  timezone: string
  clock_synced: boolean | null
  radio: Radio
  lights: Lamp[]
  wakeup: { light: string | null; alarms: Alarm[]; ramp: Ramp }
  night: { start: string; end: string }
  sensors: Sensor[]
  remotes: Remote[]
  weather: Weather
  master: MasterStatus
  sunrise: SunriseRun | null
  upcoming: Upcoming[]
  last_run: RunRecord | null
  last_test: RunRecord | null
  pairing_until: string | null
  last_event: string | null
  devices: DeviceInfo[]
  auth_required: boolean
}
