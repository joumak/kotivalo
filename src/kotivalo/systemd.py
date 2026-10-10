"""Minimal sd_notify: readiness and watchdog pings for a Type=notify unit (no dependency).

Outside systemd (tests, local runs) NOTIFY_SOCKET is unset and everything is a no-op.
"""

from __future__ import annotations

import os
import socket


def notify(message: str) -> bool:
    """Send e.g. "READY=1" or "WATCHDOG=1" to systemd. Returns False outside systemd."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):  # abstract namespace socket
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
    except OSError:
        return False
    return True


def watchdog_interval() -> float | None:
    """Seconds between watchdog pings (half of WatchdogSec), or None if not enabled for us."""
    usec = os.environ.get("WATCHDOG_USEC")
    pid = os.environ.get("WATCHDOG_PID")
    if not usec or (pid and int(pid) != os.getpid()):
        return None
    return int(usec) / 1_000_000 / 2
