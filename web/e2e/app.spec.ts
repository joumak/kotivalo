import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

const LAMP = '00:00:00:00:00:00:00:02'
const SENSOR = '00:00:00:00:00:00:00:f1'
const REMOTE = '00:00:00:00:00:00:00:e1'
const PLUG = '00:00:00:00:00:00:00:c1'
const PLUG_NAME = 'TRETAKT Smart plug 00c1'

async function state(request: APIRequestContext) {
  return (await request.get('/api/state')).json()
}
async function lamp(request: APIRequestContext, ieee = LAMP) {
  return (await state(request)).lights.find((l: { ieee: string }) => l.ieee === ieee)
}
async function reset(request: APIRequestContext) {
  for (const device of (await state(request)).devices) {
    if (device.kind === 'fixture') await request.delete(`/api/devices/${device.ieee}`)
  }
  await request.put(`/api/devices/${LAMP}`, { data: { name: 'Lukuvalo', room: 'Olohuone' } })
  for (const ieee of ['00:00:00:00:00:00:00:01', LAMP, '00:00:00:00:00:00:00:03', PLUG]) {
    await request.post(`/api/lights/${ieee}`, { data: { action: 'off' } })
  }
  await request.put('/api/night', { data: { start: '23:00', end: '07:00' } })
  await request.post('/api/master', { data: { action: 'cancel' } })
  await request.delete(`/api/motion/${SENSOR}`)
  await request.delete(`/api/remotes/${REMOTE}`)
  await request.put('/api/weather', { data: { lat: null, lon: null } })
  await request.put(`/api/devices/${SENSOR}`, { data: { name: 'Eteisen tunnistin', room: 'Eteinen' } })
  const alarms = Array.from({ length: 7 }, () => ({ enabled: false, time: '07:00' }))
  await request.put('/api/wakeup', { data: { alarms } })
}
async function open(page: Page, hash = '', storage: Record<string, string> = {}) {
  await page.addInitScript((items) => {
    localStorage.setItem('kotivalo-lang', 'fi')
    for (const [key, value] of Object.entries(items)) localStorage.setItem(key, value)
  }, storage)
  await page.goto(`/${hash}`)
}

test.beforeEach(async ({ request }) => reset(request))

/** Drags the mouse sideways across a lamp card, from `from` to `to` (0..1 of its width). */
async function dragCard(page: Page, name: string, from: number, to: number) {
  const box = (await page.getByRole('button', { name, exact: true }).boundingBox())!
  const y = box.y + box.height / 2
  await page.mouse.move(box.x + box.width * from, y)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * to, y, { steps: 12 })
  await page.mouse.up()
}

/** Swipes a finger over a lamp card, `from` and `to` as fractions of its size: real touch input
 * (Chromium's DevTools protocol), so touch-action and the browser's own capture apply. */
async function swipeCard(page: Page, name: string, from: [number, number], to: [number, number]) {
  const box = (await page.getByRole('button', { name, exact: true }).boundingBox())!
  const cdp = await page.context().newCDPSession(page)
  const at = (fx: number, fy: number) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [at(...from)] })
  for (let i = 1; i <= 12; i++) {
    const point = at(from[0] + ((to[0] - from[0]) * i) / 12, from[1] + ((to[1] - from[1]) * i) / 12)
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point] })
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
}

test('a tap on a lamp card switches it, and the card follows', async ({ page, request }) => {
  await open(page, '#/lights')
  const card = page.getByRole('button', { name: 'Lukuvalo', exact: true })
  await expect(card).toHaveAttribute('aria-pressed', 'false')
  await card.click()
  await expect(card).toHaveAttribute('aria-pressed', 'true')
  expect((await lamp(request)).state.on).toBe(true)
})

test('dragging a card sideways sets the brightness without switching', async ({ page, request }) => {
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'level', value: 64 } })
  await open(page, '#/lights')
  await dragCard(page, 'Lukuvalo', 0.05, 0.98)
  await expect.poll(async () => (await lamp(request)).state.level).toBeGreaterThan(200)
  expect((await lamp(request)).state.on).toBe(true)
})

test('a finger dragged sideways sets the brightness, one moved up or down does not', async ({ page, request, browserName }) => {
  test.skip(browserName !== 'chromium', 'touch input through Chromium')
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'level', value: 64 } })
  await open(page, '#/lights')
  await swipeCard(page, 'Lukuvalo', [0.5, 0.15], [0.55, 0.95]) // the page's gesture, not the lamp's
  await page.waitForTimeout(500)
  expect((await lamp(request)).state).toMatchObject({ on: true, level: 64 })
  await swipeCard(page, 'Lukuvalo', [0.05, 0.5], [0.98, 0.55])
  await expect.poll(async () => (await lamp(request)).state.level).toBeGreaterThan(200)
  expect((await lamp(request)).state.on).toBe(true)
})

test('dragging an off lamp right switches it on, left keeps it off', async ({ page, request }) => {
  await open(page, '#/lights')
  await dragCard(page, 'Lukuvalo', 0.95, 0.05)
  await page.waitForTimeout(500)
  expect((await lamp(request)).state.on).toBe(false)
  await dragCard(page, 'Lukuvalo', 0.05, 0.6)
  await expect.poll(async () => (await lamp(request)).state.on).toBe(true)
})

test('a smart plug only switches: a tap, but no brightness drag or slider', async ({ page, request }) => {
  await open(page, '#/lights')
  await page.getByRole('button', { name: PLUG_NAME, exact: true }).click()
  await expect.poll(async () => (await lamp(request, PLUG)).state.on).toBe(true)
  await dragCard(page, PLUG_NAME, 0.9, 0.1) // nothing to set, and not a tap either
  await page.waitForTimeout(400)
  expect((await lamp(request, PLUG)).state.on).toBe(true)
  await page.getByRole('button', { name: `${PLUG_NAME}: säädöt` }).click()
  await expect(page.getByRole('switch', { name: `Sammuta ${PLUG_NAME}` })).toBeVisible()
  await expect(page.getByRole('slider', { name: 'Kirkkaus' })).toHaveCount(0)
})

test('changes brightness while the slider moves', async ({ page, request }) => {
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'level', value: 127 } })
  await open(page, '#/lights')
  await page.getByRole('button', { name: 'Lukuvalo: säädöt' }).click()
  const slider = page.getByRole('slider', { name: 'Kirkkaus' })
  await slider.focus()
  for (let i = 0; i < 10; i++) await page.keyboard.press('ArrowRight')
  await expect.poll(async () => (await lamp(request)).state.level).toBeGreaterThan(140)
})

test('sets an alarm for Monday', async ({ page, request }) => {
  await open(page, '#/wakeup')
  await page.getByRole('button', { name: /^maanantai/ }).click()
  await page.getByRole('switch', { name: 'Herätys tänä päivänä' }).click()
  await page.getByLabel('Kellonaika').fill('06:45')
  await page.getByRole('button', { name: 'Tallenna' }).first().click()
  await expect(page.getByRole('button', { name: 'maanantai: 6.45' })).toBeVisible()
  expect((await state(request)).wakeup.alarms[0]).toEqual({ enabled: true, time: '06:45' })
})

test('switches the language to English', async ({ page }) => {
  await open(page, '#/settings')
  await page.getByRole('radio', { name: 'English' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Lights' })).toBeVisible()
})

test('wall panel at night: the first touch only wakes the screen', async ({ page, request }) => {
  const hhmm = (d: Date) => d.toTimeString().slice(0, 5)
  const now = Date.now()
  await request.put('/api/night', {
    data: { start: hhmm(new Date(now - 3600e3)), end: hhmm(new Date(now + 3600e3)) },
  })
  await request.put('/api/weather', { data: { name: 'Helsinki', lat: 60.17, lon: 24.94 } })
  await open(page, '', { 'kotivalo-panel': '1' })
  const wake = page.getByRole('button', { name: 'Näytä valot napauttamalla' })
  await expect(wake).toBeVisible()
  await expect(wake.getByText(/^Sää nyt: /)).toBeAttached() // the weather, dimmed, at night too
  await wake.click()
  await expect(page.getByRole('button', { name: 'Lukuvalo', exact: true })).toBeVisible()
  for (const l of (await state(request)).lights) expect(l.state.on).toBe(false) // nothing switched
})

test('the wall panel opens a lamp\'s controls from its card', async ({ page, request }) => {
  const hhmm = (d: Date) => d.toTimeString().slice(0, 5)
  const now = Date.now()
  await request.put('/api/night', {
    data: { start: hhmm(new Date(now + 2 * 3600e3)), end: hhmm(new Date(now + 3 * 3600e3)) },
  }) // daytime on the panel, whenever the test runs
  await open(page, '', { 'kotivalo-panel': '1' })
  await page.getByRole('button', { name: 'Lukuvalo: säädöt' }).click()
  await expect(page.getByRole('slider', { name: 'Kirkkaus' })).toBeVisible()
  await expect(page.getByRole('switch', { name: 'Sytytä Lukuvalo' })).toBeVisible()
  for (const l of (await state(request)).lights) expect(l.state.on).toBe(false) // nothing switched
})

test('sets up motion lighting for a lamp', async ({ page, request }) => {
  await open(page, '#/devices')
  await page.getByRole('button', { name: 'Eteisen tunnistin: liikevalot' }).first().click()
  await page.getByRole('switch', { name: /^Lukuvalo/ }).click()
  await page.getByRole('button', { name: 'Tallenna' }).click()
  await expect.poll(async () => (await state(request)).sensors[0].rule?.lights).toEqual([LAMP])
  await expect(page.getByRole('dialog')).toBeHidden()
})

test('gives a lamp switched on by hand back to its motion sensor', async ({ page, request }) => {
  await request.put(`/api/motion/${SENSOR}`, { data: { lights: [LAMP] } })
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'on' } })
  await open(page, '#/lights')
  await page.getByRole('button', { name: 'Lukuvalo: säädöt' }).click()
  await expect(page.getByText('Sytytetty käsin, liiketunnistin ei ohjaa')).toBeVisible()
  await page.getByRole('button', { name: 'Palauta liikeohjaus' }).click()
  await expect(page.getByText('Liiketunnistin ohjaa tätä valoa')).toBeVisible()
  expect((await lamp(request)).owner).toBe('motion')
})

test('a remote switches the lamps chosen for it', async ({ page, request }) => {
  await open(page, '#/devices')
  await page.getByRole('button', { name: /^STYRBAR 00e1: valot$/ }).click()
  await page.getByRole('switch', { name: 'Lukuvalo' }).click()
  await page.getByRole('button', { name: 'Tallenna' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await request.post('/api/fake/event', { data: { type: 'button', ieee: REMOTE, value: 'on' } })
  await expect.poll(async () => (await lamp(request)).state.on).toBe(true)
  await expect(page.getByText(/Painettu juuri nyt: Päälle/)).toBeVisible()
})

test('shows the weather once a place is set', async ({ page, request }) => {
  await open(page, '#/settings')
  await page.getByLabel('Paikkakunta tai 60.17, 24.94').fill('60.17, 24.94')
  await page.getByRole('button', { name: 'Hae' }).click()
  await page.getByRole('button', { name: '60.17, 24.94' }).click()
  await expect.poll(async () => (await state(request)).weather.location?.lat).toBe(60.17)
  await page.evaluate(() => (window.location.hash = '#/lights'))
  await expect(page.getByText(/^Sää nyt: /)).toBeAttached()
  await expect(page.getByText(/^-?\d+°$/).first()).toBeVisible()
})

test('the master switch turns everything off and brings it back', async ({ page, request }) => {
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'level', value: 150 } })
  await open(page, '#/lights')
  await page.getByRole('button', { name: 'Kaikki pois' }).click()
  await expect.poll(async () => (await lamp(request)).state.on).toBe(false)
  await page.getByRole('button', { name: 'Palauta valot' }).click()
  await expect.poll(async () => (await lamp(request)).state.level).toBe(150)
  await expect(page.getByRole('button', { name: 'Kaikki pois' })).toBeVisible()
})

test('the master switch can wait a few minutes before switching off', async ({ page, request }) => {
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'level', value: 150 } })
  await open(page, '#/lights')
  await page.getByRole('button', { name: 'Sammuta myöhemmin' }).click()
  await page.getByRole('menuitem', { name: '5 min päästä' }).click()
  await expect(page.getByText('Pois 5 min päästä')).toBeVisible()
  expect((await state(request)).master.off_at).not.toBeNull()
  expect((await lamp(request)).state.on).toBe(true) // not yet
  await page.getByRole('button', { name: 'Peru' }).click()
  await expect(page.getByRole('button', { name: 'Kaikki pois' })).toBeVisible()
  expect((await state(request)).master.off_at).toBeNull()
})

test('hand only keeps motion away from a lamp until released', async ({ page, request }) => {
  await request.put(`/api/motion/${SENSOR}`, { data: { lights: [LAMP], dark_lux: null } })
  await request.post('/api/fake/event', { data: { type: 'motion', ieee: SENSOR, value: false } })
  await open(page, '#/lights')
  await page.getByRole('button', { name: 'Lukuvalo: säädöt' }).click()
  await page.getByRole('switch', { name: 'Vain käsin' }).click()
  await expect.poll(async () => (await lamp(request)).hand_only).toBe(true)
  await expect(page.getByText('Vain käsin, pois').first()).toBeVisible()
  await request.post('/api/fake/event', { data: { type: 'motion', ieee: SENSOR, value: true } })
  expect((await lamp(request)).state.on).not.toBe(true)
  await page.getByRole('switch', { name: 'Vain käsin' }).click()
  await expect.poll(async () => (await lamp(request)).state.on).toBe(true) // back to motion
  await request.post('/api/fake/event', { data: { type: 'motion', ieee: SENSOR, value: false } })
})

test('bulbs grouped into a fixture act as one lamp', async ({ page, request }) => {
  await open(page, '#/devices')
  await page.getByRole('button', { name: 'Yhdistä valaisimeksi' }).click()
  await page.getByLabel('Nimi').fill('Lattiavalo')
  await page.getByRole('switch', { name: 'Lukuvalo' }).click()
  await page.getByRole('switch', { name: /^Fake panel 0003/ }).click()
  await page.getByRole('button', { name: 'Tallenna' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(page.getByText('Osa valaisinta Lattiavalo').first()).toBeVisible()

  await page.evaluate(() => (window.location.hash = '#/lights'))
  await expect(page.getByRole('button', { name: 'Lattiavalo', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Lukuvalo', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Lattiavalo', exact: true }).click()
  const fixture = async () =>
    (await state(request)).lights.find((l: { name: string }) => l.name === 'Lattiavalo')
  await expect.poll(async () => (await fixture()).state.on).toBe(true)
  expect((await fixture()).members).toHaveLength(2)
})

test('each channel of a two-gang dimmer is a lamp of its own', async ({ page, request }) => {
  const dimmer = '00:00:00:00:00:00:00:d1'
  await request.post(`/api/lights/${dimmer}`, { data: { action: 'off' } })
  await request.post(`/api/lights/${dimmer}-2`, { data: { action: 'off' } })
  await open(page, '#/devices')
  await expect(page.getByText('Kanava 2').first()).toBeVisible()
  await page.evaluate(() => (window.location.hash = '#/lights'))
  await page.getByRole('button', { name: 'Fake dimmer 00d1 (2)', exact: true }).click()
  await expect.poll(async () => (await lamp(request, `${dimmer}-2`)).state.on).toBe(true)
  expect((await lamp(request, dimmer)).state.on).not.toBe(true) // channel 1 untouched
  await request.post(`/api/lights/${dimmer}-2`, { data: { action: 'off' } })
})
