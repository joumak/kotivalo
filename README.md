# kotivalo

Home lighting control for IKEA Zigbee lights, running on a Raspberry Pi. The name is
Finnish: *koti* (home) + *valo* (light).

- **Lamps:** switch, dim and set the warmth of every lamp from a phone or a wall panel. Each lamp is a card that works the same everywhere: **tap** it to switch, **drag sideways** to set the brightness, and **⚙** opens its warmth, "Vain käsin" and motion settings. Changes take effect while you drag.
- **Wake-up light:** before each alarm the wake-up lamp fades in from a dim warm glow to full, cooler white.
- **Motion lighting:** an IKEA VALLHORN sensor switches lamps on when it's dark, with a dim night light at night, and off when the room has been empty for a while.
- **Remotes:** IKEA remotes control the lamps you choose, through the Pi.
- **Weather:** the current weather and the next few hours, on the Lights page and the wall panel.
- **Languages:** the UI is in Finnish and English, switchable per screen.

Web UI: `http://kotivalo.local:8080`, or by IP (currently `http://192.168.1.174:8080`) on phones that do not resolve `.local` names.

Planned work and known issues: [docs/ROADMAP.md](docs/ROADMAP.md). Notes for working on the code: [CLAUDE.md](CLAUDE.md).

## Hardware

- Raspberry Pi 3B+ running Raspberry Pi OS Lite
- **SONOFF Dongle Plus MG24** (EmberZNet, EZSP), since 2026-10-21. Before it, a Digi XStick2 ZB (XBee Series 2 with Coordinator API firmware), which the code still supports: see [Changing the radio](#changing-the-radio).
- **Lamps:** IKEA FLOALT panels (white spectrum). Other IKEA lamps with on/off and dimming work too.
- **Motion sensor:** IKEA VALLHORN (E2134)
- **Remotes:**
  - STYRBAR (E2001/E2002) and RODRET (E2201)
  - the older TRÅDFRI on/off switch (E1743), 5-button remote (E1810) and shortcut button (E1812)

**Software:** [zigpy](https://github.com/zigpy/zigpy) with [bellows](https://github.com/zigpy/bellows) (and [zigpy-xbee](https://github.com/zigpy/zigpy-xbee) for the old XStick), the radio stack of Home Assistant's ZHA. aiohttp serves a React UI.

## Who controls a lamp

Every lamp has one owner at a time. The lamp's status line in the UI says which:

| Status | Owner | Ends when |
|---|---|---|
| Off | nobody | |
| On by hand ("Käsin päällä") | you: the UI, a remote or the wall switch | you switch it off. **Motion never switches off a lamp you switched on.** |
| On by motion, off at … ("Liikkeestä päällä") | the motion sensor | the room has been empty for the set time |
| Night light ("Yövalo") | the motion sensor, at night | as above |
| Sunrise, full at … ("Auringonnousu") | the wake-up alarm | the hold time after the alarm ends, or you touch the lamp |

**"Vain käsin" ("Hand only")**, a switch in the lamp's controls, makes a lamp yours until you switch it off:
- Motion and its timers leave it alone, both on and off, however long the room has been empty or still.
- A hand icon on its card and "Vain käsin" in its status line show it's on.
- Switching it off, or "Palauta liikeohjaus", hands the lamp back to its sensor.
- An alarm still lights the wake-up lamp, and that ends "Hand only".
- The master switch still includes it.

**Switching a lamp off by hand pauses motion** ("Pois, liike tauolla") until the room has been empty for the set time. You can switch the light off and walk out without it coming back on.

**To hand a lamp back to its motion sensor,** tap ⚙ on its card, then **Palauta liikeohjaus** ("Let motion control it"):
- a lit lamp then switches off when the room has been empty for the set time
- an off lamp comes on straight away if you're in the room and it's dark

**"On" restores the last brightness and warmth set by hand,** from the UI or a remote.

## Fixtures: several bulbs as one lamp

A lamp with several smart bulbs, like a fitting with GU10 spots, works best as a **fixture** (*valaisin*). Its bulbs then act as one lamp: one card and one set of sliders. Motion rules, remotes, the wake-up lamp, "Hand only" and the master switch all treat it like any other lamp.

1. Pair the bulbs: switch the lamp off and on 6 times. All its spots reset together and join while pairing is open.
2. Under **Laitteet → Valot**, tap **Yhdistä valaisimeksi** ("Group into a fixture"), give it a name and room, and choose its bulbs.

Each command goes to every bulb at once. The fixture counts as on if any of its bulbs is on, at the brightest one's level. If a bulb doesn't answer, the others still follow. A bulb's roles (motion rule, remote, wake-up lamp) pass to its fixture. Removing a fixture makes its bulbs lamps of their own again.

**Ordinary dimmable bulbs** (e.g. SOLHETTA) can be controlled with an in-wall Zigbee dimmer instead. One example is the **AGGE 2-gang Zigbee push dimmer**: it needs no neutral wire, fits behind a two-button push switch in a Finnish switch box, and handles 5–100 W per channel. An electrician installs it.
- **Each channel is a lamp of its own** in Kotivalo, listed under its device as "Kanava 1" and "Kanava 2". Removing the device removes both.
- **The wall buttons keep working** without the Pi: click to switch, hold to dim.
- **If the lowest levels flicker,** raise the dimmer's minimum brightness on the device itself.

**Smart plugs** (IKEA **TRETAKT**) make an ordinary lamp switchable. Kotivalo treats a plug as a lamp that only switches on and off:
- **Pairing:** start pairing under **Laitteet → Lisää laite**, then hold the plug's small button for about 5 seconds until its light blinks.
- **Its card** shows a plug icon. A tap switches it; there is no brightness to drag. ⚙ has the motion and "Vain käsin" settings.
- **Everything else works as for other lamps:** motion sensors, remotes (on and off; "brighter" switches it on) and the master switch. It can't be the wake-up lamp, as a sunrise needs dimming.
- **After a power cut** it goes back to how it was, so a cut at night doesn't light the lamp.
- **The plugs also strengthen the Zigbee network:** being mains-powered, they relay messages for the devices around them.

**Buying bulbs:** IKEA's **TRÅDFRI** smart bulbs (e.g. GU10 345 lm white spectrum) are Zigbee and work. IKEA's newer **KAJPLATS** range is Matter over Thread, which needs a Thread radio and a Matter stack. Its Zigbee mode is unofficial and stripped down, so avoid it. Ordinary bulbs like **SOLHETTA** have no radio at all.

## All lamps at once

**Kaikki pois** ("All off") on the Lights page and the wall panel:
- It switches every lamp off.
- It remembers which lamps were lit, at what brightness and warmth, and who controlled them.

**Later:** the timer button next to it (**Sammuta myöhemmin**, "Switch off later") switches everything off **in 1 or 5 minutes**, e.g. time to walk out or get into bed.
- While it counts down, the button shows **Pois 5 min päästä** ("All off in 5 min") with **Peru** ("Cancel").
- What it remembers is whatever is lit when the time is up.
- The countdown survives a restart of Kotivalo. If Kotivalo was down for over 10 minutes past the time, it's dropped instead.

**Palauta valot** ("Restore lights") brings that set back:
- Lamps that were on by hand come back exactly as they were.
- Lamps the motion sensor had lit go back to their sensor. They come on again only when it sees someone in a dark room.

**The memory** is kept until the next "All off", so the button always restores your usual lights. Before the first "All off" it reads **Kaikki päälle** ("All on") and switches every lamp on at its last setting by hand.

**Alarms are not affected:** the next sunrise starts as usual. A sunrise that is running right now stops, like any manual off.

**From a remote:** a remote can be the master switch instead of controlling its own lamps (see Remotes).

## Motion lighting

Set up per sensor under **Laitteet → (sensor) → settings**:
- **the lamps it switches.** A lamp can have only one sensor.
- **"only when darker than"**, with the live lux reading. The lux value counts only when the sensor's lamps have been off for a minute, so the lamp's own light doesn't count.
  - A sensor that only tells bright from dim (the SONOFF SNZB-06P) offers **"Vain hämärässä"** ("only when it is dim") instead. It measures the light as it sees someone come in, and its lamps wait up to a second for that reading.
  - The sensor's own threshold can't be changed, and the SNZB-06P calls an overcast October afternoon "bright". If its lamps stay off by day when you'd want them, choose **"Aina"** (always).
  - While the room counts as bright, the lamp's ⚙ says so: "Huoneessa on joku, mutta siellä on valoisaa".
- **the off time:** switch off once the room has been empty this long.
- **day and night brightness and warmth.** The default night light is 5 %, 2200 K.

**Night** is a global setting (Asetukset, default 23–07). It ends early when that morning's sunrise starts.

**A sensor that stays silent for 10 minutes** counts as an empty room, for example when its battery runs out. A USB-powered presence sensor (the SNZB-06P) is asked every 3 minutes instead, so a long stay keeps the lights on; it has no battery and must stay plugged in. Use rechargeable batteries (IKEA LADDA): ordinary 1.5 V batteries make the VALLHORN see motion that isn't there.

## Daylight

A lamp can follow daylight: warm around sunrise and sunset, cool by day. Switch it on in the lamp's ⚙ (**Seuraa päivänvaloa**); only lamps with adjustable warmth have it.

**The curve** is set under **Asetukset → Päivänvalo**:
- **the warm and the daylight warmth** (default 2700 K and 4000 K, the FLOALT's coolest).
- **Aamu:** when the light starts cooling and when it is fully cool, as minutes from sunrise (default: from sunrise to 2 h after).
- **Ilta:** when it starts warming and when it is fully warm, as minutes from sunset (default: from 2 h before sunset to sunset).
- Each slider shows what its point means in clock time today, and the band shows the whole day's colours. A saved change applies at once.

**The sun's times** are calculated for the weather place, so the curve follows the seasons: in Espoo the sun rises at 9.25 and sets at 15.13 in December, 3.54 and 22.51 in June. On a short winter day the morning and evening slopes may overlap, and the light then never reaches full daylight. Without a weather place nothing changes.

**What it changes:** only the warmth, while the lamp is on, in small steps (a CT transition would freeze an IKEA lamp). The brightness stays yours. A lamp switched on (by hand, a remote, motion or the master switch) comes on at the warmth of the moment.

**What it leaves alone:**
- **Warmth set by hand** (the slider or a remote's arrows) wins until the lamp is switched off. "Jatka nyt" in the lamp's ⚙ resumes at once.
- **A running sunrise**, **"Vain käsin"**, and **the motion night light**, which keeps its own warmth.

## Remotes

Choose the lamps a remote controls under **Laitteet → (remote) → settings**. The row shows the last button pressed and the battery level.

| Button | What it does |
|---|---|
| On / Off (STYRBAR, RODRET, E1743) | switches the lamps on (last setting by hand) or off |
| Centre (5-button) | on/off: off if any of its lamps is on |
| Hold up / down | dims smoothly until released |
| Tap up / down (5-button) | ±20 % |
| Left / right arrows (STYRBAR, 5-button) | warmer / cooler; repeats while held |

**As the master switch:** turn on **Pääkytkin: kaikki valot** in the remote's settings, e.g. for a remote by the front door.
- **Off** is "Kaikki pois": every lamp off, remembering which were lit.
- **On** is "Palauta valot".
- **The 5-button remote's centre button** switches off if anything is lit, otherwise restores.
- **Its other buttons** do nothing. It has no lamps of its own.

**During a sunrise:** any remote or UI action on the wake-up lamp ends the sunrise and skips that alarm. "On" then means full brightness ("I'm up").

**Old firmware:** a 5-button remote or on/off switch on firmware older than 2.3.075 sends its presses only to a Zigbee group, which Kotivalo doesn't listen to yet. Its row then shows no presses. Use **Päivitä laiteohjelmisto** in the remote's settings to update it from IKEA's server:
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
- **Every switch-off from the Pi fades out:** the app, a remote, motion, or the end of a sunrise. The lamp dims smoothly to minimum (about half a second) and switches off. "On" restores the brightness and warmth you last set by hand.
- **The wake-up lamp also turns warm** at that dim level before switching off, so a sunrise or night light never starts with a flash of a cooler setting. Other lamps keep their warmth.
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

## Weather

Set the place under **Asetukset → Sää**: search for your town, or type its coordinates (`60.17, 24.94`), then tap the result.
- **What it shows:** a line on the Lights page and the wall panel with the current weather (icon, temperature, wind) and the next three 3-hour marks, e.g. 18, 21, 00.
- **Updates:** the Pi fetches the forecast from MET Norway, the data behind yr.no, when the previous one expires (about every 30 minutes).
- **If a fetch fails:** the last forecast stays for up to 3 hours, then the line is hidden.
- **Location privacy:** the place is stored rounded to about 1 km. The search uses Open-Meteo's geocoder, and only when you search.
- **Source:** weather data from MET Norway (yr.no), CC BY 4.0.

## Wall panel

On a tablet mounted on a wall or by the bed, open the UI and switch on **Asetukset → Tämä näyttö on seinäpaneeli** ("This screen is a wall panel"). The setting applies to that screen only.

- The panel shows a large clock, the weather, the next alarm (with skip) and the lamps.
- The lamp cards work as everywhere else: **tap** to switch, **drag sideways** to set the brightness, **⚙** for the rest. The controls close by themselves after a minute untouched.
- **At night** the screen is almost black with a dim amber clock, the next alarm and the weather, all drifting a little to prevent burn-in. The first touch only wakes the screen, so it never switches a lamp by accident.
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
| `src/kotivalo/daylight.py` | pure maths: sunrise and sunset, the daylight warmth curve |
| `src/kotivalo/behaviour.py` | pure owner model: motion, manual, sunrise, timers |
| `src/kotivalo/remotes.py` | pure decoder: remote frames to button actions |
| `src/kotivalo/sunrise.py`, `scheduler.py` | runs one sunrise; starts and resumes alarms |
| `src/kotivalo/light.py` | `Light` protocol, `FakeLight`, `LightController`, `LatestWins` |
| `src/kotivalo/registry.py`, `settings.py` | devices and lamps; versioned `settings.json` |
| `src/kotivalo/zigbee.py`, `events.py` | zigpy: startup, binding, reports and presses as events, firmware updates |
| `src/kotivalo/xbee_config.py` | raw XBee AT frames (one-time setup, `radio-info`) |
| `src/kotivalo/weather.py` | MET Norway forecast: fetch, parse, place search |
| `src/kotivalo/app.py`, `web.py` | the service, JSON API and live-update stream |
| `web/` | the React UI (built into `src/kotivalo/static/`) |
| `deploy/` | `pi-setup.sh`, `deploy.sh`, systemd unit |

State lives in `/var/lib/kotivalo` on the Pi:
- `settings.json`: devices, lamps, wake-up, night, motion rules, remotes, weather place, daylight, radio
- `state.json`: skipped alarms, last run, lamp owners and timers, lamps whose daylight is paused by hand
- `zigbee.db`: zigpy's device database, including the network key

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'     # the Pi runs Python 3.13
.venv/bin/pytest -q && .venv/bin/ruff check .
.venv/bin/kotivalo --state-dir var serve --fake --fake-lamps 6 --port 8080   # in-memory devices
cd web && npm ci && npm run dev    # UI with hot reload, /api proxied to :8080
cd web && npm run lint && npm test && npm run e2e
```

`serve --fake` has fake lamps, motion sensors (`--fake-sensors`) and remotes (`--fake-remotes`). `POST /api/fake/event` with `{"type": "motion" | "lux" | "bright" | "battery" | "button", "ieee": ..., "value": ...}` plays a device event.

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
   kotivalo radio-info              # read-only: firmware, network (XBee: AP, baud too)
   kotivalo xbee-config             # XBee only, one-time: AP=2 + 57600 baud, verified before saving
   kotivalo form-network --channel 25
   ```

   **Choosing a channel:**
   - Pick a Zigbee channel away from your Wi-Fi. Wi-Fi channel 1 → Zigbee 20 or 25; channel 6 → 25; channel 11 → 15. Check with `nmcli -f CHAN,SSID dev wifi`.
   - Forming a new network means every device must be paired again.
   - Don't re-form unnecessarily: the XBee's flash wears with each write.
   - The service never forms a network by itself, on any radio.
5. Start the service with `deploy/deploy.sh`, then pair devices from the UI (Laitteet → Lisää laite).

   The CLI can pair and control lamps too (`kotivalo pair`, `devices`, `light level 128`), but radio commands need the service stopped first: `sudo systemctl stop kotivalo`.

## Troubleshooting

- **"The radio is in use":** the service holds the radio. Stop it before using CLI radio commands.
- **"The radio has no Zigbee network yet":** run `form-network`. The service exits with code 78 and systemd does not retry.
- **A lamp stops responding:**
  - Check that the wall switch is on.
  - Look at its row under Laitteet ("seen …").
  - Re-pair if needed: 6 off/on cycles while pairing is open.
- **Motion doesn't switch a lamp on:** read the lamp's status line.
  - "Käsin päällä" means you switched it on by hand, and motion leaves it alone.
  - "Pois, liike tauolla" means you switched it off by hand, and motion is paused.
  - "Palauta liikeohjaus" hands the lamp back to the sensor.
  - "Huoneessa on joku, mutta siellä on valoisaa" (in ⚙) means the sensor finds the room bright. Check the lux value (or "valoisaa", bright) in the sensor's settings, or choose "Aina" there.
- **A remote's presses don't show on its row:**
  - It may still be setting up: press its pairing button 4 times near a lamp.
  - On old firmware, update it (see Remotes).
  - Check the battery: a weak one makes the remote drop off the network mid-setup.
- **Every device stops answering at once, while the UI works:** the radio may have stopped receiving. Restart the service: `sudo systemctl restart kotivalo`.
  - The UI notices this: when no device has been heard for 10 minutes, a banner says so on every page. **Asetukset → Zigbee-radio** shows the stick, its firmware and network, and when a device was last heard. The lamps answer every minute, so that should say "juuri nyt" or a minute or two.
  - The old XStick did this after resetting itself: `No 'rx' handler` in the log (`journalctl -u kotivalo`), as it then sent messages in a form zigpy-xbee drops.

## Changing the radio

The code talks to zigpy's generic API, so a new radio is a settings change. But a new radio means a new network, and **every device must be paired again**. Names, rooms, fixtures, motion and remote rules and the wake-up lamp are kept, because they are saved by device address.

**The SONOFF Dongle Plus MG24** replaced the XStick on 2026-10-21. Re-pairing all 14 devices took about 25 minutes.
- Firmware EmberZNet 7.4.5 as shipped, 115200 baud: no update needed.
- Network formed: channel 25, PAN 0xAE6B. zigpy's backups of an EZSP network include the network key, so a later stick swap can restore it without re-pairing.

**The switch-over** (on the Pi, in `~/kotivalo`; check that no sunrise is running):

1. Stop the service: `sudo systemctl stop kotivalo`.
2. Point the settings at the new radio and keep the old device database aside:

   ```sh
   cd /var/lib/kotivalo
   cp settings.json settings.xbee.json
   for f in zigbee.db*; do mv "$f" "zigbee.xbee${f#zigbee}"; done   # with its -wal, -shm
   python3 - <<'PY'
   import json
   s = json.load(open("settings.json"))
   s["radio"] = {"type": "ezsp", "baudrate": 115200, "flow_control": None, "channel": 25,
       "path": "/dev/serial/by-id/usb-SONOFF_SONOFF_Dongle_Plus_MG24_048489522075f011ad93ae2f1045c30f-if00-port0"}
   json.dump(s, open("settings.json", "w"), indent=2)
   PY
   ```

3. A radio without a network needs `kotivalo form-network --channel 25` (the Sonoff already has one: `kotivalo radio-info` shows it).
4. Start the service: `sudo systemctl start kotivalo`. **Asetukset → Zigbee-radio** should now show the SONOFF Dongle Plus MG24 on channel 25, PAN 0xAE6B.
5. Unplug the old radio before re-pairing. If both networks are on the same channel, a reset device might join the old one. The old network stays stored in the stick.
6. Pair every device again (see [Adding devices](#adding-devices)): the lamp nearest the Pi first, then the other lamps, since they relay for the battery devices, then sensors and remotes next to a lamp. Under **Laitteet**, a device still to be paired says "Ei liitetty".

**Going back:** with the service stopped, plug the XStick back in and put `settings.xbee.json` and the `zigbee.xbee.db*` files back. Devices already paired to the new radio must then be paired again.
