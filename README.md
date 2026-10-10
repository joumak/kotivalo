# kotivalo

Home lighting control for IKEA Zigbee lights, running on a Raspberry Pi. The name is
Finnish: *koti* (home) + *valo* (light).

- **Lamps:** switch, dim and set the warmth of every lamp from a phone or a wall panel. Sliders take effect while you drag.
- **Wake-up light:** before each alarm the wake-up lamp fades in from a dim warm glow to full, cooler white.
- **Motion lighting:** an IKEA VALLHORN sensor switches lamps on when it's dark, with a dim night light at night, and off when the room has been empty for a while.
- **Remotes:** IKEA remotes control the lamps you choose, through the Pi.
- **Languages:** the UI is in Finnish and English, switchable per screen.

Web UI: `http://kotivalo.local:8080`, or by IP (currently `http://192.168.1.174:8080`) on phones that do not resolve `.local` names.

Planned work and known issues: [docs/ROADMAP.md](docs/ROADMAP.md). Notes for working on the code: [CLAUDE.md](CLAUDE.md).

## Hardware

- Raspberry Pi 3B+ running Raspberry Pi OS Lite
- Digi XStick2 ZB: an XBee Series 2 with Coordinator API firmware
- **Lamps:** IKEA FLOALT panels (white spectrum). Other IKEA lamps with on/off and dimming work too.
- **Motion sensor:** IKEA VALLHORN (E2134)
- **Remotes:**
  - STYRBAR (E2001/E2002) and RODRET (E2201)
  - the older TRÅDFRI on/off switch (E1743), 5-button remote (E1810) and shortcut button (E1812)

**Software:** [zigpy](https://github.com/zigpy/zigpy) and [zigpy-xbee](https://github.com/zigpy/zigpy-xbee), the radio stack of Home Assistant's ZHA (zigbee2mqtt does not support XBee radios). aiohttp serves a React UI.

## Who controls a lamp

Every lamp has one owner at a time. The lamp's status line in the UI says which:

| Status | Owner | Ends when |
|---|---|---|
| Off | nobody | |
| On by hand ("Käsin päällä") | you: the UI, a remote or the wall switch | you switch it off. **Motion never switches off a lamp you switched on.** |
| On by motion, off at … ("Liikkeestä päällä") | the motion sensor | the room has been empty for the set time |
| Night light ("Yövalo") | the motion sensor, at night | as above |
| Sunrise, full at … ("Auringonnousu") | the wake-up alarm | the hold time after the alarm ends, or you touch the lamp |

**Switching a lamp off by hand pauses motion** ("Pois, liike tauolla") until the room has been empty for the set time. You can switch the light off and walk out without it coming back on.

**To hand a lamp back to its motion sensor,** open the lamp and tap **Palauta liikeohjaus** ("Let motion control it"):
- a lit lamp then switches off when the room has been empty for the set time
- an off lamp comes on straight away if you're in the room and it's dark

**"On" restores the last brightness and warmth set by hand,** from the UI or a remote.

## Motion lighting

Set up per sensor under **Laitteet → (sensor) → settings**:
- **the lamps it switches.** A lamp can have only one sensor.
- **"only when darker than"**, with the live lux reading. The lux value counts only when the sensor's lamps have been off for a minute, so the lamp's own light doesn't count.
- **the off time:** switch off once the room has been empty this long.
- **day and night brightness and warmth.** The default night light is 5 %, 2200 K.

**Night** is a global setting (Asetukset, default 23–07). It ends early when that morning's sunrise starts.

**A sensor that stays silent for 10 minutes** counts as an empty room, for example when its battery runs out. Use rechargeable batteries (IKEA LADDA): ordinary 1.5 V batteries make the VALLHORN see motion that isn't there.

## Remotes

Choose the lamps a remote controls under **Laitteet → (remote) → settings**. The row shows the last button pressed and the battery level.

| Button | What it does |
|---|---|
| On / Off (STYRBAR, RODRET, E1743) | switches the lamps on (last setting by hand) or off |
| Centre (5-button) | on/off: off if any of its lamps is on |
| Hold up / down | dims smoothly until released |
| Tap up / down (5-button) | ±20 % |
| Left / right arrows (STYRBAR, 5-button) | warmer / cooler; repeats while held |

**During a sunrise:** any remote or UI action on the wake-up lamp ends the sunrise and skips that alarm. "On" then means full brightness ("I'm up").

**Old firmware:** a 5-button remote or on/off switch on firmware older than 2.3.075 sends its presses only to a Zigbee group, which the XStick cannot hear. Its row then shows no presses. Use **Päivitä laiteohjelmisto** in the remote's settings to update it from IKEA's server:
- it takes 30–90 minutes
- press a button every few seconds until the update starts, then keep the remote near a lamp
- a failed update leaves the old firmware in place

## The wake-up light

Choose the wake-up lamp under Laitteet (the sunrise icon), and the alarm days and times under Herätys.

- **Brightness:** `level = 2 + 252 · p^2.5`, so it rises slowly at first. The minimum is level 2, because level 1 switches a FLOALT off.
- **Colour temperature:** moves linearly from 2200 K to 4000 K.
- **Timing:** about 60 steps per ramp, at most one every 30 s.
- **Each step:**
  1. Set the colour temperature with no transition.
  2. Wait 0.3 s.
  3. Start a brightness transition that ends 2 s before the next step.

  IKEA lamps run one transition at a time and freeze on colour-temperature transitions, so the two never overlap.
- **At the alarm time:** full brightness and coolest white are sent again, in case a command was lost.
- **After the hold:** the lamp switches off. If there has been motion in the room, the motion sensor takes over instead and the lamp stays on. If you switched it on by hand before the alarm, it stays on.
- **Times:** alarms are local wall-clock times (Europe/Helsinki). Ramp windows are computed in UTC, so a fade across a DST change still lasts its full length.

**No flash at the next start:**
- Before switching the wake-up lamp off, the Pi sets it to warm and minimum brightness, so a sunrise or night light never starts with a flash of its old setting. Other lamps get only their warmth reset.
- After a power cut the wake-up lamp returns to its previous state, so a power cut at night doesn't wake you. Other lamps come on, so their wall switches work.

**Reliability:**
- **The ramp never dims a lamp that is already brighter.**
- **Restarts resume.** A restart or reboot mid-sunrise resumes at the right point, from the wall clock.
- **Failures restart the service.**
  - If the radio stops answering, the service exits and systemd restarts it.
  - A failed startup always exits, and systemd retries every 10 s.
  - A 60 s watchdog restarts even a hung process.
- **Unpowered lamps don't block startup.** Lamps switched off at the wall are controllable again once they have power.
- **The Wake-up page shows how the last alarm went.**

## Wall panel

On a tablet mounted on a wall or by the bed, open the UI and switch on **Asetukset → Tämä näyttö on seinäpaneeli** ("This screen is a wall panel"). The setting applies to that screen only.

- The panel shows a large clock, the next alarm (with skip) and the lamps.
- **Tap** a lamp tile to switch it. **Press and drag** up or down to set its brightness.
- **At night** the screen is almost black with a dim amber clock, which drifts a little to prevent burn-in. The first touch only wakes the screen, so it never switches a lamp by accident.
- The menu button opens the full app. After 3 minutes untouched, the panel returns to its dashboard.

**Keeping the screen on:** browsers allow the Wake Lock API only over HTTPS, so use the tablet's own settings:
- **Android:** [Fully Kiosk Browser](https://www.fully-kiosk.com/) with the UI as its start URL, "Keep Screen On" and "Start on Boot". Its kiosk mode (a paid PLUS feature) locks the tablet to the page.
- **iPad:**
  1. Set Settings → Display & Brightness → Auto-Lock → **Never**.
  2. Turn on Settings → Accessibility → **Guided Access**.
  3. Open the UI in Safari (or add it to the Home Screen) and triple-click the side button to lock the tablet to it.

A web page can't change the screen brightness, so the night mode darkens the content instead.

## Adding devices

Open **Laitteet → Lisää laite**, choose the kind, and follow the steps on screen. Pairing stays open for 254 s.

- **IKEA lamp:** with the lamp on, switch it off and on 6 times (about 1 s each) and leave it on. It flashes when it joins.
- **VALLHORN:** press its pairing button 4 times within 5 seconds, near a lamp. This also removes any direct link it had to a lamp.
- **Remote:** hold it next to a lamp and press its pairing button 4 times within 5 seconds. On most remotes the button is on the back, under the cover. Then press any button every few seconds until it appears, so it stays awake while the Pi sets it up.

Battery devices are set up while they're awake: right after joining, or after a button press or motion. A device whose setup didn't finish says so on its row; the Pi tries again at most every 5 minutes.

## Code layout

| Path | What |
|---|---|
| `src/kotivalo/ramp.py`, `schedule.py` | pure maths: curve, tick plan, alarm occurrences |
| `src/kotivalo/behaviour.py` | pure owner model: motion, manual, sunrise, timers |
| `src/kotivalo/remotes.py` | pure decoder: remote frames to button actions |
| `src/kotivalo/sunrise.py`, `scheduler.py` | runs one sunrise; starts and resumes alarms |
| `src/kotivalo/light.py` | `Light` protocol, `FakeLight`, `LightController`, `LatestWins` |
| `src/kotivalo/registry.py`, `settings.py` | devices and lamps; versioned `settings.json` |
| `src/kotivalo/zigbee.py`, `events.py` | zigpy: startup, binding, reports and presses as events, firmware updates |
| `src/kotivalo/xbee_config.py` | raw XBee AT frames (one-time setup, `radio-info`) |
| `src/kotivalo/app.py`, `web.py` | the service, JSON API and live-update stream |
| `web/` | the React UI (built into `src/kotivalo/static/`) |
| `deploy/` | `pi-setup.sh`, `deploy.sh`, systemd unit |

State lives in `/var/lib/kotivalo` on the Pi:
- `settings.json`: devices, lamps, wake-up, night, motion rules, remotes, radio
- `state.json`: skipped alarms, last run, lamp owners and timers
- `zigbee.db`: zigpy's device database, including the network key

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'     # the Pi runs Python 3.13
.venv/bin/pytest -q && .venv/bin/ruff check .
.venv/bin/kotivalo --state-dir var serve --fake --fake-lamps 6 --port 8080   # in-memory devices
cd web && npm ci && npm run dev    # UI with hot reload, /api proxied to :8080
cd web && npm run lint && npm test && npm run e2e
```

`serve --fake` has fake lamps, motion sensors (`--fake-sensors`) and remotes (`--fake-remotes`). `POST /api/fake/event` with `{"type": "motion" | "lux" | "battery" | "button", "ieee": ..., "value": ...}` plays a device event.

## Deploy

```sh
deploy/deploy.sh               # all checks, UI build, rsync, install on the Pi, restart the service
deploy/deploy.sh --no-service  # code only (for CLI work with the service stopped)
```

Logs: `ssh pi@kotivalo.local journalctl -fu kotivalo`. The journal is kept in RAM, so logs don't survive a reboot.

## Setting up a Pi from scratch

1. Flash Raspberry Pi OS Lite (64-bit) and set up the user `pi` with SSH key login. Enable passwordless sudo for pi.
2. Run the one-time system setup. It ends with a reboot.

   ```sh
   ssh pi@raspberrypi.local 'sudo bash -s' < deploy/pi-setup.sh
   ```

   It does the following:
   - renames the Pi to `kotivalo` (or `NEW_HOSTNAME`), so it becomes `kotivalo.local`, and stops cloud-init from resetting the name
   - apt full-upgrade
   - turns Wi-Fi power saving off
   - keeps the journal in RAM
   - makes boot wait up to 3 min for NTP
   - disables ModemManager and brltty
   - creates the state directory
3. Install the code only: `deploy/deploy.sh --no-service`.
4. Prepare the radio. These commands are on the Pi, in `~/kotivalo`, using `.venv/bin/kotivalo`.

   ```sh
   kotivalo radio-info              # read-only: firmware, AP, baud, network
   kotivalo xbee-config             # one-time: AP=2 + 57600 baud, verified before saving
   kotivalo form-network --channel 25
   ```

   **Choosing a channel:**
   - Pick a Zigbee channel away from your Wi-Fi. Wi-Fi channel 1 → Zigbee 20 or 25; channel 6 → 25; channel 11 → 15. Check with `nmcli -f CHAN,SSID dev wifi`.
   - Forming a new network means every device must be paired again.
   - Don't re-form unnecessarily: the XBee's flash wears with each write.
5. Start the service with `deploy/deploy.sh`, then pair devices from the UI (Laitteet → Lisää laite).

   The CLI can pair and control lamps too (`kotivalo pair`, `devices`, `light level 128`), but radio commands need the service stopped first: `sudo systemctl stop kotivalo`.

## Troubleshooting

- **"The radio is in use":** the service holds the XStick. Stop it before using CLI radio commands.
- **"The radio has no Zigbee network yet":** run `form-network`. The service exits with code 78 and systemd does not retry.
- **A lamp stops responding:**
  - Check that the wall switch is on.
  - Look at its row under Laitteet ("seen …").
  - Re-pair if needed: 6 off/on cycles while pairing is open.
- **Motion doesn't switch a lamp on:** read the lamp's status line.
  - "Käsin päällä" means you switched it on by hand, and motion leaves it alone.
  - "Pois, liike tauolla" means you switched it off by hand, and motion is paused.
  - "Palauta liikeohjaus" hands the lamp back to the sensor. Otherwise the room may be bright: check the lux value in the sensor's settings.
- **A remote's presses don't show on its row:**
  - It may still be setting up: press its pairing button 4 times near a lamp.
  - On old firmware, update it (see Remotes).
  - Check the battery: a weak one makes the remote drop off the network mid-setup.
- **If the XStick ever won't keep devices joined, swap the radio.** A Sonoff ZBDongle-E or ZBDongle-P works with the same code:
  1. `pip install -e '.[ezsp]'` or `'.[znp]'`.
  2. Set `radio` in `settings.json` to `{"type": "ezsp" or "znp", "path": "/dev/serial/by-id/...", "baudrate": 115200}`.
  3. Pair again. Those radios form their network automatically on first start.
