"""aiohttp JSON API, the live-update stream and the static UI."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from kotivalo.light import LightError
from kotivalo.settings import SettingsError

LOGGER = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SERVICE = web.AppKey("service", object)
SSE_DEBOUNCE_S = 0.2  # at most ~5 updates per second per client
SSE_KEEPALIVE_S = 15


@web.middleware
async def guard(request: web.Request, handler):
    """JSON-only writes (a cross-site form can't send them without a CORS preflight,
    which we never grant), plus the optional token. EventSource cannot send headers,
    so the token may also come as ?token=."""
    service = request.app[SERVICE]
    if request.method in ("POST", "PUT") and request.content_type != "application/json":
        return web.json_response({"error": "Content-Type must be application/json"}, status=415)
    token = service.settings.web_token
    if token and request.path.startswith("/api/"):
        given = request.headers.get("X-Token") or request.query.get("token", "")
        if not hmac.compare_digest(given, token):
            return web.json_response({"error": "token required"}, status=401)
    response = await handler(request)
    if request.method in ("POST", "PUT", "DELETE"):
        service.notify()  # push the change to every open page
    return response


@web.middleware
async def errors(request: web.Request, handler):
    try:
        return await handler(request)
    except (SettingsError, ValueError, KeyError, TypeError) as exc:
        return web.json_response({"error": f"Bad request: {exc}"}, status=400)
    except LightError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except RuntimeError as exc:
        return web.json_response({"error": str(exc)}, status=409)


def service_of(request: web.Request):
    return request.app[SERVICE]


def ok(request: web.Request) -> web.Response:
    return web.json_response(service_of(request).snapshot())


async def index(request: web.Request) -> web.StreamResponse:
    page = STATIC_DIR / "index.html"
    if not page.exists():
        return web.Response(status=503, text="The UI is not built: run `npm run build` in web/.")
    return web.FileResponse(page, headers={"Cache-Control": "no-cache"})


async def get_state(request: web.Request) -> web.Response:
    return ok(request)


async def events(request: web.Request) -> web.StreamResponse:
    """Server-Sent Events: the full state now, then again whenever it changes."""
    service = service_of(request)
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
    await response.prepare(request)

    async def send_state() -> None:
        await response.write(f"data: {json.dumps(service.snapshot())}\n\n".encode())

    # A viewer gone without closing (a phone asleep: the TCP connection times out) shows
    # up as a ConnectionError on the next write. The stream just ends.
    with contextlib.suppress(ConnectionError, asyncio.CancelledError):
        await send_state()
        while not service.stopped.is_set():
            if await service.wait_change(SSE_KEEPALIVE_S):
                await asyncio.sleep(SSE_DEBOUNCE_S)  # let a burst of changes settle
                if service.stopped.is_set():
                    break
                await send_state()
            else:
                await response.write(b": keepalive\n\n")
    return response


# --- lamps and devices ----------------------------------------------------------------


async def post_lamp(request: web.Request) -> web.Response:
    body = await request.json()
    ieee = request.match_info["ieee"]
    await service_of(request).lamp_action(ieee, body["action"], body.get("value"))
    return ok(request)


async def post_fixture(request: web.Request) -> web.Response:
    service_of(request).create_fixture(await request.json())
    return ok(request)


async def put_fixture(request: web.Request) -> web.Response:
    service_of(request).update_fixture(request.match_info["ieee"], await request.json())
    return ok(request)


async def post_master(request: web.Request) -> web.Response:
    body = await request.json()
    await service_of(request).master_switch(str(body.get("action", "")), body.get("delay", 0))
    return ok(request)


async def post_lamp_refresh(request: web.Request) -> web.Response:
    await service_of(request).refresh_lamp(request.match_info["ieee"])
    return ok(request)


async def put_device(request: web.Request) -> web.Response:
    service_of(request).update_device(request.match_info["ieee"], await request.json())
    return ok(request)


async def delete_device(request: web.Request) -> web.Response:
    await service_of(request).remove_device(request.match_info["ieee"])
    return ok(request)


async def put_wakeup(request: web.Request) -> web.Response:
    await service_of(request).update_wakeup(await request.json())
    return ok(request)


async def put_motion(request: web.Request) -> web.Response:
    service_of(request).update_motion(request.match_info["ieee"], await request.json())
    return ok(request)


async def delete_motion(request: web.Request) -> web.Response:
    service_of(request).remove_motion(request.match_info["ieee"])
    return ok(request)


async def put_remote(request: web.Request) -> web.Response:
    service_of(request).update_remote(request.match_info["ieee"], await request.json())
    return ok(request)


async def delete_remote(request: web.Request) -> web.Response:
    service_of(request).remove_remote(request.match_info["ieee"])
    return ok(request)


async def post_firmware(request: web.Request) -> web.Response:
    service_of(request).start_firmware_update(request.match_info["ieee"])
    return ok(request)


async def put_weather(request: web.Request) -> web.Response:
    service_of(request).update_weather(await request.json())
    return ok(request)


async def get_places(request: web.Request) -> web.Response:
    query = request.query.get("q", "")
    language = request.query.get("lang", "fi")
    try:
        places = await service_of(request).search_places(query, language)
    except (aiohttp.ClientError, TimeoutError) as exc:
        return web.json_response({"error": f"Place search failed: {exc!r}"}, status=502)
    return web.json_response({"places": places})


async def put_night(request: web.Request) -> web.Response:
    service_of(request).update_night(await request.json())
    return ok(request)


async def put_daylight(request: web.Request) -> web.Response:
    service_of(request).update_daylight(await request.json())
    return ok(request)


# --- wake-up, pairing ---------------------------------------------------------------


async def post_test(request: web.Request) -> web.Response:
    body = await request.json()
    await service_of(request).test_sunrise(float(body["minutes"]))
    return ok(request)


async def post_stop(request: web.Request) -> web.Response:
    await service_of(request).stop_sunrise("stopped from the web UI")
    return ok(request)


async def post_skip(request: web.Request) -> web.Response:
    body = await request.json()
    service_of(request).set_skip(str(body["key"]), bool(body["skip"]))
    return ok(request)


async def post_permit(request: web.Request) -> web.Response:
    body = await request.json()
    await service_of(request).permit(int(body.get("seconds", 254)))
    return ok(request)


async def post_fake_event(request: web.Request) -> web.Response:
    """`serve --fake` only: inject a sensor event, for UI development and tests."""
    from kotivalo.events import Battery, Brightness, Button, Lux, Motion

    body = await request.json()
    ieee, value = str(body["ieee"]), body["value"]
    make = {
        "motion": lambda: Motion(ieee, bool(value)),
        "lux": lambda: Lux(ieee, float(value)),
        "bright": lambda: Brightness(ieee, bool(value)),
        "battery": lambda: Battery(ieee, float(value)),
        "button": lambda: Button(ieee, str(value)),
    }
    service_of(request).events.put_nowait(make[body["type"]]())
    await asyncio.sleep(0.2)  # let it be handled before answering
    return ok(request)


def make_web_app(service) -> web.Application:
    app = web.Application(middlewares=[errors, guard])
    app[SERVICE] = service
    router = app.router
    router.add_get("/", index)
    router.add_get("/api/state", get_state)
    router.add_get("/api/events", events)
    router.add_post("/api/lights/{ieee}", post_lamp)
    router.add_post("/api/lights/{ieee}/refresh", post_lamp_refresh)
    router.add_post("/api/master", post_master)
    router.add_post("/api/fixtures", post_fixture)
    router.add_put("/api/fixtures/{ieee}", put_fixture)
    router.add_put("/api/devices/{ieee}", put_device)
    router.add_delete("/api/devices/{ieee}", delete_device)
    router.add_put("/api/wakeup", put_wakeup)
    router.add_put("/api/night", put_night)
    router.add_put("/api/daylight", put_daylight)
    router.add_put("/api/motion/{ieee}", put_motion)
    router.add_delete("/api/motion/{ieee}", delete_motion)
    router.add_put("/api/remotes/{ieee}", put_remote)
    router.add_delete("/api/remotes/{ieee}", delete_remote)
    router.add_post("/api/remotes/{ieee}/firmware", post_firmware)
    router.add_put("/api/weather", put_weather)
    router.add_get("/api/weather/places", get_places)
    router.add_post("/api/sunrise/test", post_test)
    router.add_post("/api/sunrise/stop", post_stop)
    router.add_post("/api/skip", post_skip)
    router.add_post("/api/permit", post_permit)
    if service.fake:
        router.add_post("/api/fake/event", post_fake_event)
    router.add_static("/static/", STATIC_DIR)
    return app
