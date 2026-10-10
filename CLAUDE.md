# CLAUDE.md

Working notes for changing this code. `README.md` is the user manual; `docs/ROADMAP.md` lists planned work and known issues.

## System

- **Pi:** Raspberry Pi 3B+, Pi OS Lite (Debian 13, aarch64, **Python 3.13**), `pi@wakeup-light.local` (192.168.1.174), passwordless sudo.
- **Radio:** Digi XStick2 ZB (XBee S2, EM250, ZB Coordinator API firmware 21A7) at `/dev/serial/by-id/usb-Digi_XStick-if00-port0`.
  - Settings: AP=2, 57600 baud. Zigbee channel 25 (Wi-Fi is on channel 6).
  - Uses zigpy 2.3.0 + zigpy-xbee 0.22.0. zigbee2mqtt does not support XBee.
- **Light:** IKEA "FLOALT panel WS 60x60" (`50:32:5f:ff:fe:6e:e5:2c`), 250–454 mired.
- **Service:** systemd unit `wakeup-light`, web UI on port 8080.
- **State:** `/var/lib/wakeup-light` (`settings.json`, `state.json`, `zigbee.db`).
- **Laptop:** dev venv uses Python **3.11.0rc1**, which is not the Pi's 3.13. Code must work on both.

## Commands

```sh
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/wakeup-light --state-dir var serve --fake --port 8080   # local UI, in-memory light
deploy/deploy.sh                 # runs tests, then rsync + install + restart the service on the Pi
ssh pi@wakeup-light.local journalctl -u wakeup-light -b   # journal is in RAM: lost on reboot
```

CLI radio commands (`pair`, `light`, `devices`, `form-network`, `xbee-config`, `radio-info`) run on the Pi and need the service stopped first: `sudo systemctl stop wakeup-light`. The service and the CLI take the same `flock`, so only one opens the radio at a time.

## Hard rules

**Radio (XBee):**
- **Never form or re-form the network automatically** (`auto_form` is off for xbee). Every write wears the EM250's flash, and a new network means re-pairing every device.
- Use `xbee-config` only for the one-time AP/baud change, which issues a single `WR`.

**IKEA lights** (verified on the FLOALT):
- **Minimum level is 2.** Level 1 switches it off.
- **Never send a colour-temperature (CT) command with a transition.** It freezes the light until the transition ends. Send CT with transition 0.
- **One transition at a time.** A new command cancels the running transition. Never overlap CT and level changes: send CT first, wait ~0.3 s, then the level.
- **CT is ignored while the light is off.** Switch it on first.
- **Switch off with plain `on_off.off()`.** An off with a transition can leave IKEA lights on.

**asyncio:**
- **Use `asyncio.timeout`, never `asyncio.wait_for`.** On Python 3.11, `wait_for` can swallow a cancellation, which once made the service shutdown hang.
- **Shutdown must never hang.** Keep background-task waits bounded.
- **The service must exit (not hang) on startup errors,** so that systemd restarts it.

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
- **`zigbee.py`:** the only module that touches zigpy for light control. `xbee_config.py` uses raw serial frames, stdlib only.
- **`app.py` (`Service`)** wires everything together. `web.py` is a thin JSON API.
- **`static/`:** plain HTML/JS/CSS, no build step. Write requests must be JSON, which acts as the CSRF guard.

## Testing and verification

- Test against `FakeLight` + `FakeClock`. `FakeClock.sleep*` advances time instantly.
- Hardware checks go through the HTTP API (`curl` against `http://wakeup-light.local:8080/api/...`).
  - Restore the user's alarms and ramp settings afterwards.
  - Don't leave the light on at night.
- Deploying restarts the service. A running sunrise resumes from the wall clock, but check for one first.
- Commit only when asked. Commit messages end with the `Co-Authored-By` line.
