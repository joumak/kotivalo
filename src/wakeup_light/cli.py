"""Command line: the web service plus radio setup and debugging commands."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from wakeup_light import xbee_config
from wakeup_light.light import LightError
from wakeup_light.settings import SettingsError, Store

DEFAULT_STATE_DIR = Path("/var/lib/wakeup-light")
EXIT_CONFIG = 78  # systemd unit does not restart on this

AI_MEANING = {0x00: "network formed/joined", 0xFF: "scanning/starting", 0x21: "scan found no PAN"}


def default_state_dir() -> Path:
    if env := os.environ.get("WAKEUP_LIGHT_STATE_DIR"):
        return Path(env)
    if DEFAULT_STATE_DIR.is_dir() and os.access(DEFAULT_STATE_DIR, os.W_OK):
        return DEFAULT_STATE_DIR
    return Path("var")


def say(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


# --- radio setup -----------------------------------------------------------------


def cmd_xbee_config(args, store: Store) -> None:
    from wakeup_light.zigbee import radio_lock

    settings = store.load_settings()
    with radio_lock(store.lock_path):
        rate = xbee_config.configure_for_zigpy(settings.radio.path, log=say)
    if settings.radio.baudrate != rate:
        settings.radio.baudrate = rate
        store.save_settings(settings)
        say(f"Saved baudrate {rate} to settings")


def cmd_radio_info(args, store: Store) -> None:
    from wakeup_light.zigbee import radio_lock

    radio = store.load_settings().radio
    with radio_lock(store.lock_path):
        info = xbee_config.read_info(radio.path, radio.baudrate)
        if all(r is None for r in info.values()):
            rate = xbee_config.find_baudrate(radio.path)
            if rate is None:
                sys.exit(f"No answer from {radio.path} at any common baud rate")
            say(f"No answer at configured {radio.baudrate} baud; XBee answers at {rate}")
            info = xbee_config.read_info(radio.path, rate)
    for cmd, rsp in info.items():
        if rsp is None:
            text = "(no answer)"
        elif not rsp.ok:
            text = f"(status {rsp.status})"
        else:
            value = rsp.as_int()
            text = f"{rsp.value.hex().upper() or '-'}"
            if cmd == "BD":
                text += f"  = {xbee_config.BD_RATES.get(value, '?')} baud"
            elif cmd == "AI":
                text += f"  = {AI_MEANING.get(value, 'see XBee manual')}"
            elif cmd in ("CH", "AP", "ZS", "EE", "EO", "NJ", "PL"):
                text += f"  = {value}"
        print(f"  {cmd}  {text}")


def cmd_form_network(args, store: Store) -> None:
    settings = store.load_settings()
    channel = args.channel or settings.radio.channel
    if not args.yes:
        answer = input(
            f"Form a NEW Zigbee network on channel {channel}? Paired devices must be "
            "re-paired afterwards. Type 'yes': "
        )
        if answer.strip().lower() != "yes":
            sys.exit("Cancelled")
    settings.radio.channel = channel
    store.save_settings(settings)
    asyncio.run(_form_network(settings, store))


async def _form_network(settings, store: Store) -> None:
    from wakeup_light.zigbee import controller_class, radio_lock, zigpy_config

    with radio_lock(store.lock_path):
        cls = controller_class(settings.radio.type)
        app = await cls.new(zigpy_config(settings.radio, store.db_path), start_radio=False)
        try:
            await app.connect()
            say(f"Forming network on channel {settings.radio.channel} ...")
            await app.form_network()
            await app.load_network_info()
            net = app.state.network_info
            say(
                f"Formed: channel {net.channel}, PAN 0x{net.pan_id:04X}, "
                f"extended PAN {net.extended_pan_id}"
            )
        finally:
            await app.shutdown()


# --- devices and pairing -----------------------------------------------------------


def cmd_devices(args, store: Store) -> None:
    asyncio.run(_devices(store))


async def _devices(store: Store) -> None:
    from wakeup_light.zigbee import devices, radio_lock, start_app

    settings = store.load_settings()
    with radio_lock(store.lock_path):
        app = await start_app(settings.radio, store.db_path, start_radio=False)
        try:
            found = devices(app)
        finally:
            await app.shutdown()
    if not found:
        print("No devices paired.")
    for d in found:
        mark = "*" if d["ieee"] == settings.target_ieee else " "
        seen = datetime.fromtimestamp(d["last_seen"]).strftime("%F %T") if d["last_seen"] else "-"
        print(
            f"{mark} {d['ieee']}  {d['nwk']}  {d['manufacturer']} / {d['model']}  "
            f"light={d['is_light']} initialized={d['initialized']} last_seen={seen}"
        )


def cmd_pair(args, store: Store) -> None:
    asyncio.run(_pair(args, store))


async def _pair(args, store: Store) -> None:
    from wakeup_light.zigbee import DeviceEvents, ZigbeeLight, light_endpoint, radio_lock, start_app

    settings = store.load_settings()
    lights = []
    lost = asyncio.Event()

    def on_event(kind, obj):
        if kind == "connection_lost":
            if obj is not None:  # None = our own clean shutdown
                say(f"Radio connection lost: {obj!r}")
                lost.set()
            return
        say(f"{kind}: {obj.ieee} nwk=0x{obj.nwk:04X} {obj.manufacturer} / {obj.model}")
        if kind == "initialized" and light_endpoint(obj) is not None:
            lights.append((time.monotonic(), obj))

    with radio_lock(store.lock_path):
        app = await start_app(settings.radio, store.db_path)
        app.add_listener(DeviceEvents(on_event))
        try:
            await app.permit(time_s=args.seconds)
            say(
                f"Pairing open for {args.seconds} s. Reset the FLOALT now: with it ON, "
                "switch it off and on 6 times (about 1 s each) and leave it on."
            )
            deadline = time.monotonic() + args.seconds
            while not lost.is_set():
                now = time.monotonic()
                if lights and now - lights[-1][0] >= args.watch:
                    break  # watched the new light long enough for a quick leave
                if not lights and now >= deadline:
                    say("No light joined.")
                    break
                await asyncio.sleep(1)
            await app.permit(time_s=0)

            for _, device in lights:
                if device.ieee not in app.devices:
                    say(f"{device.ieee} left again: the network did not keep it.")
                    continue
                light = ZigbeeLight(app, str(device.ieee))
                caps = await light.read_caps()
                await light.restore_after_power_loss()
                say(f"Light {device.ieee}: {caps}")
                if settings.target_ieee in (None, str(device.ieee)) or args.select:
                    settings.target_ieee = str(device.ieee)
                    settings.caps = caps
                    store.save_settings(settings)
                    say("Selected as the alarm light.")
        finally:
            await app.shutdown()


def cmd_light(args, store: Store) -> None:
    asyncio.run(_light(args, store))


async def _light(args, store: Store) -> None:
    from wakeup_light.ramp import kelvin_to_mired
    from wakeup_light.zigbee import ZigbeeLight, radio_lock, start_app

    settings = store.load_settings()
    ieee = args.ieee or settings.target_ieee
    if not ieee:
        sys.exit("No light selected: run 'wakeup-light pair' first, or pass --ieee")
    with radio_lock(store.lock_path):
        app = await start_app(settings.radio, store.db_path)
        try:
            light = ZigbeeLight(app, ieee)
            match args.action:
                case "on":
                    await light.on()
                case "off":
                    await light.off()
                case "level":
                    await light.set_level(args.value, args.transition)
                case "ct":
                    await light.set_ct(kelvin_to_mired(args.value))
                case "state":
                    print(await light.read_state())
                case "caps":
                    print(await light.read_caps())
            say("OK")
        finally:
            await app.shutdown()


# --- service ---------------------------------------------------------------------


def cmd_serve(args, store: Store) -> None:
    from wakeup_light.app import serve

    code = asyncio.run(serve(store, host=args.host, port=args.port, fake=args.fake))
    leftover = [t.name for t in threading.enumerate() if t is not threading.main_thread()]
    if leftover:  # diagnostics: these could keep the process from exiting
        logging.getLogger(__name__).warning("Threads still running at exit: %s", leftover)
    sys.exit(code)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wakeup-light", description=__doc__)
    parser.add_argument(
        "--state-dir", type=Path, default=None, help="settings, state and zigbee.db"
    )
    parser.add_argument("--debug", action="store_true", help="verbose logging (incl. zigpy)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the alarm service and web UI")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--fake", action="store_true", help="use an in-memory light, no radio")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("xbee-config", help="one-time: set the XBee to AP=2 and 57600 baud")
    p.set_defaults(func=cmd_xbee_config)

    p = sub.add_parser("radio-info", help="show XBee parameters (raw, read-only)")
    p.set_defaults(func=cmd_radio_info)

    p = sub.add_parser("form-network", help="one-time: create the Zigbee network")
    p.add_argument("--channel", type=int, choices=range(11, 27), metavar="11-26")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.set_defaults(func=cmd_form_network)

    p = sub.add_parser("pair", help="open the network for joining and set up the new light")
    p.add_argument("--seconds", type=int, default=254, choices=range(1, 255), metavar="1-254")
    p.add_argument("--watch", type=int, default=120, help="seconds to watch a new light")
    p.add_argument("--select", action="store_true", help="make the new light the alarm light")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("devices", help="list paired devices (* = alarm light)")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("light", help="control the light directly (service must be stopped)")
    p.add_argument("action", choices=["on", "off", "level", "ct", "state", "caps"])
    p.add_argument("value", type=int, nargs="?", help="level 2-254, or ct in kelvin")
    p.add_argument("--transition", type=float, default=0, help="seconds (level only)")
    p.add_argument("--ieee", help="device to control instead of the selected light")
    p.set_defaults(func=cmd_light)

    args = parser.parse_args(argv)
    if args.command == "light" and args.action in ("level", "ct") and args.value is None:
        parser.error(f"light {args.action} needs a value")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.debug:
        for noisy in ("zigpy", "zigpy_xbee", "bellows", "zigpy_znp", "aiohttp.access"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    store = Store(args.state_dir or default_state_dir())
    try:
        args.func(args, store)
    except SettingsError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except (xbee_config.XBeeError, LightError) as exc:
        sys.exit(f"Error: {exc}")
    except Exception as exc:
        from wakeup_light.zigbee import RadioError

        if isinstance(exc, RadioError):
            sys.exit(f"Radio error: {exc}")
        raise
