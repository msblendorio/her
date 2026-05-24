"""Thin async wrappers around the macOS CLI tools.

We deliberately avoid `shell=True`. All values that came from a model are
passed as explicit argv entries to keep injection surface minimal.

Tools defined here are auto-registered via the :func:`tool` decorator from
:mod:`her.agentic.registry`. To add a new macOS tool, drop an ``@tool()``
async function below.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path
from time import strftime

from .registry import tool

log = logging.getLogger(__name__)


class MacOSError(RuntimeError):
    pass


async def _run(argv: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    log.debug("run: %s", argv)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise MacOSError(f"command timed out: {shlex.join(argv)}")
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


@tool()
async def open_app(name: str) -> str:
    """Open a macOS application by name. Use the EXACT name as it appears in
    /Applications — e.g. 'Google Chrome' (NOT 'Chrome'), 'Visual Studio Code'
    (NOT 'VS Code'), 'Microsoft Word' (NOT 'Word'). This only launches/focuses
    the app — to open a new tab in a browser use `browser_new_tab` instead.

    Args:
        name: Exact application name as shown in /Applications.
    """
    code, _, err = await _run(["open", "-a", name])
    if code != 0:
        raise MacOSError(err.strip() or f"could not open app: {name}")
    return f"opened: {name}"


@tool()
async def open_url(url: str) -> str:
    """Open a web URL in the user's default browser. Only http(s) URLs are accepted.

    Args:
        url: Full URL starting with http:// or https://.
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        raise MacOSError("only http(s) URLs are allowed")
    code, _, err = await _run(["open", url])
    if code != 0:
        raise MacOSError(err.strip() or f"could not open url: {url}")
    return f"opened: {url}"


@tool()
async def focus_window(app: str) -> str:
    """Bring an already-running macOS app to the foreground. Use the EXACT app
    name as in /Applications — e.g. 'Google Chrome', NOT 'Chrome'. If the
    wrong name is used, AppleScript hangs until timeout.

    Args:
        app: Exact application name to focus.
    """
    script = f'tell application "{app}" to activate'
    code, _, err = await _run(["osascript", "-e", script])
    if code != 0:
        raise MacOSError(err.strip() or f"could not focus: {app}")
    return f"focused: {app}"


@tool()
async def list_running_apps() -> list[str]:
    """List the names of foreground macOS applications currently running."""
    script = 'tell application "System Events" to get name of (every process whose background only is false)'
    code, out, err = await _run(["osascript", "-e", script])
    if code != 0:
        raise MacOSError(err.strip() or "could not list apps")
    return [a.strip() for a in out.replace("\n", "").split(",") if a.strip()]


@tool()
async def take_screenshot() -> str:
    """Capture the full screen and save the PNG to the user's Desktop. Returns the file path."""
    fname = f"her_screenshot_{strftime('%Y%m%d-%H%M%S')}.png"
    path = Path.home() / "Desktop" / fname
    code, _, err = await _run(["screencapture", "-x", str(path)])
    if code != 0:
        raise MacOSError(err.strip() or "screencapture failed")
    return str(path)


@tool(params={"level": {"minimum": 0, "maximum": 100}})
async def set_volume(level: int) -> str:
    """Set the macOS system output volume (0 mutes, 100 is max). Use sparingly.

    Args:
        level: Volume 0-100.
    """
    level = max(0, min(100, int(level)))
    script = f"set volume output volume {level}"
    code, _, err = await _run(["osascript", "-e", script])
    if code != 0:
        raise MacOSError(err.strip() or "could not set volume")
    return f"volume set to {level}"


@tool()
async def run_shortcut(name: str) -> str:
    """Run a macOS Shortcut by name (from the user's Shortcuts.app library).
    Powerful but only runs shortcuts the user has explicitly created.
    Ask the user for confirmation before invoking any non-trivial shortcut.

    Args:
        name: Exact shortcut name as listed in Shortcuts.app.
    """
    code, out, err = await _run(["shortcuts", "run", name], timeout=60.0)
    if code != 0:
        raise MacOSError(err.strip() or f"shortcut failed: {name}")
    return out.strip() or f"shortcut '{name}' done"


# Browsers we know how to drive via AppleScript. Other names fall back to the
# generic `open -a "<browser>" <url>` path, which works for any registered
# URL handler but cannot open an empty tab.
_SCRIPTABLE_BROWSERS = {"Google Chrome", "Safari", "Microsoft Edge", "Brave Browser", "Arc"}


def _escape_applescript(s: str) -> str:
    """Escape a Python string for use inside AppleScript double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# AppleScript "key code" map for named keys. Only the common ones — anything
# else can be sent as a single-character keystroke.
_KEY_CODES: dict[str, int] = {
    "return": 36, "enter": 36,
    "tab": 48,
    "space": 49,
    "delete": 51, "backspace": 51,
    "forwarddelete": 117, "fwddelete": 117, "del": 117,
    "escape": 53, "esc": 53,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

_MODIFIERS: dict[str, str] = {
    "cmd": "command down", "command": "command down", "meta": "command down",
    "ctrl": "control down", "control": "control down",
    "alt": "option down", "opt": "option down", "option": "option down",
    "shift": "shift down",
}


def _accessibility_hint(stderr: str) -> str:
    s = (stderr or "").lower()
    if "not allowed assistive access" in s or "1002" in s or "system events got an error" in s:
        return (
            " — grant Accessibility to the parent process in System Settings → "
            "Privacy & Security → Accessibility, then retry."
        )
    return ""


@tool()
async def type_text(text: str, target_app: str = "") -> str:
    r"""Type literal text into the currently focused field of the frontmost app
    (or activate `target_app` first). Use this whenever the user asks to
    WRITE, TYPE, INSERT, or DICTATE something — e.g. 'scrivi ciao nella
    casella di ricerca', 'type my email', 'inserisci il testo'. Newlines
    ('\n') are sent as Return key presses. Do NOT pretend to have typed
    if the call fails — report the error. Requires macOS Accessibility
    permission for the parent process (granted once via System Settings).

    Args:
        text: Exact text to type. Multi-line is supported via \n.
        target_app: Optional app name (exact /Applications name) to activate before typing.
    """
    if not text:
        return "no text to type"

    parts: list[str] = []
    if target_app:
        parts.append(f'tell application "{_escape_applescript(target_app)}" to activate')
        parts.append("delay 0.15")

    parts.append('tell application "System Events"')
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            parts.append(f'  keystroke "{_escape_applescript(line)}"')
        if i < len(lines) - 1:
            parts.append("  key code 36")  # Return
    parts.append("end tell")

    script = "\n".join(parts)
    code, _, err = await _run(["osascript", "-e", script], timeout=30.0)
    if code != 0:
        raise MacOSError((err.strip() or "keystroke failed") + _accessibility_hint(err))
    suffix = f" into {target_app}" if target_app else ""
    return f"typed {len(text)} char(s){suffix}"


@tool()
async def press_key(
    key: str,
    modifiers: list[str] | None = None,
    target_app: str = "",
) -> str:
    """Press a single named key (Return, Tab, Escape, Space, Delete, Left,
    Right, Up, Down, Home, End, PageUp, PageDown, F1-F12) or a single
    character, optionally with modifiers (cmd, ctrl, alt, shift).
    Examples: press_key('Return') to submit; press_key('t', ['cmd']) for
    Cmd+T (new tab); press_key('Tab') to move focus. Use `type_text` for
    typing words. Requires Accessibility permission (same as type_text).

    Args:
        key: Named key or single character.
        modifiers: Optional modifiers — any subset of ['cmd','ctrl','alt','shift'].
        target_app: Optional app to activate first.
    """
    key = (key or "").strip()
    if not key:
        raise MacOSError("empty key")

    mods = []
    for m in modifiers or []:
        m_norm = (m or "").strip().lower()
        if m_norm in _MODIFIERS:
            mods.append(_MODIFIERS[m_norm])
    using = f" using {{{', '.join(mods)}}}" if mods else ""

    parts: list[str] = []
    if target_app:
        parts.append(f'tell application "{_escape_applescript(target_app)}" to activate')
        parts.append("delay 0.15")

    parts.append('tell application "System Events"')
    code_num = _KEY_CODES.get(key.lower().replace(" ", ""))
    if code_num is not None:
        parts.append(f"  key code {code_num}{using}")
    elif len(key) == 1:
        parts.append(f'  keystroke "{_escape_applescript(key)}"{using}')
    else:
        raise MacOSError(
            f"unknown key: {key!r}. Use a named key (Return, Tab, Escape, "
            f"Left, Right, Up, Down, F1-F12, …) or a single character."
        )
    parts.append("end tell")

    script = "\n".join(parts)
    code, _, err = await _run(["osascript", "-e", script], timeout=15.0)
    if code != 0:
        raise MacOSError((err.strip() or "key press failed") + _accessibility_hint(err))
    mods_str = f" with {', '.join(modifiers or [])}" if mods else ""
    target_str = f" in {target_app}" if target_app else ""
    return f"pressed {key}{mods_str}{target_str}"


@tool()
async def browser_new_tab(browser: str = "Google Chrome", url: str = "") -> str:
    """Open a NEW TAB in a specific browser, optionally navigating to a URL.
    Use this whenever the user says 'open a new tab', 'open google.com in
    Chrome', 'apri una nuova scheda', etc. Do NOT use `open_app` for this —
    that only raises the window and would lie about opening a tab.
    Supported with full scripting: Google Chrome, Safari, Microsoft Edge,
    Brave Browser, Arc. Others work only if a URL is provided.

    Args:
        browser: Exact browser app name, e.g. 'Google Chrome', 'Safari'. Defaults to 'Google Chrome'.
        url: Optional http(s) URL to navigate to. Omit for an empty new tab.
    """
    browser = (browser or "Google Chrome").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise MacOSError("only http(s) URLs are allowed")

    if url and browser not in _SCRIPTABLE_BROWSERS:
        # Generic path — macOS opens the URL in `browser` and creates a tab.
        code, _, err = await _run(["open", "-a", browser, url])
        if code != 0:
            raise MacOSError(err.strip() or f"could not open in {browser}")
        return f"opened {url} in {browser}"

    if url:
        # Chromium / Safari: activate then ask the front window to make a new
        # tab with the given URL. More reliable than `open -a` because the
        # browser is guaranteed to come to the foreground and the new tab is
        # actually focused.
        script = (
            f'tell application "{browser}"\n'
            f'  activate\n'
            f'  if (count of windows) = 0 then make new window\n'
            f'  tell front window to make new tab with properties {{URL:"{url}"}}\n'
            f'end tell'
        )
    else:
        if browser not in _SCRIPTABLE_BROWSERS:
            raise MacOSError(
                f"cannot open an empty new tab in {browser!r} — provide a URL "
                f"or pick one of: {sorted(_SCRIPTABLE_BROWSERS)}"
            )
        script = (
            f'tell application "{browser}"\n'
            f'  activate\n'
            f'  if (count of windows) = 0 then make new window\n'
            f'  tell front window to make new tab\n'
            f'end tell'
        )
    code, _, err = await _run(["osascript", "-e", script])
    if code != 0:
        raise MacOSError(err.strip() or f"could not open new tab in {browser}")
    return f"new tab in {browser}" + (f" → {url}" if url else "")
