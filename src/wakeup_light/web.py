"""aiohttp JSON API and static files for the phone UI."""

from __future__ import annotations

import hmac
import logging
from pathlib import Path

from aiohttp import web

from wakeup_light.light import LightError
from wakeup_light.settings import SettingsError

LOGGER = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SERVICE = web.AppKey("service", object)


@web.middleware
async def guard(request: web.Request, handler):
    """JSON-only writes (a cross-site form can't send them without a CORS preflight,
    which we never grant), plus the optional token."""
    service = request.app[SERVICE]
    if request.method in ("POST", "PUT") and request.content_type != "application/json":
        return web.json_response({"error": "Content-Type must be application/json"}, status=415)
    token = service.settings.web_token
    if token and request.path.startswith("/api/"):
        given = request.headers.get("X-Token", "")
        if not hmac.compare_digest(given, token):
            return web.json_response({"error": "token required"}, status=401)
    return await handler(request)


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


def ok(request: web.Request) -> web.Response:
    return web.json_response(request.app[SERVICE].snapshot())


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def get_state(request: web.Request) -> web.Response:
    return ok(request)


async def put_alarms(request: web.Request) -> web.Response:
    body = await request.json()
    request.app[SERVICE].update_alarms(body["alarms"])
    return ok(request)


async def put_ramp(request: web.Request) -> web.Response:
    request.app[SERVICE].update_ramp(await request.json())
    return ok(request)


async def post_light(request: web.Request) -> web.Response:
    body = await request.json()
    await request.app[SERVICE].light_action(body["action"], body.get("value"))
    return ok(request)


async def post_refresh(request: web.Request) -> web.Response:
    await request.app[SERVICE].refresh_light()
    return ok(request)


async def post_test(request: web.Request) -> web.Response:
    body = await request.json()
    await request.app[SERVICE].test_sunrise(float(body["minutes"]))
    return ok(request)


async def post_stop(request: web.Request) -> web.Response:
    await request.app[SERVICE].stop_sunrise("stopped from the web UI")
    return ok(request)


async def post_skip(request: web.Request) -> web.Response:
    body = await request.json()
    request.app[SERVICE].set_skip(str(body["key"]), bool(body["skip"]))
    return ok(request)


async def post_permit(request: web.Request) -> web.Response:
    body = await request.json()
    await request.app[SERVICE].permit(int(body.get("seconds", 254)))
    return ok(request)


async def post_target(request: web.Request) -> web.Response:
    body = await request.json()
    await request.app[SERVICE].select_light(str(body["ieee"]))
    return ok(request)


def make_web_app(service) -> web.Application:
    app = web.Application(middlewares=[errors, guard])
    app[SERVICE] = service
    app.router.add_get("/", index)
    app.router.add_get("/api/state", get_state)
    app.router.add_put("/api/alarms", put_alarms)
    app.router.add_put("/api/ramp", put_ramp)
    app.router.add_post("/api/light", post_light)
    app.router.add_post("/api/refresh", post_refresh)
    app.router.add_post("/api/sunrise/test", post_test)
    app.router.add_post("/api/sunrise/stop", post_stop)
    app.router.add_post("/api/skip", post_skip)
    app.router.add_post("/api/permit", post_permit)
    app.router.add_post("/api/target", post_target)
    app.router.add_static("/static/", STATIC_DIR)
    return app
