// English UI text. `fi.ts` must provide every key (the type checker enforces it).

const ago = (minutes: number) =>
  minutes < 1
    ? 'just now'
    : minutes < 60
      ? `${minutes} min ago`
      : minutes < 48 * 60
        ? `${Math.round(minutes / 60)} h ago`
        : `${Math.round(minutes / 1440)} days ago`

const inTime = (minutes: number) => {
  if (minutes < 1) return 'now'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `in ${m} min`
  if (h < 48) return `in ${h} h ${m} min`
  return `in ${Math.round(h / 24)} days`
}

export const en = {
  locale: 'en-GB',
  nav: { lights: 'Lights', wakeup: 'Wake-up', devices: 'Devices', settings: 'Settings' },
  banner: {
    offline: 'No connection to Kotivalo. Trying again…',
    unauthorized: 'This page needs the access code. Enter it in Settings.',
    clock: "The clock isn't synced yet, so alarms use the Pi's own clock.",
  },
  time: { ago, inTime },
  lamp: {
    off: 'Off',
    level: (percent: number) => `${percent} %`,
    kelvin: (kelvin: number) => `${Math.round(kelvin / 50) * 50} K`,
    brightness: 'Brightness',
    warmth: 'Warmth',
    warm: 'Warm',
    cool: 'Cool',
    notResponding: 'Not responding',
    turnOn: (name: string) => `Turn on ${name}`,
    turnOff: (name: string) => `Turn off ${name}`,
    sunrise: (time: string) => `Sunrise, full at ${time}`,
    sunriseHold: (time: string) => `Sunrise done, off at ${time}`,
    sunriseDone: 'Sunrise done',
    motionOn: 'On by motion',
    nightLight: 'Night light',
    byHand: 'On by hand',
    offMotionPaused: 'Off, motion paused',
    offAt: (status: string, time: string) => `${status}, off at ${time}`,
    wakeupLamp: 'Wake-up lamp',
    noRoom: 'Other lamps',
    noLamps: 'No lamps yet. Add one under Devices.',
    pickOne: 'Pick a lamp to adjust it.',
  },
  wakeup: {
    noAlarm: 'No alarm set. Pick the days below.',
    when: (weekday: string, relative: string) => `${weekday}, ${relative}`,
    lightStarts: (time: string) => `Light starts at ${time}`,
    offAt: (time: string) => `off at ${time}`,
    staysOn: 'stays on',
    skip: 'Skip this one',
    unskip: "Don't skip",
    skipped: 'Skipped',
    later: 'After that',
    days: 'Alarm days',
    dayOff: 'Off',
    editTitle: (weekday: string) => `Alarm on ${weekday}`,
    enabled: 'Wake me up on this day',
    time: 'Time',
    save: 'Save',
    cancel: 'Cancel',
    sunrise: 'Sunrise',
    duration: 'Brightens over',
    minutes: (n: number) => `${n} min`,
    switchOff: 'Then switch off',
    never: 'Never',
    after: (n: number) => `after ${n} min`,
    startWarmth: 'Starting warmth',
    endWarmth: 'Final warmth',
    curve: 'Brightening',
    curveEven: 'Even',
    curveSlow: 'Dim for longer',
    saveSunrise: 'Save sunrise',
    saved: 'Saved',
    lamp: 'Wake-up lamp',
    noLamp: 'Choose a wake-up lamp',
    tryIt: 'Try it',
    running: 'Sunrise running',
    testRunning: 'Trying the sunrise',
    fullAt: (time: string) => `Full brightness at ${time}`,
    stop: 'Stop',
    lastAlarm: (result: string, time: string) => `Last alarm ${result} at ${time}.`,
    result: { completed: 'finished', cancelled: 'was stopped', failed: 'failed' } as Record<
      string,
      string
    >,
  },
  sensor: {
    occupied: 'Motion',
    empty: 'No motion',
    lux: (lux: number) => `${lux < 10 ? lux.toFixed(1) : Math.round(lux)} lx`,
    battery: (percent: number) => `Battery ${Math.round(percent)} %`,
    settings: (name: string) => `${name}: motion lighting`,
    enabled: 'Motion turns lamps on',
    lamps: 'Lamps it switches on',
    takenBy: (name: string) => `Already controlled by ${name}`,
    darkerThan: 'Only when darker than',
    always: 'Always, even in daylight',
    luxNow: (lux: string) => `Now ${lux}`,
    offAfter: 'Switch off when the room has been empty for',
    minutes: (n: number) => `${n} min`,
    day: 'By day',
    night: 'At night',
    nightHint: (from: string, to: string) => `Night is ${from}-${to}, set in Settings.`,
    brightness: 'Brightness',
    warmth: 'Warmth',
    save: 'Save',
    notConfigured: 'Setting up: move in front of the sensor to wake it.',
  },
  devices: {
    kinds: { light: 'Lamps', motion: 'Motion sensors', remote: 'Remotes', other: 'Other devices' },
    add: 'Add a device',
    addTitle: 'Add a device',
    addWhat: 'What are you adding?',
    addLamp: 'An IKEA lamp',
    addSensor: 'A motion sensor (VALLHORN)',
    startPairing: 'Start pairing',
    close: 'Close',
    sensorHelp:
      'Press the pairing button on the sensor 4 times quickly, within 5 seconds. Its red light flashes, then goes out when it has joined. Keep it near a lamp while pairing.',
    sensorBatteries:
      'Use rechargeable batteries (IKEA LADDA). Ordinary 1.5 V batteries make the sensor see motion that is not there.',
    pairing: (seconds: number) => `Pairing open, ${seconds} s left`,
    stopPairing: 'Stop pairing',
    pairHelp:
      'With the lamp on, switch it off and on 6 times, about a second each time, then leave it on. It flashes when it joins.',
    rename: 'Rename',
    name: 'Name',
    room: 'Room',
    roomHint: 'For example Bedroom',
    remove: 'Remove',
    removeTitle: (name: string) => `Remove ${name}?`,
    removeBody: 'It leaves the Zigbee network. To use it again, pair it again.',
    useForWakeup: 'Use for wake-up',
    seen: (relative: string) => `Seen ${relative}`,
    notSeen: 'Not paired',
    empty: 'No devices yet.',
  },
  settings: {
    language: 'Language',
    panel: 'This screen is a wall panel',
    panelHelp: 'Shows a large clock and the lamps, and darkens at night.',
    night: 'Night',
    nightHelp: 'Motion turns on only a dim night light, and the panel goes dark. Night ends early when a sunrise starts.',
    from: 'From',
    to: 'To',
    saveNight: 'Save night',
    token: 'Access code',
    tokenHelp: 'Only needed if one has been set on the Pi.',
    saveToken: 'Use this code',
    saved: 'Saved',
  },
  panel: {
    menu: 'Menu',
    back: 'Back to the panel',
    alarm: (weekday: string, time: string) => `Alarm ${weekday} ${time}`,
    noAlarm: 'No alarm',
    tapToWake: 'Tap to show the lamps',
  },
  error: {
    lamp: "The lamp didn't respond. Check that its power is on.",
    unreachable: 'No connection to Kotivalo.',
    generic: (message: string) => `That didn't work: ${message}`,
  },
}

export type Messages = typeof en
