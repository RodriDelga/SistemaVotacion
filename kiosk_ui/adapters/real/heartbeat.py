"""Reporte de disponibilidad del kiosco y sus periféricos para el dashboard."""
from __future__ import annotations

import errno
import logging
import os
import struct
import sys
import threading
import time

from kiosk_ui.adapters.real.api_client import ApiError, VotingApi
from kiosk_ui.adapters.real.nfc import NfcCardReader

log = logging.getLogger(__name__)

# ABI de V4L2 en Raspberry Pi. Los dos campos son capabilities y device_caps.
_VIDIOC_QUERYCAP = 0x80685600
_V4L2_CAPABILITY = struct.Struct("=84xII12x")
_V4L2_CAP_DEVICE_CAPS = 0x80000000
_V4L2_VIDEO_CAPTURE = 0x00000001 | 0x00001000  # VIDEO_CAPTURE y VIDEO_CAPTURE_MPLANE


def probe_camera() -> bool | None:
    """Consulta el nodo de captura configurado sin iniciar el flujo de video."""
    if sys.platform != "linux":
        return None
    import fcntl

    try:
        index = int(os.getenv("CAMERA_INDEX", "0"))
        fd = os.open(f"/dev/video{index}", os.O_RDWR | os.O_NONBLOCK)
        try:
            result = fcntl.ioctl(fd, _VIDIOC_QUERYCAP, bytes(_V4L2_CAPABILITY.size))
        finally:
            os.close(fd)
    except OSError as exc:
        return None if exc.errno == errno.EBUSY else False
    except ValueError:
        return False

    capabilities, device_caps = _V4L2_CAPABILITY.unpack(result)
    if capabilities & _V4L2_CAP_DEVICE_CAPS:
        capabilities = device_caps
    return bool(capabilities & _V4L2_VIDEO_CAPTURE)


def run_heartbeat(stop: threading.Event, *, nfc: NfcCardReader) -> None:
    # Sesión propia: este hilo no comparte el cliente HTTP del flujo de votación.
    api = VotingApi()
    try:
        ttl = int(os.getenv("DASHBOARD_HEARTBEAT_TTL_SECONDS", "45"))
    except ValueError:
        ttl = 45
    interval = min(15.0, max(1.0, ttl / 3))
    try:
        while not stop.is_set():
            next_report = time.monotonic() + interval
            components = {}
            for component, available in (("camera", probe_camera()), ("nfc", nfc.probe_health())):
                if available is not None:
                    components[component] = "online" if available else "offline"
            if stop.is_set():
                break

            try:
                api.report_heartbeat(components)
            except ApiError as exc:
                if exc.status_code is None:
                    log.warning("No se pudo comunicar con el backend para enviar el latido de la urna.")
                else:
                    log.warning("El backend rechazó el latido de la urna (HTTP %s).", exc.status_code)

            if stop.wait(max(0, next_report - time.monotonic())):
                break
    finally:
        api.close()
