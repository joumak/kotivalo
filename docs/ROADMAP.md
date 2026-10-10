# Roadmap

**Status (2026-10-10):**
- **Done:** v0.1, a sunrise alarm for one IKEA FLOALT panel with a phone UI.
- **Verified on the hardware:** a test sunrise with no lost commands, resume after a restart, manual override, and reboot.

**Next:** grow from a single wakeup light into general Zigbee lighting control for the home:
- several IKEA lights and remotes
- lights organised into groups
- the sunrise becomes one automation among others

---

## Known issues (fix first)

### 1. ~~Service hangs if no Zigbee router is powered at startup~~ (fixed 2026-10-10)

**What happened:** after a reboot the service printed a traceback but never exited, so systemd never restarted it.

**Causes:**
- zigpy's startup `permit(0)` broadcast fails with `BROADCAST_RELAY_FAILURE` when no router is powered to relay it.
- After the failure, zigpy closes the radio but not its database. The database thread kept the process alive.

**Fixes:**
- `TolerantPermit` (in `zigbee.py`) logs the unrelayed broadcast and still opens the coordinator.
- `start_app()` closes the database on any startup failure.
- `serve()` turns every startup error into an exit code.
- The unit is `Type=notify` with a 60 s watchdog, as a backstop for any future hang.

**Verified:**
- with real zigpy, both on the laptop and on the Pi: the old code hangs, the new code exits
- by `tests/test_startup.py`

### 2. The UI shows the last *commanded* state

Changes made with the wall switch or an IKEA remote are invisible to the UI. This becomes a real problem with remotes and groups (see feature 2).

### 3. Laptop Python differs from the Pi

The laptop uses 3.11.0rc1, the Pi 3.13. This gap already hid one bug (`wait_for`). Use `uv` with Python 3.13 for the dev venv.

---

## Features

### 1. Many lights, organised into groups

**Goal:** control every IKEA light in the home. The living room has three lamps, each with several individually controlled spotlights, so a single lamp is already a group.

**Proposed model:**
```
Room ("Living room")
  └─ Group / fixture ("Floor lamp", "Ceiling spots", ...)
       └─ Light (one Zigbee device/endpoint; IEEE + user-given name)
```
- **Devices:** give every paired device a name and a room. The data lives in `settings.json`, or a separate `devices.json` if it grows.
- **Native Zigbee groups:** use Zigbee groups (`ep.add_to_group(group_id)`, `app.groups`, and the group endpoint for commands). One multicast command switches every spot at the same moment, with no "popcorn" effect, and with less radio traffic.
  - **Risk:** zigpy-xbee's group sending is barely exercised. It has the comment `tx_opts |= 0x08  # where did this come from?`. Test on the XStick early, with two bulbs.
  - **Fallback:** app-level groups that send one unicast per light.
- **The `Light` protocol gets a group implementation.** The sunrise, UI and automations then target "a light or a group" the same way.
- **Group capabilities:** take the intersection of the members' (CT support, mired range). A group with a non-CT bulb gets brightness only.
- **Capacity:** every mains-powered IKEA bulb is a Zigbee router and strengthens the mesh. The XStick itself has weak radio power, so the network will lean on the bulbs.

**Open questions:**
- How many bulbs, and which models?
- Must each spot be controllable alone, or only per lamp?

### 2. IKEA remotes and controllers

**Two ways to wire them:**
- **Bind the remote straight to a Zigbee group.** It works without the Pi and responds instantly, but behaviour is fixed (on/off/dim).
- **Bind the remote to the coordinator and handle its commands in the app.** This is flexible: scenes, "remote press cancels the sunrise", long-press actions.
- **Hybrid:** bind to the group for basic control, and also to the coordinator so the app sees presses.

**Things to know:**
- **Remotes are battery-powered sleepy end devices.** Pair them near a bulb so they choose a bulb, not the XStick, as parent; the EM250 has few child slots. Their commands arrive as zigpy `cluster_command` events on the remote's output clusters.
- **Light state must follow reality.** Configure attribute reporting (`on_off`, `current_level`, `color_temperature`) and bind it to the coordinator. If IKEA reporting proves unreliable, poll a light after a remote press.

**Open question:** which remote models (STYRBAR, RODRET, TRÅDFRI on/off, 5-button...)?

### 3. Automations

- Turn the wakeup sunrise into one automation type, with target, schedule and ramp. Each room or group can then have its own.
- Ideas:
  - evening dimming
  - lights on at sunset (the `astral` library gives Helsinki sun times)
  - "all off" when leaving
  - scenes (saved level and CT per group)
- Generalise the current scheduler, and keep its strengths:
  - wall-clock and UTC handling for DST
  - resume after restart
  - manual action cancels the running automation

### 4. UI: immediate effect while dragging

Today brightness and warmth are sent only when the slider is released.

**Plan:**
- **Browser:** send `input` events throttled to about every 150–250 ms.
- **Server:** keep a "latest value wins" queue per target. While a command is in flight, only the newest pending value is kept, so slow radio replies never pile up.
- **Commands:** send brightness with a short transition (0.2–0.3 s) for smoothness. A new command simply replaces the running transition, which IKEA allows.
- **During a drag:**
  - send CT with no transition, as always
  - throttle CT more than brightness
  - never send CT and brightness at the same moment
- **Groups:** use multicast, which waits for no reply, so dragging stays fast.
- **Navigation:** add a room/group page now that there will be more than one light.

### 5. Flash-free morning start ("arm for wakeup")

**Problem:** IKEA lights come back on at the brightness and CT they had when switched off. Sometimes this is only for a moment before the first command lands. So if the lamp was used bright and cool in the evening, the sunrise starts with a flash. Today:
- Off from the UI or the auto-off parks CT at warm, but leaves the brightness.
- Off with the wall switch or a remote parks nothing.

**Options, cheapest first:**
1. **Park the brightness too.** On every app-initiated off: CT warm → wait → level 2 → off. It's visible as a brief dim-down. The catch: the next manual switch-on starts very dim.
2. **"ExecuteIfOff".** Set the Level Control and Color Control `options` attribute so level and CT commands apply while the light is off, then re-arm silently at any time (for example an hour before the alarm). It's unknown whether the FLOALT's firmware supports this.
   - **Test:** read `sw_build_id`, write the options, send `move_to_level` while off, then read `current_level` back.
3. **Update the FLOALT firmware.** zigpy has an IKEA OTA provider (`ikea`). Newer firmware may support option 2. Over the XBee link an update could take hours, and it carries risk. Try one bulb first.
4. **An explicit "Arm for wakeup" button,** or an evening automation, running option 1 or 2 when the light isn't in use.

**Decide after testing option 2 on the panel.**

### 6. Naming

Once the project is general home lighting, rename the repo, package (`wakeup_light`), service and hostname (for example `valot`). This is easiest before more features build on the names.

**Open question:** the new name.

---

## Hardening (later)

- **Back up the Zigbee network.** Keep a copy of `zigbee.db` (it holds zigpy's network backups, including the network key) and `settings.json` off the Pi. Otherwise a dead SD card means re-pairing every light and remote.
- **Read-only root filesystem (overlay FS):** protects the SD card from power cuts once the setup is stable.
- **Optional web token** (`web_token` in `settings.json`): enable it if the LAN isn't trusted.
- **Health page:** radio status, last-seen time per device, and the result of the last automation.
