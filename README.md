# wakeup-light

A sunrise alarm for an IKEA Zigbee light, running on a Raspberry Pi.

Before each alarm the light fades in. It starts as a dim warm glow and reaches full,
cooler white at the alarm time, then switches off after a set time. You set alarms and
control the light from a phone-friendly web page on the Pi.

**Hardware:**
- Raspberry Pi 3B+ running Raspberry Pi OS Lite
- Digi XStick2 ZB, an XBee Series 2 with Coordinator API firmware
- IKEA FLOALT panel (white spectrum)

**Software:**
- [zigpy](https://github.com/zigpy/zigpy) and [zigpy-xbee](https://github.com/zigpy/zigpy-xbee), the radio stack Home Assistant's ZHA uses. zigbee2mqtt does not support XBee radios.
- aiohttp for the web UI.

Web UI: `http://wakeup-light.local:8080`, or by IP (currently `http://192.168.1.174:8080`) on phones that do not resolve `.local` names.

## How the sunrise works

- **Brightness:** `level = 2 + 252 · p^2.5`, so it rises slowly at first. The minimum is level 2, because level 1 switches a FLOALT off.
- **Colour temperature:** moves linearly from 2200 K to 4000 K.
- **Timing:** about 60 steps per ramp, at most one every 30 s.
- **Each step:**
  1. Set the colour temperature with no transition.
  2. Wait 0.3 s.
  3. Start a brightness transition that ends 2 s before the next step.

  IKEA lights run one transition at a time and freeze on colour-temperature transitions, so the two never overlap.
- **At the alarm time:** full brightness and coolest white are sent again, in case a command was lost.
- **Switching off:** after the "switch off" time the light is first set back to warm, then switched off with no transition. The next switch-on then starts warm.
- **Times:** alarms are local wall-clock times (Europe/Helsinki). Ramp windows are computed in UTC, so a fade across a DST change still lasts its full length.

**Behaviour:**
- **Manual control stops a running sunrise.** Any light control in the UI stops the sunrise and skips that alarm; the scheduler won't restart it.
- **The ramp never dims a light that is already brighter.**
- **Restarts resume.** A restart or reboot mid-sunrise resumes at the right point, from the wall clock.
- **Radio failures restart the service.** If the radio stops answering, the service exits and systemd restarts it.

## Layout

| Path | What |
|---|---|
| `src/wakeup_light/ramp.py`, `schedule.py` | pure maths: curve, tick plan, alarm occurrences |
| `src/wakeup_light/sunrise.py`, `scheduler.py` | runs one sunrise; starts/resumes alarms |
| `src/wakeup_light/light.py` | `Light` protocol, `FakeLight`, `LightController` |
| `src/wakeup_light/zigbee.py` | zigpy startup, `ZigbeeLight`, radio lock |
| `src/wakeup_light/xbee_config.py` | raw XBee AT frames (one-time setup, `radio-info`) |
| `src/wakeup_light/app.py`, `web.py`, `static/` | the service, JSON API, phone UI |
| `deploy/` | `pi-setup.sh`, `deploy.sh`, systemd unit |

State lives in `/var/lib/wakeup-light` on the Pi:
- `settings.json`: alarms, ramp, radio, the selected light
- `state.json`: skipped alarms, last run
- `zigbee.db`: zigpy's device database

## Development

```sh
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q && .venv/bin/ruff check .
.venv/bin/wakeup-light --state-dir var serve --fake --port 8080   # UI with an in-memory light
```

## Deploy

```sh
deploy/deploy.sh               # ruff + pytest, rsync, pip install on the Pi, restart the service
deploy/deploy.sh --no-service  # code only (for CLI work with the service stopped)
```

Logs: `ssh pi@wakeup-light.local journalctl -fu wakeup-light`. The journal is kept in RAM, so logs don't survive a reboot. The UI footer shows the result of the last alarm.

## Setting up a Pi from scratch

1. Flash Raspberry Pi OS Lite (64-bit) and set up the user `pi` with SSH key login. Enable passwordless sudo for pi.
2. Run the one-time system setup. It ends with a reboot.

   ```sh
   ssh pi@raspberrypi.local 'sudo bash -s' < deploy/pi-setup.sh
   ```

   It does the following:
   - renames the Pi to `wakeup-light` (or `NEW_HOSTNAME`), so it becomes `wakeup-light.local`, and stops cloud-init from resetting the name
   - apt full-upgrade
   - turns Wi-Fi power saving off
   - keeps the journal in RAM
   - makes boot wait up to 3 min for NTP
   - disables ModemManager and brltty
   - creates the state directory
3. Install the code only: `deploy/deploy.sh --no-service`.
4. Prepare the radio. These commands are on the Pi, in `~/wakeup-light`, using `.venv/bin/wakeup-light`.

   ```sh
   wakeup-light radio-info              # read-only: firmware, AP, baud, network
   wakeup-light xbee-config             # one-time: AP=2 + 57600 baud, verified before saving
   wakeup-light form-network --channel 25
   ```

   **Choosing a channel:**
   - Pick a Zigbee channel away from your Wi-Fi. Wi-Fi channel 1 → Zigbee 20 or 25; channel 6 → 25; channel 11 → 15. Check with `nmcli -f CHAN,SSID dev wifi`.
   - Forming a new network means every device must be paired again.
   - Don't re-form unnecessarily: the XBee's flash wears with each write.
5. Pair the light. With the panel on, switch it off and on 6 times (about 1 s each) and leave it on.

   ```sh
   wakeup-light pair      # opens joining for 254 s; the first light becomes the alarm light
   wakeup-light devices
   wakeup-light light level 128 / ct 2700 / off / state
   ```

   You can also pair from the UI (Devices → Pair) while the service runs. CLI radio commands need the service stopped first: `sudo systemctl stop wakeup-light`.
6. Start the service with `deploy/deploy.sh`.

## Troubleshooting

- **"The radio is in use":** the service holds the XStick. Stop it before using CLI radio commands.
- **"The radio has no Zigbee network yet":** run `form-network`. The service exits with code 78 and systemd does not retry.
- **The light stops responding:**
  - Check that the wall switch is on.
  - Look at `wakeup-light devices` (last_seen).
  - Re-pair if needed: 6 off/on cycles while the network is open for pairing.
- **If the XStick ever won't keep the light joined, swap the radio.** A Sonoff ZBDongle-E or ZBDongle-P works with the same code:
  1. `pip install -e '.[ezsp]'` or `'.[znp]'`.
  2. Set `radio` in `settings.json` to `{"type": "ezsp" or "znp", "path": "/dev/serial/by-id/...", "baudrate": 115200}`.
  3. Pair again. Those radios form their network automatically on first start.
