# Roadmap

**Status (2026-10-10):** general lighting control for the home. Everything below is verified on the hardware:
- **Lamps:** several, with live state from reports and polling.
- **Wake-up light:** the sunrise.
- **Motion lighting:** with the VALLHORN.
- **Remotes:** through the Pi (the STYRBAR).
- **UI:** a React UI for phones and a wall panel, in Finnish and English.

Done, in order:

| Phase | What | Commit |
|---|---|---|
| 0 | rename to kotivalo | `d16fdc9` |
| 1 | several lamps, settings v2 | `ce6692e` |
| 2 | React UI | `a0f0bf2` |
| 3 | lamp reports and polling | `16e3994` |
| 4 | owner model, motion lighting | `ff7da08`, `b2fe5d8` |
| 5 | remotes and remote firmware updates | `f15ed72`, `f1ff0c8` |
| 6 | docs | |

---

## Known issues

### 1. The 5-button remote (E1810) doesn't work yet

**The cause:** it has firmware 2.3.014, which sends presses only to a Zigbee group, and the XStick drops group frames. Its binding to the Pi is accepted but ignored.

**What happened:** an over-the-air update to 24.4.5 (IKEA image type 0x11C1, 207 KB) was tried. The remote kept dropping off the network mid-setup, probably because of a weak battery.

**Next:** fit a fresh battery, then press **Päivitä laiteohjelmisto** in its settings. The same applies to an E1743 on/off switch on old firmware.

### 2. Every frame arrives four times

Each remote frame reaches the Pi four times within ~40 ms. This is probably MAC-level retries, because the sender doesn't hear the XStick's acknowledgement. `remotes.Decoder` de-duplicates them, and lamp reports are idempotent.

**Effect:** extra airtime only. Check whether lamp reports are also quadrupled; a better radio would probably end it (see feature 4).

### 3. The XStick slows down when a sleeping device has queued requests

Requests to a sleepy device wait at its parent until it wakes, and the XBee seems to stall meanwhile. Once a radio check answered 3 s late. zigpy-xbee then logged `InvalidStateError` from `_handle_at_response`: it sets a result on an already timed-out future. That's harmless, but noisy.

**Mitigation:** setup retries are limited to one every 5 minutes per device.

### 4. Laptop Python differs from the Pi

The laptop uses 3.11.0rc1, the Pi 3.13. Recreate the dev venv with `uv` and Python 3.13 when the folder is renamed to `~/my/kotivalo`.

### Fixed

- **The service hung at startup with no Zigbee router powered.** `TolerantPermit`, the database close on failure, and the systemd watchdog fixed it (`9263e24`).
- **The UI showed only the last commanded state.** Lamps now report on/off, level and warmth; polling and Device_annce catch the rest.
- **The wake-up lamp flashed at the next start.** It is now parked at warm and minimum level before switching off, and "on" restores the last manual setting.

---

## Features

### 1. Lamps organised into groups

**Goal:** the living room has three lamps, each with several individually controlled spots. A fixture should act as one lamp.

**Proposed model:** room → group/fixture → lamp. The `Light` protocol gets a group implementation, so the sunrise, UI, motion rules and remotes target "a lamp or a group" the same way.

- **Native Zigbee groups:** one multicast command switches every spot at the same moment, with no "popcorn" effect and less radio traffic.
  - **Risk:** zigpy-xbee's group sending is barely exercised (`tx_opts |= 0x08  # where did this come from?`). Test on the XStick early.
  - **Fallback:** app-level groups that send one unicast per lamp.
- **Group capabilities:** the intersection of the members' (CT support, mired range).
- **Open question:** must each spot be controllable alone, or only per fixture?

### 2. More remote polish

- A button legend per model in the remote's settings, and its firmware version on the row.
- Long-press actions: for example STYRBAR's arrow hold for scenes, or "all off".
- Pair and check RODRET and the E1743/E1812 when the user has them at hand.

### 3. Automations

- Turn the sunrise into one automation type (target, schedule, ramp), so each room or group can have its own.
- **Ideas:**
  - evening dimming
  - lights on at sunset (`astral` gives Helsinki sun times)
  - "all off" when leaving
  - scenes (saved level and CT per group)
- **Keep the scheduler's strengths:**
  - DST-safe UTC windows
  - resume after a restart
  - manual action wins

### 4. A better radio

A Sonoff ZBDongle-E (EZSP) or ZBDongle-P (ZNP) would bring:
- group traffic, so old-firmware remotes would work
- more child slots
- probably no quadruple frames

The code talks to zigpy's generic API, so swapping is a settings change plus re-pairing (see the README).

### 5. HTTPS on the LAN and an installable app

- A local CA (mkcert) would enable the Wake Lock API, so the wall panel's screen stays on without kiosk apps.
- It would also make the UI installable as an app (PWA).

---

## Hardening (later)

- **Back up the Zigbee network.** Keep a copy of `zigbee.db` (it holds the network key) and `settings.json` off the Pi. Otherwise a dead SD card means re-pairing every device.
- **Read-only root filesystem (overlay FS):** protects the SD card from power cuts.
- **Optional web token** (`web_token` in `settings.json`): enable it if the LAN isn't trusted.
- **Health page:** radio status, last-seen time per device, the last automation's result.
