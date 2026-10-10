# CLAUDE.md

Working notes for changing this code. `README.md` is the user manual; `docs/ROADMAP.md` lists planned work and known issues.

## System

- **Pi:** Raspberry Pi 3B+, Pi OS Lite (Debian 13, aarch64, **Python 3.13**), `pi@kotivalo.local` (192.168.1.174), passwordless sudo.
- **Radio:** Digi XStick2 ZB (XBee S2, EM250, ZB Coordinator API firmware 21A7) at `/dev/serial/by-id/usb-Digi_XStick-if00-port0`.
  - Settings: AP=2, 57600 baud. Zigbee channel 25 (Wi-Fi is on channel 6).
  - Uses zigpy 2.3.0 + zigpy-xbee 0.22.0. zigbee2mqtt does not support XBee.
- **Devices** (the user's home; restore their state after tests):

  | Device | IEEE | Role |
  |---|---|---|
  | FLOALT panel WS 60x60 (250–454 mired) | `50:32:5f:ff:fe:6e:e5:2c` | panel 1, a normal lamp |
  | FLOALT panel WS 60x60 | `d0:cf:5e:ff:fe:1f:a3:9e` | panel 2, the wake-up lamp; the VALLHORN switches it |
  | VALLHORN motion sensor | `8c:65:a3:ff:fe:3d:d1:6d` | dark_lux 30, off after 5 min (the user's settings) |
  | STYRBAR remote | `cc:86:ec:ff:fe:92:d6:09` | controls panel 1 |
  | TRÅDFRI 5-button remote (E1810) | `84:2e:14:ff:fe:41:64:b9` | firmware 2.3.014: group-only, so not working yet; its update failed (weak battery?) |
- **Service:** systemd unit `kotivalo`, web UI on port 8080.
- **State:** `/var/lib/kotivalo` (`settings.json`, `state.json`, `zigbee.db`).
- **Laptop:** dev venv uses Python **3.11.0rc1**, which is not the Pi's 3.13. Code must work on both.

## Commands

```sh
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/kotivalo --state-dir var serve --fake --fake-lamps 6 --port 8080   # in-memory devices
#   also --fake-sensors N, --fake-remotes N; POST /api/fake/event {type: motion|lux|battery|button, ieee, value}
cd web && npm run dev            # UI with hot reload, /api proxied to :8080 (KOTIVALO_API=... for the Pi)
cd web && npm run lint && npm test && npm run e2e   # oxlint, Vitest, Playwright (needs a build)
cd web && npm run screenshots -- <out-dir>          # every layout + panel day/night (needs serve on :8099)
deploy/deploy.sh                 # all checks, UI build, then rsync + install + restart on the Pi
ssh pi@kotivalo.local journalctl -u kotivalo -b   # journal is in RAM: lost on reboot
```

CLI radio commands (`pair`, `light`, `devices`, `form-network`, `xbee-config`, `radio-info`) run on the Pi and need the service stopped first: `sudo systemctl stop kotivalo`. The service and the CLI take the same `flock`, so only one opens the radio at a time.

## Hard rules

**Radio (XBee):**
- **Never form or re-form the network automatically** (`auto_form` is off for xbee). Every write wears the EM250's flash, and a new network means re-pairing every device.
- Use `xbee-config` only for the one-time AP/baud change, which issues a single `WR`.
- **zigpy's OTA stays disabled** (`"ota": {"enabled": False}` in `zigpy_config`): lamps must never update themselves. Firmware updates run only on request, for remotes (`find_firmware`/`update_firmware` in `zigbee.py`).
- **Bindings are unicast to the coordinator.** The XStick drops group-addressed frames, so a device that only sends to groups (E1743/E1810 before firmware 2.3.075) is never heard.
- **Sleepy devices (sensors, remotes) answer only while awake:** right after joining, a button press or motion. Configure them then (`_configure_soon`), with 30 s timeouts. A failed setup is retried at most every 5 min: queued requests to a sleeping device slow the XStick down.

**IKEA lights** (verified on the FLOALT):
- **Minimum level is 2.** Level 1 switches it off.
- **Never send a colour-temperature (CT) command with a transition.** It freezes the light until the transition ends. Send CT with transition 0.
- **One transition at a time.** A new command cancels the running transition. Never overlap CT and level changes: send CT first, wait ~0.3 s, then the level.
- **While off** (tested on panel 2, firmware 1.2.217, 2026-10-10):
  - **Brightness can't be preset.** ExecuteIfOff is ignored for Level Control, both per command (`options_mask`/`options_override`) and as the `options` attribute. The attribute is writable, but has no effect.
  - **Colour temperature is stored, but it doesn't help.** A plain `move_to_color_temp` while off changes `color_temperature` (no flag needed), and the lamp reports it as soon as it's on. By eye, though, it still comes on at the warmth it last had while lit, then shifts. So parking warmth *before* off, and setting CT after switching on, remains the only way.
- **Switch off with plain `on_off.off()`.** An off with a transition can leave IKEA lights on.

**asyncio:**
- **Use `asyncio.timeout`, never `asyncio.wait_for`.** On Python 3.11, `wait_for` can swallow a cancellation, which once made the service shutdown hang.
- **Shutdown must never hang.** Keep background-task waits bounded.
- **The service must exit (not hang) on startup errors,** so that systemd restarts it.
  - On failure, zigpy closes the radio but not its database thread. `start_app()` therefore always calls `app.shutdown()`.
  - The unit is `Type=notify`. It sends `READY=1` once the radio and web UI are up, and `WatchdogSec=60` is pinged from the event loop by `systemd.py`.
- **Startup must not depend on the lamp being powered.** Permit-join broadcasts may be unrelayed (`TolerantPermit`).

## Code map

The pure logic has no I/O and is fully unit-tested:
- `ramp.py`: brightness curve, colour temperature, tick plan
- `schedule.py`: alarm occurrences, computed in UTC so DST is handled

Everything else:
- **`sunrise.py`:** runs one sunrise with cancel/resume.
- **`scheduler.py`:** decides when an alarm should run, from the wall clock and `state.json`.
- **`light.py`:**
  - the `Light` protocol
  - `FakeLight`, for tests and `--fake`
  - `LightController`, whose lock keeps a CT+level pair from interleaving with other commands
- **`behaviour.py`:** the pure owner model (off / manual / motion / sunrise per lamp): motion rules, manual wins, manual off pauses motion until the room has been empty, "let motion control it" (`automatic`), the night window, timers (`tick`, `next_deadline`). Returns actions (`SwitchOn`, `SwitchOff`); `Service._run_actions` performs them. Saved in `state.json`.
- **Master switch** (`Service.master_switch`, `POST /api/master {action: on|off}`):
  - **"off":** saves `{level, kelvin, owner}` of the lit lamps in `state.json` (`State.master`), then sends `lamp_action(off)` to each.
  - **"on":** restores manual lamps via `last_manual` + `lamp_action(on)`, and hands motion-lit ones back with `lamp_action(auto)`. With no memory, every lamp comes on.
  - **The memory** is kept until the next "off" that finds something lit.
- **`weather.py`:** MET Norway Locationforecast (yr.no). `parse_met` and `Forecast.view(now)` are pure. `MetClient` sends a User-Agent and If-Modified-Since, and the service refetches only when `Expires` says, clamped to 10–60 min (MET's terms). `Service._weather_loop` runs it; `serve --fake` uses `fake_forecast` and never touches the network. Place search: Open-Meteo geocoder, or typed coordinates.
- **`remotes.py`:** pure decoder from remote ZCL frames to actions (on, off, toggle, brighter/dimmer, *_hold, dim_stop, warmer/cooler, arrow_stop). De-duplicates by sequence number (every frame arrives ~4 times through the XStick) and drops STYRBAR's stray "on" after an arrow. `Service._remote_pressed` maps actions to the remote's lamps.
- **`settings.py`:** versioned `settings.json` (v2: devices, lights, wakeup, night, motion, remotes). A v1 file is migrated on load and kept as `settings.v1.json`. `serve --fake` devices (`FAKE_PREFIX`) are never saved.
- **`registry.py`:** devices reported by the radio (`Discovered`) and one `LightController` per lamp. Radio-agnostic.
- **`zigbee.py`:** the only module that touches zigpy for light control (`classify`/`discover` turn zigpy devices into `Discovered`).
  - `EventBridge` turns zigpy callbacks into `events.py` domain events on `Service.events`. It is attached before the radio starts (the `start_app(on_created=...)` hook). Every callback is wrapped in try/except: zigpy's `emit()` lets exceptions escape into packet handling.
  - `configure_lamp` binds on/off, level and colour to the coordinator and configures reporting. Verified on the FLOALT: reports arrive.
  - `configure_sensor` (VALLHORN: occupancy, illuminance, battery; its OnOff output deliberately unbound) and `configure_remote` (OnOff, Level and Scenes outputs bound with raw ZDO `Bind_req`, since STYRBAR's descriptor lacks Scenes although its arrows use it) set up battery devices.
  - `EventBridge.handle_message` sees every frame before zigpy's cluster matching: it emits `Seen`, `Announce` (Device_annce: a lamp got mains power back) and `Button`.
- **Lamp state** is what we commanded, corrected by reports (`LightController.apply_report`, ignored for 5 s after our own command: the echo guard) and by polling (every 60 s, backing off to 10 min while a lamp doesn't answer; unreachable is not off). `xbee_config.py` uses raw serial frames, stdlib only.
- **`app.py` (`Service`)** wires everything together. `web.py` is a thin JSON API.
  - Per-lamp level/warmth go through `LatestWins` (`light.py`), so a dragged slider never queues behind the radio.
  - **Off fades out** (`LightController.off`):
    1. `fade` (Level `move_to_level` *without* on/off, so an off lamp ignores it) to minimum over `OFF_FADE_S`
    2. the wake-up lamp only: CT warm, instantly, at that dim level (others keep their warmth)
    3. plain off
    - A UI or remote off counts as off at once (`switching_off`) and fades in the background.
  - "On" (UI or remote) restores the lamp's last manual level and warmth (`_manual_on`), since every lamp is parked at minimum. During a sunrise "on" means full brightness.
  - Remote hold-to-dim uses the lamp's native `move`/`stop`, then reads the level back; arrows step 40 mired, repeating while held.
  - `GET /api/events` (SSE) pushes the full state on every change: call `service.notify()` after anything that changes state (web writes do it in the `guard` middleware).
- **`web/`:** the React UI (TypeScript, Vite, Tailwind v4, shadcn/ui on Radix), built into `src/kotivalo/static/` (gitignored; `deploy.sh` builds it).
  - `api/`: REST client, `live.tsx` (one SSE `EventSource` feeding every view), `actions.ts` (calls plus error toasts).
  - `i18n/`: `fi.ts` is typed against `en.ts`, so a missing translation fails the build.
  - `lib/`: pure helpers (format, light colour, night window, lamp state, rooms, layout), all unit-tested.
  - `pages/`: lights, wakeup, devices, settings, and `panel.tsx` (the wall panel).
  - `components/ui/` is generated by shadcn; buttons are enlarged to 44 px touch targets.


## UI rules

- **All UI text goes through `i18n/` in both Finnish and English.** The server sends data (owner, times, levels), never display text.
- **Times are shown in the home's timezone** (`snapshot.timezone`), formatted with `Intl` (`6.30` in Finnish).
- **Design:** the tokens are in `web/src/index.css`: a "blue hour" dark theme and a cool snow light theme. A lamp's own light colour (kelvin plus level, `lib/light-color.ts`) is the only accent. The wall panel is always dark, and at night shows only a dim amber clock.
- **Touch targets are at least 44 px.** Lamp level 1 must never be sent (it switches a FLOALT off): `percentToLevel` clamps to 2.
- **Write requests must be JSON:** that is the CSRF guard.

## Testing and verification

- Test against `FakeLight` + `FakeClock`. `FakeClock.sleep*` advances time instantly.
- Hardware checks go through the HTTP API (`curl` against `http://kotivalo.local:8080/api/...`).
  - The lamps may be in use: note every lamp's state (`/api/state`) before a test and restore it afterwards, along with the user's alarms and ramp settings.
  - Don't leave the light on at night.
- Deploying restarts the service. A running sunrise resumes from the wall clock, but check for one first.
- Commit and push at the end of each phase or fix without asking: the user gave standing permission on 2026-10-10. Commit messages end with the `Co-Authored-By` line.
