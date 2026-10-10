// Screenshots of every page at the four layouts, plus the wall panel by day and night.
//   1. kotivalo --state-dir <tmp> serve --fake --fake-lamps 6 --fake-sensors 1 --host 127.0.0.1 --port 8099
//   2. node scripts/screenshots.mjs [out-dir] [base-url]
import { chromium } from '@playwright/test'

const out = process.argv[2] ?? 'screenshots'
const base = process.argv[3] ?? 'http://127.0.0.1:8099'
const LAMP_2 = '00:00:00:00:00:00:00:02'
const SENSOR = '00:00:00:00:00:00:00:f1'

const VIEWPORTS = {
  'phone-portrait': { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  'phone-landscape': { viewport: { width: 844, height: 390 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  'tablet-portrait': { viewport: { width: 820, height: 1180 }, hasTouch: true },
  'tablet-landscape': { viewport: { width: 1180, height: 820 }, hasTouch: true },
}

async function call(method, path, body) {
  const response = await fetch(base + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body && JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`)
  return response.json()
}

const hhmm = (date) => date.toTimeString().slice(0, 5)

const LAMPS = [
  // ieee suffix, name, room, [level, kelvin] when lit
  ['01', 'Lattiavalo', 'Olohuone', [170, 2700]],
  ['02', 'Makuuhuoneen paneeli', 'Makuuhuone', null],
  ['03', 'Kattospotit', 'Olohuone', [80, 2200]],
  ['04', 'Lukuvalo', 'Olohuone', null],
  ['05', 'Keittiön paneeli', 'Keittiö', [254, 4000]],
  ['06', 'Eteinen', 'Eteinen', null],
]

async function seed({ nightNow }) {
  for (const [suffix, name, room, lit] of LAMPS) {
    const ieee = `00:00:00:00:00:00:00:${suffix}`
    await call('PUT', `/api/devices/${ieee}`, { name, room })
    if (lit) {
      await call('POST', `/api/lights/${ieee}`, { action: 'level', value: lit[0] })
      await call('POST', `/api/lights/${ieee}`, { action: 'kelvin', value: lit[1] })
    } else {
      await call('POST', `/api/lights/${ieee}`, { action: 'off' })
    }
  }
  await call('PUT', '/api/wakeup', {
    light: LAMP_2,
    alarms: [0, 1, 2, 3, 4, 5, 6].map((d) => ({ enabled: d < 5, time: d < 5 ? '06:30' : '08:00' })),
  })
  // A motion sensor in the bedroom switches the wake-up panel.
  await call('PUT', `/api/devices/${SENSOR}`, { name: 'Makuuhuoneen tunnistin', room: 'Makuuhuone' })
  await call('PUT', `/api/motion/${SENSOR}`, { lights: [LAMP_2], dark_lux: 30, off_after_min: 5 })
  for (const [type, value] of [['lux', 8], ['battery', 82], ['motion', true], ['motion', false]]) {
    await call('POST', '/api/fake/event', { type, ieee: SENSOR, value })
  }
  const now = new Date()
  const night = nightNow
    ? { start: hhmm(new Date(now - 3600e3)), end: hhmm(new Date(+now + 3600e3)) }
    : { start: '23:00', end: '07:00' }
  await call('PUT', '/api/night', night)
  await call('PUT', '/api/weather', { name: 'Helsinki', lat: 60.17, lon: 24.94 }) // a canned forecast
}

const browser = await chromium.launch()
async function shoot(name, viewport, { hash = '', panel = false, lang = 'fi', before } = {}) {
  const context = await browser.newContext({ ...viewport, locale: lang === 'fi' ? 'fi-FI' : 'en-GB', colorScheme: 'dark' })
  await context.addInitScript(
    ([panelMode, language]) => {
      localStorage.setItem('kotivalo-lang', language)
      if (panelMode) localStorage.setItem('kotivalo-panel', '1')
    },
    [panel, lang],
  )
  const page = await context.newPage()
  await page.goto(`${base}/${hash}`)
  await page.waitForTimeout(800)
  if (before) await before(page)
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: !panel })
  await context.close()
}

await seed({ nightNow: false })
for (const [layout, viewport] of Object.entries(VIEWPORTS)) {
  for (const tab of ['lights', 'wakeup', 'devices', 'settings']) {
    await shoot(`${layout}-${tab}`, viewport, { hash: `#/${tab}` })
  }
}
await shoot('phone-portrait-lamp-drawer', VIEWPORTS['phone-portrait'], {
  hash: '#/lights',
  before: (page) => page.getByRole('button', { name: 'Lattiavalo' }).first().click().then(() => page.waitForTimeout(600)),
})
await shoot('phone-portrait-motion-dialog', VIEWPORTS['phone-portrait'], {
  hash: '#/devices',
  before: (page) =>
    page.getByRole('button', { name: 'Makuuhuoneen tunnistin: liikevalot' }).first().click().then(() => page.waitForTimeout(600)),
})
await shoot('phone-portrait-add-device', VIEWPORTS['phone-portrait'], {
  hash: '#/devices',
  before: (page) => page.getByRole('button', { name: 'Lisää laite' }).first().click().then(() => page.waitForTimeout(500)),
})
await shoot('phone-portrait-wakeup-en', VIEWPORTS['phone-portrait'], { hash: '#/wakeup', lang: 'en' })
await shoot('panel-day-landscape', VIEWPORTS['tablet-landscape'], { panel: true })
await shoot('panel-day-portrait', VIEWPORTS['tablet-portrait'], { panel: true })
await seed({ nightNow: true })
await shoot('panel-night', VIEWPORTS['tablet-landscape'], { panel: true })
await browser.close()
console.log(`screenshots in ${out}`)
