import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

const LAMP = '00:00:00:00:00:00:00:02'
const SENSOR = '00:00:00:00:00:00:00:f1'
const REMOTE = '00:00:00:00:00:00:00:e1'

async function state(request: APIRequestContext) {
  return (await request.get('/api/state')).json()
}
async function lamp(request: APIRequestContext, ieee = LAMP) {
  return (await state(request)).lights.find((l: { ieee: string }) => l.ieee === ieee)
}
async function reset(request: APIRequestContext) {
  await request.put(`/api/devices/${LAMP}`, { data: { name: 'Lukuvalo', room: 'Olohuone' } })
  for (const ieee of ['00:00:00:00:00:00:00:01', LAMP, '00:00:00:00:00:00:00:03']) {
    await request.post(`/api/lights/${ieee}`, { data: { action: 'off' } })
  }
  await request.put('/api/night', { data: { start: '23:00', end: '07:00' } })
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

test('switches a lamp on from its tile, and the tile follows', async ({ page, request }) => {
  await open(page, '#/lights')
  const power = page.getByRole('button', { name: 'Sytytä Lukuvalo' })
  await power.click()
  await expect(page.getByRole('button', { name: 'Sammuta Lukuvalo' })).toHaveAttribute('aria-pressed', 'true')
  expect((await lamp(request)).state.on).toBe(true)
})

test('changes brightness while the slider moves', async ({ page, request }) => {
  await request.post(`/api/lights/${LAMP}`, { data: { action: 'level', value: 127 } })
  await open(page, '#/lights')
  await page.getByRole('button', { name: 'Lukuvalo', exact: true }).click()
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
  await open(page, '', { 'kotivalo-panel': '1' })
  const wake = page.getByRole('button', { name: 'Näytä valot napauttamalla' })
  await expect(wake).toBeVisible()
  await wake.click()
  await expect(page.getByRole('button', { name: /^Lukuvalo/ })).toBeVisible()
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
  await page.getByRole('button', { name: 'Lukuvalo', exact: true }).click()
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
