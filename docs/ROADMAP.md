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
| 6 | docs | `740ad03` |
| — | weather line (MET Norway / yr.no), off the original plan | |

---

## Known issues

### 1. The 5-button remote (E1810) doesn't work yet

**The cause:** it has firmware 2.3.014, which sends presses only to a Zigbee group, and the XStick drops group frames. Its binding to the Pi is accepted but ignored.

**Update attempts:** an over-the-air update to 24.4.5 (IKEA image type 0x11C1, 207 KB) failed over the XStick.
- **2026-10-10:** the remote kept dropping off the network mid-setup, probably because of a weak battery.
- **2026-10-11,** with a fresh battery:
  - **Rejoining:** after its long time without a battery the remote had lost the network (`ADDRESS_NOT_FOUND`) and needed re-pairing (4 presses). Afterwards it answered binds and reads normally.
  - **First attempts (old code):** the remote did ask for its firmware a few minutes after rejoining, while zigpy's fast-poll requests were also being sent. But the traffic queued behind the sleeping remote, the XStick missed two radio checks, and the service restarted. The XStick then didn't answer at the next start; the second start worked.
  - **After the fix** (one continuous session, only the image notify repeated, no fast poll, patient radio check): the notifies were delivered, but the remote never asked, for 30 minutes while idle.
  - **Best guess:** fast polling, sent once at the start rather than per retry, is what makes it ask.
- **Next:** retry with the new radio (feature 4). The same applies to an E1743 on/off switch on old firmware.

**On the Sonoff (2026-10-21):** both E1810s (the first, "64b9", and a second, "5f6d", both firmware 2.3.014) joined and set up fine, but their presses weren't heard.
- **The update works over the Sonoff:** 64b9 went to 24.4.5 from the UI (Päivitä laiteohjelmisto) in 1 h 50 min (22:39–00:31), steadily at 9–13 min per 10 %, with no errors. It rebooted, was set up again at once, and now binds unicast.
- **Next:** check that 64b9's presses arrive, then update 5f6d the same way. The group route (LightLink `get_group_identifiers`, then the coordinator into that group through the EZSP multicast table) is needed only for a remote that can't be updated.

### 2. Every frame arrives four times

Each remote frame reaches the Pi four times within ~40 ms. This is probably MAC-level retries, because the sender doesn't hear the XStick's acknowledgement. `remotes.Decoder` de-duplicates them, and lamp reports are idempotent.

**Effect:** extra airtime only. Check whether lamp reports are also quadrupled; a better radio would probably end it (see feature 4). **Check on the Sonoff.**

### 3. The XStick slows down when a sleeping device has queued requests

**Gone with the XStick (2026-10-21),** unless the Sonoff shows it too.

Requests to a sleepy device wait at its parent until it wakes, and the XBee seems to stall meanwhile. Once a radio check answered 3 s late. zigpy-xbee then logged `InvalidStateError` from `_handle_at_response`: it sets a result on an already timed-out future. That's harmless, but noisy.

**Mitigation:** setup retries are limited to one every 5 minutes per device. While a firmware update runs, the radio check allows five misses instead of two.

**Seen 2026-10-11:** during the remote's firmware update the XStick stopped answering long enough for a restart, and at the next start it didn't even accept API mode (it recovered on the second start).

### 4. The XStick resets itself, and then drops every incoming message

**Seen 2026-10-21:**
- **Earlier that morning,** every device stopped answering while the UI still worked, and the user restarted the Pi. That log is gone (the journal is in RAM).
- **Later that morning,** the same happened at 09:17. The log showed `No 'rx' handler` (a TypeError) for every incoming frame.
- **The cause:** a reset puts the XBee's API options back to AO=0. Frames then arrive as 0x90 `rx`, which zigpy-xbee doesn't handle, instead of 0x91 explicit rx.
- **Why the service didn't recover:** the radio check (`AT AI`) still passed, so it never restarted. A manual service restart fixed it.
- **Resolved 2026-10-21:** the Sonoff replaced the XStick (feature 4). A banner now appears when no device has been heard for 10 minutes, whatever the radio.

**Power:** the Pi reported undervoltage at boot (`vcgencmd get_throttled` = 0x50000). A weak supply can reset USB devices. Use a 5.1 V / 2.5 A supply.

### 5. Laptop Python differs from the Pi

The laptop uses 3.11.0rc1, the Pi 3.13. Recreate the dev venv with `uv` and Python 3.13 when the folder is renamed to `~/my/kotivalo`.

### Fixed

- **The service hung at startup with no Zigbee router powered.** `TolerantPermit`, the database close on failure, and the systemd watchdog fixed it (`9263e24`).
- **The UI showed only the last commanded state.** Lamps now report on/off, level and warmth; polling and Device_annce catch the rest.
- **The wake-up lamp flashed at the next start.** Every off now fades out to warm and minimum before switching off, and "on" restores the last manual setting. A brief warm moment at "on" remains (see feature 5).

---

## Features

### 1. Lamps organised into groups

**Fixtures are done** (2026-10-11): app-level, so each command is sent to every bulb at once. What remains:
- **Native Zigbee groups:** one multicast instead of one command per bulb, so all spots change at exactly the same moment. Test XStick group sending with the TRÅDFRI GU10s.
- **Rooms as groups:** e.g. "all living-room lamps".

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

**Candidates:** both use the Silicon Labs EFR32MG24 chip and ship with Zigbee coordinator firmware (EmberZNet, EZSP). zigpy's `bellows` speaks EZSP and is already installed.
- **Home Assistant Connect ZBT-2:** 460800 baud.
- **Sonoff Dongle Plus MG24** (model Dongle-PMG24, not the older ZBDongle-E): 115200 baud, an external SMA antenna and a USB extension cable. Its firmware is updated with Sonoff's web flasher (dongle.sonoff.tech) from a laptop: update it before forming the network.

**What it would bring:**
- group traffic, so old-firmware remotes would work
- more child slots
- probably no quadruple frames

**Thread:** either radio runs Zigbee *or* Thread; running both at once (MultiPAN) is unreliable. IKEA's new Matter-over-Thread devices would need a second radio and a Matter stack: a separate project.

**The switch-over:**
- The code talks to zigpy's generic API, so swapping is a settings change (radio type, port, baud) plus forming a new network and re-pairing every device (see the README).
- Do it before the AGGE dimmer is installed, so the dimmer is paired only once.

**Progress (2026-10-21):**
- **Bought:** the Sonoff Dongle Plus MG24, plugged into the Pi next to the XStick.
- **Firmware:** EmberZNet 7.4.5, fine as shipped.
- **Network:** formed on channel 25. An energy scan found 25 among the quieter channels. 26 is the busiest, and Wi-Fi channel 6 shows on 17–18.
- **Tested:** a second instance of the service (port 8091, its own state directory) started on it, opened and closed pairing, and stopped cleanly.
- **Switched over 2026-10-21, 21:45–22:37:** all 14 devices re-paired (8 mains, 6 battery; the last E1810 at 22:36, once found), plus a second E1810 and a new SNZB-06P presence sensor; each set up within seconds of joining. The XStick is unplugged.
- **Next:**
  - the E1810 (known issue 1)
  - once the Sonoff has run well for a few days: delete `/home/pi/sonoff-test` (a test state directory) and, later, the XStick's kept files
  - once it has run well for a few weeks: remove the XBee-only code (`xbee_config.py`, `xbee-config`, `_radio_watch`, zigpy-xbee)

### 5. Flash-free switch-on: not possible on this firmware

**Today:**
- Every off fades out over about 0.5 s to minimum, then switches off. The wake-up lamp also turns warm at that dim level first. (Since 2026-10-10; before, lamps jumped to warm and dim.)
- "On" sets the remembered brightness, then the warmth 0.5 s later. That shows as a brief warm moment.

**Tested on panel 2 (firmware 1.2.217) on 2026-10-10, with the lamp off:**
- **Brightness** can't be preset, with or without ExecuteIfOff.
- **Colour temperature** is stored, but by eye the lamp still comes on at its previous warmth, then shifts to the stored one. That's the same as today.

So the current parking is as good as it gets. The only open route is newer FLOALT firmware (IKEA has 2.3.087), if it supports ExecuteIfOff. Lamps must never update automatically (see CLAUDE.md), and updating rules out the dimming patch (feature 8).

### 6. Weather ideas

- The forecast for the next alarm time on the Herätys page ("Aamulla 6.30: 🌧 3°").
- FMI's measured temperature from the nearest station, as "now" in Finland, if yr.no's model value feels off.

### 7. HTTPS on the LAN and an installable app

- A local CA (mkcert) would enable the Wake Lock API, so the wall panel's screen stays on without kiosk apps.
- It would also make the UI installable as an app (PWA).

### 8. A dimmer minimum for the FLOALT panels (investigated 2026-10-22)

**Today:** level 2, the lowest we send, is a 5 % PWM duty: too bright for a night light or the first minutes of a sunrise. Nothing sent over Zigbee changes that.

**What sets it:** at start the panel firmware builds a level table, a geometric curve over 253 steps:
- **Bottom:** 5 % of the PWM period, at level 1.
- **Top:** full, at level 254.
- **PWM:** TIMER1 at 600 Hz (TOP 63999 at 38.4 MHz).

**A published patch:** zw's, for the FLOALT 30x30 (github.com/zw/TRADFRI-Hacking, `hacks/L1527`; trmm.net/Ikea did the same on the TRÅDFRI 10 W driver). It lowers the floor to 32 counts (0.05 %) on firmware 1.2.217, which all our panels run (OTA file version 0x12217572).
- **The change:** 14 bytes. The floor calculation (`ldr`, `adds`, `add.w`, `movs`, `udiv`) becomes five NOPs and `mov.w r0, #32`.
- **Leave out its other change:** it fixes the Step commands' step size at 8, which matters only for IKEA remotes bound straight to the lamp.
- **Which image:** the 60x60 runs IKEA's `driver-hp` image ("FLOALT panel WS 60x60" is compiled into it); the 30x30 runs `driver-lp`.
  - The patch is for lp, with the floor code at 0x92dc. hp has the identical code at 0x92d0.
  - The 30x90 is in neither image's strings, but it asks for the same OTA image type as the 60x60s (0x4202), so it runs the same image.
- **The panels can't be told apart over Zigbee** (read 2026-10-25): all report image type 0x4202, firmware 1.2.217, hardware version 1, app version 17, stack 87 and date code 20170331, which is the firmware's build date, not the panel's. Only the radio's IEEE prefix differs: panel 2 has 00:0b:57, Silicon Labs' oldest; panel 1, Vaatehuone and Eteinen have newer ones. A hardware generation shows only on the driver box itself.
- **Two hardware versions in the home:** panel 1's driver has a mains cord with a standard Euro plug, panel 2's a custom connector. Vaatehuone's is not known yet. The Zigbee module and firmware are the same, so the patch is too, but the LED power stage may behave differently at the lowest duty: test the floor on the panel that gets patched.
- **The floor is our choice:** 32 counts (0.05 %) is what zw and trmm used, and both saw stripes and occasional strobing on the FLOALT at the very lowest levels. 320 (0.5 %) would be a gentler first try.

**Two ways to put it on a panel:**
- **SWD** (zw's way):
  1. Open the driver box. Solder 4 wires (VCC, PF1 = SWDIO, PF0 = SWCLK, GND) to the module.
  2. Dump the 256 KB flash, and check that its code matches IKEA's 1.2.217 image.
  3. Patch it and write back only the changed page. Writing the dump back undoes it.
  - **Needs a probe,** such as a Pi Pico running debugprobe.
  - **If the debug interface is locked, stop:** an erase would lose IKEA's firmware.
- **Over the air** (nobody has published doing this): patch IKEA's 1.2.217 hp image and serve it through zigpy as a one-off update. zigpy strips IKEA's signature wrapper, so the panel sees a plain EBL.
  - **Checksums:** its end CRC is a standard CRC-32 (verified on IKEA's images) and can be recomputed.
  - **Unknown:** whether the bootloader checks the address table's image CRC (not reproduced). zw's SWD-patched panel boots with it stale.
  - **Risk:** a bad image would leave the panel needing SWD to recover, and the FLOALT is discontinued.

**What Kotivalo would need:** a per-lamp flag that remaps UI percentages, motion levels and the sunrise ramp onto the new range. The patched curve makes *every* level below 254 dimmer: stock level 2 equals patched level ~155 (with the floor at 0.05 %).

**Consequence:** a patched panel stays on 1.2.217 for good. IKEA's 2.3.087 rewrote this code, so the patch doesn't carry over to it.

**Decided with the user (2026-10-22), postponed until they have the tools:**
- **First, by cable, on one 60x60** (panel 2). Its debug lock is the one thing that could make an over-the-air failure permanent.
- **If unlocked:** over the air for the other panels. A failed update is fixable by cable: write IKEA's 1.2.217 program back, since the pairing area isn't touched.
- **If locked:** stop, and drop the over-the-air route.
- **Probe:** a Raspberry Pi Pico running Raspberry Pi's debugprobe, or the Kotivalo Pi's GPIO with OpenOCD.
- **When we resume:** write the step-by-step for the chosen probe, and a script that checks the panel's dump against IKEA's image before anything is written.

---

## Hardening (later)

- **Back up the Zigbee network.** Keep a copy of `zigbee.db` (it holds the network key) and `settings.json` off the Pi. Otherwise a dead SD card means re-pairing every device.
- **Read-only root filesystem (overlay FS):** protects the SD card from power cuts.
- **Optional web token** (`web_token` in `settings.json`): enable it if the LAN isn't trusted.
- **Health page:** radio status, last-seen time per device, the last automation's result.
