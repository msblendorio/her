"""Desktop launcher for Her.app.

Wraps the FastAPI/uvicorn server in a native macOS window via pywebview so
the user gets a real Dock-icon app instead of a terminal + browser tab.

Responsibilities, in order:

1. Pick a writable working directory under ``~/Library/Application Support/Her``
   and ``chdir`` there so relative paths in ``config.py``
   (``data/memory.jsonl`` etc.) end up under user data, not inside the
   read-only ``.app`` bundle.
2. Seed ``.env`` on first launch: if missing, ask the user for an
   OpenAI API key via a tiny pywebview dialog and persist it.
3. Force ``HOST=127.0.0.1`` — the LAN-bind default in ``run.sh`` makes no
   sense for a packaged app and would expose the server to anyone on the
   Wi-Fi.
4. Start uvicorn in a background thread, wait for it to accept
   connections, then open a pywebview window pointing at ``/``.
5. On window close, stop the server cleanly and exit.
"""
from __future__ import annotations

# ── SSL bootstrap (MUST run before any module that touches sockets) ───
# The bundled Python.framework ships without configured root CAs, so any
# outbound TLS handshake (OpenAI WebSocket, HF model downloads) fails
# with "unable to get local issuer certificate" unless we point the
# default SSL context at certifi's bundle. Setting these env vars before
# `import ssl` happens anywhere in the process is the safest order.
import os as _os
try:
    import certifi as _certifi
    _os.environ["SSL_CERT_FILE"] = _certifi.where()
    _os.environ["REQUESTS_CA_BUNDLE"] = _certifi.where()
except ImportError:
    pass

import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path


APP_NAME = "Her"
APP_PORT = 8765
APP_HOST = "127.0.0.1"

LOG = logging.getLogger("her.desktop")


def _app_support_dir() -> Path:
    base = Path.home() / "Library" / "Application Support" / APP_NAME
    (base / "data").mkdir(parents=True, exist_ok=True)
    return base


def _ensure_env(workdir: Path) -> Path:
    """Return path to a usable .env, creating an empty stub if needed."""
    env_path = workdir / ".env"
    if env_path.exists():
        return env_path
    env_path.write_text(
        "# Created by Her.app on first launch.\n"
        "# Get an OpenAI key at https://platform.openai.com/api-keys\n"
        "OPENAI_API_KEY=\n"
        "HOST=127.0.0.1\n"
        "PORT=8765\n",
        encoding="utf-8",
    )
    return env_path


def _api_key_present(env_path: Path) -> bool:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return bool(line.split("=", 1)[1].strip())
    return False


def _write_api_key(env_path: Path, key: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith("OPENAI_API_KEY="):
            lines[i] = f"OPENAI_API_KEY={key}"
            replaced = True
            break
    if not replaced:
        lines.append(f"OPENAI_API_KEY={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prompt_for_api_key(env_path: Path) -> bool:
    """Show a minimal pywebview window asking for the OpenAI key.

    Returns True if the user supplied one, False if they cancelled.
    """
    import webview  # local import: heavy, only needed on first run

    html = """<!doctype html>
<html><head><meta charset="utf-8"><title>Her — Setup</title>
<style>
 body{font:14px -apple-system,system-ui;margin:24px;background:#111;color:#eee}
 h2{margin:0 0 8px;font-weight:600}
 p{color:#aaa;margin:0 0 16px;line-height:1.4}
 input{width:100%;box-sizing:border-box;padding:10px;font:13px ui-monospace,monospace;
       background:#222;color:#eee;border:1px solid #333;border-radius:6px}
 .row{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
 button{padding:8px 16px;border-radius:6px;border:0;cursor:pointer;font-weight:500}
 .ok{background:#4f8cff;color:#fff}
 .skip{background:#333;color:#aaa}
 a{color:#4f8cff}
</style></head><body>
<h2>Welcome to Her</h2>
<p>Paste your OpenAI API key to enable the Realtime voice session.
You can get one at <a href="#" onclick="pywebview.api.open_keys()">platform.openai.com/api-keys</a>.
The key stays on this Mac.</p>
<input id="k" type="password" placeholder="sk-..." autofocus>
<div class="row">
 <button class="skip" onclick="pywebview.api.cancel()">Later</button>
 <button class="ok" onclick="pywebview.api.save(document.getElementById('k').value)">Save</button>
</div>
<script>
 document.getElementById('k').addEventListener('keydown', e => {
   if (e.key === 'Enter') pywebview.api.save(e.target.value);
 });
</script>
</body></html>"""

    state = {"saved": False}

    class Api:
        def save(self, value: str) -> None:
            value = (value or "").strip()
            if not value:
                return
            _write_api_key(env_path, value)
            state["saved"] = True
            webview.windows[0].destroy()

        def cancel(self) -> None:
            webview.windows[0].destroy()

        def open_keys(self) -> None:
            import webbrowser
            webbrowser.open("https://platform.openai.com/api-keys")

    webview.create_window(
        title="Her — Setup",
        html=html,
        width=480,
        height=260,
        resizable=False,
        js_api=Api(),
    )
    webview.start()
    return state["saved"]


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def _run_server() -> None:
    # Imported lazily so the setup window can appear without paying the
    # uvicorn/torch import cost upfront.
    from her.main import main as her_main
    her_main()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )

    workdir = _app_support_dir()
    os.chdir(workdir)
    LOG.info("Working dir: %s", workdir)

    env_path = _ensure_env(workdir)
    if not _api_key_present(env_path):
        LOG.info("No OPENAI_API_KEY found, prompting user…")
        if not _prompt_for_api_key(env_path):
            LOG.warning("User declined to provide an API key; exiting.")
            sys.exit(0)

    # Force loopback bind regardless of what .env says — a packaged app
    # shouldn't expose itself to the LAN by accident.
    os.environ["HOST"] = APP_HOST
    os.environ["PORT"] = str(APP_PORT)

    server_thread = threading.Thread(target=_run_server, daemon=True, name="her-server")
    server_thread.start()

    if not _wait_for_port(APP_HOST, APP_PORT, timeout=30.0):
        LOG.error("Server did not start within 30s; exiting.")
        sys.exit(1)

    import webview  # heavy; import after server bootstrap
    webview.create_window(
        title="Her",
        url=f"http://{APP_HOST}:{APP_PORT}/",
        width=1100,
        height=780,
        min_size=(800, 600),
    )
    webview.start()
    # webview.start() blocks until the last window closes.
    LOG.info("Window closed; exiting.")
    os._exit(0)


if __name__ == "__main__":
    main()
