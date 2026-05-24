"""Entry point: `python -m her.main` or the console script `her`."""
from __future__ import annotations

import logging
import os

# Point Python's default SSL context at certifi's CA bundle. Required on macOS
# when running under a python.org Python (Python.framework), which ships
# without configured root certificates and would otherwise fail the TLS
# handshake against api.openai.com with "unable to get local issuer
# certificate". Harmless on systems already configured correctly.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import socket  # noqa: E402

import uvicorn  # noqa: E402

from .config import settings  # noqa: E402


def _detect_lan_ip() -> str | None:
    """Best-effort LAN IP of the active interface.

    Opens a UDP socket toward a public address — no packets are sent, but the
    kernel picks the right source interface, which is what we want to print
    to the user. Returns None on hosts without outbound connectivity.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not settings.openai_api_key:
        logging.warning("OPENAI_API_KEY is not set — the Realtime session will refuse to start.")

    log = logging.getLogger("her.startup")
    log.info("Local:   http://127.0.0.1:%d", settings.port)
    if settings.host not in ("127.0.0.1", "localhost"):
        lan_ip = _detect_lan_ip()
        if lan_ip and lan_ip != "127.0.0.1":
            log.info("Network: http://%s:%d  (same Wi-Fi)", lan_ip, settings.port)
            log.info("Phones need HTTPS for mic/webcam — see README 'Accessing from another device'.")
        else:
            log.info("Network: bound to %s but no LAN interface detected.", settings.host)

    uvicorn.run(
        "her.server.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
