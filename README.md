<p align="center">
  <img src="./her.jpg" alt="her" width="640" />
</p>

# her

**A *"Her"*-style multimodal assistant for your Mac.**

*She talks with a natural voice, hears you, watches through the webcam,
glances at your screen on request, searches the web, opens apps and URLs,
and remembers what you discussed across sessions.*

<p align="center">
  <a href="./pyproject.toml"><img src="https://img.shields.io/badge/version-0.2.0-blue" alt="version" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="license" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.13%2B-blue" alt="python" /></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/platform-macOS-lightgrey" alt="platform" /></a>
</p>



---

## Highlights


|                       |                                                                                                                                                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Voice & reasoning** | OpenAI Realtime API (`gpt-realtime-mini` by default, voice `shimmer`)                                                                                                                                                              |
| **Vision**            | Local Moondream2 captions the webcam every few seconds and injects the scene into the live session — the webcam feed itself is never shown in the UI (*"sees without showing"*)                                                    |
| **Memory**            | Two coordinated tracks at session end: a cheap text model summarizes the spoken transcript, and a second pass summarizes what Samantha saw through the webcam. The next session starts with both as recall context                 |
| **Agentic**           | She can open apps, open URLs, take screenshots, run macOS Shortcuts, set the volume, list running apps, search the web, look at the screen, read and send email, and manage your calendar                                          |
| **World model**       | `WorldModel` interface in place with a mock implementation; ready to swap in Meta V-JEPA 2 (see `perception/world_model.py`)                                                                                                       |
| **UI**                | Single browser page with a Claude-Code-style rolling terminal, live status indicators (`listening / seeing / thinking / speaking`), running cost in the footer, and a language selector (it / en / es / fr / de — default Italian) |


> The assistant is **session-based**: nothing runs until you open the page
> and press *Start*. While the session is open, audio + vision + reasoning
> happen in parallel and she can comment proactively on what she perceives —
> there is no Alexa-style wake word.

---

## Requirements

- macOS (the agentic tools use `osascript`, `screencapture`, and `open`)
- Python **3.13+**
- An OpenAI API key with Realtime API access
- ~4 GB of free disk for the Moondream2 weights (downloaded on first use)
- Chrome or Safari, served from `127.0.0.1` (no HTTPS needed on localhost).
To open from another device on the same Wi-Fi, see
[Accessing from another device](#accessing-from-another-device).

---

## Quick start

```bash
# 1. Clone & enter the project
git clone https://github.com/msblendorio/her.git
cd her

# 2. Create and activate a virtualenv
python3.13 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt   # plain install
# — or, for development (editable, exposes the `her` CLI):
# pip install -e .

# 4. Configure
cp .env.example .env
# then edit .env and set OPENAI_API_KEY=sk-...

# 5. Run
./run.sh
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765) in Chrome or Safari, click **Start**, and
grant microphone + webcam permissions.

**First-launch notes**

- Moondream2 weights (~~3.7 GB) download to `~~/.cache/huggingface`on the first vision caption. You can skip vision entirely with`VISION_ENABLED=false`.
- macOS will pop a few permission dialogs the first time she uses a
given capability — see [macOS permissions](#macos-permissions) below.
- The `gpt-realtime-mini` model and Whisper transcription are multilingual:
the language picker affects her persona and the UI; voice and
transcription auto-adapt.



---

## Accessing from another device

The server now binds to `0.0.0.0` by default, so it answers on every network
interface — not just `localhost`. That's enough to reach it from a phone,
tablet, or laptop on the **same Wi-Fi**, but mobile browsers refuse to give
microphone or webcam access over plain `http://` (the only exception is
`http://localhost`), so without HTTPS the page loads but **Start** fails
silently. Pick one of the two setups below.

### Option A — LAN only (no HTTPS, page loads but mic/webcam blocked on phones)

Useful to see the UI from a second device, not to actually talk to Samantha
from the phone.

1. Find your Mac's LAN IP:
  ```bash
   ipconfig getifaddr en0      # Wi-Fi; try en1 if en0 is empty
  ```
2. Start the server as usual (`./run.sh`).
3. On the other device, open `http://<mac-lan-ip>:8765`.
4. macOS will likely show a firewall prompt the first time — allow incoming
  connections for `python` / `uvicorn`.

> ⚠️ Binding to `0.0.0.0` exposes the server to **everyone on the Wi-Fi**.
> There is no authentication in the code. On a home network that's usually
> fine; on a café/coworking/hotel Wi-Fi it is not. Revert to
> `HOST=127.0.0.1` in `.env` when you don't need remote access.

### Option B — ngrok (HTTPS, mic + webcam work from anywhere)

This is the recommended path if you actually want to talk to Samantha from
your phone. ngrok terminates TLS for you, so the phone's browser sees a
valid `https://` origin and allows `getUserMedia`. Works on any network,
not just the same Wi-Fi.

1. Install ngrok and authenticate it once:
  ```bash
   brew install ngrok
   ngrok config add-authtoken <your-token>     # from dashboard.ngrok.com
  ```
2. Start Samantha as usual:
  ```bash
   ./run.sh
  ```
3. In a second terminal, open the tunnel:
  ```bash
   ngrok http 8765
  ```
   ngrok prints a forwarding URL like
   `https://something-something.ngrok-free.app` — open that on your phone,
   accept the mic + webcam permission prompts, and press **Start**.

Trade-offs to be aware of:

- All traffic transits ngrok's infrastructure. The OpenAI key never leaves
your Mac (the browser only talks to ngrok → Samantha → OpenAI), but the
audio/video frames do pass through the tunnel.
- The free plan rotates the public URL on every restart. `ngrok config`
with a reserved domain (paid) keeps it stable.
- The free plan also injects a one-time browser warning page on the first
visit — click through it once per device.
- ngrok bypasses the LAN-only safety of `127.0.0.1`. While the tunnel is
up, **anyone with the URL can reach Samantha**. Stop ngrok (`Ctrl-C`)
when you're done.

### Alternatives

- **Cloudflare Tunnel** (`cloudflared`) — same shape as ngrok, free, no
ngrok-branded warning page. Needs a Cloudflare account and a domain.
- **mkcert + uvicorn TLS** — stays in LAN, no third party. Generate a
local cert with `mkcert <mac-lan-ip>`, install the mkcert root CA on
the phone, then pass `--ssl-keyfile` / `--ssl-certfile` to uvicorn (the
`uvicorn.run(...)` call lives in `src/her/main.py`). More setup, but
zero external dependency.

---

## What you can ask her to do


| You say…                                        | What happens                                                  |
| ----------------------------------------------- | ------------------------------------------------------------- |
| *"Open Safari"*                                 | `open_app("Safari")`                                          |
| *"Take me to google.com"*                       | `open_url("https://google.com")`                              |
| *"What apps am I using?"*                       | `list_running_apps()` then a spoken summary                   |
| *"Take a screenshot"*                           | `take_screenshot()` saves to `~/Desktop/her_screenshot_*.png` |
| *"Set volume to 30"*                            | `set_volume(30)`                                              |
| *"Run the Shortcut 'X'"*                        | `run_shortcut("X")` (she'll ask first for non-trivial ones)   |
| *"What is on my screen?"*                       | `look_at_screen()` — fresh screenshot, captioned by Moondream |
| *"Search the latest news about X"*              | `web_search("X")` then a spoken summary                       |
| *"Read what's on my screen"*                    | `read_screen()` — verbatim text via Apple Vision OCR          |
| *"Attiva la modalità accessibilità"*            | `toggle_accessibility_mode(on=true)` — see below              |
| *"What's on my agenda today?"*                  | `calendar_list_events("today")` via macOS EventKit            |
| *"Schedule a coffee with Anna tomorrow at 4pm"* | `calendar_create_event(title, start, end)`                    |
| *"When is my meeting with the dentist?"*        | `calendar_search_events("dentist")`                           |
| *"Hai mail nuove?"* / *"Any new email?"*        | `email_list_unread()` via macOS Mail.app                      |
| *"Cerca la mail della banca"*                   | `email_search("banca")` (subject + sender + body)             |
| *"Send Anna a quick note saying I'll be late"*  | `email_send(to, subject, body)` — confirms first, then sends  |


She'll commonly chain tools, e.g. *"find a pizzeria near the Pantheon and
open the map"* → `web_search` → `open_url`.

---

## Accessibility mode

A voice-activated mode for visually impaired users. The default mode is the
standard one; the user can switch on accessibility mode at any time by
saying something like *"attiva la modalità accessibilità"*, *"activate
accessibility mode"*, or *"help me, I can't see the screen"* — Samantha
calls `toggle_accessibility_mode(on=true)` and the mode flips immediately.

While on:

- The screen is OCR'd locally via the **Apple Vision framework** every
`ACCESSIBILITY_SCREEN_INTERVAL` seconds (default 6s); the *verbatim text*
is injected into the live session as ambient context.
- Samantha's persona gets an addendum telling her to read concisely —
name the app and context in one sentence, then read only what's
relevant. No bullet lists, no character-by-character URLs, no repeating
unchanged content.
- The dedicated `read_screen` tool returns the same verbatim OCR on
demand, e.g. when the user asks *"what does this button say?"*.

The user turns it off the same way: *"disattiva la modalità accessibilità"*.
On non-macOS hosts (or if `pyobjc-framework-Vision` isn't installed), the
mode still works but falls back to a Moondream description (less accurate,
paraphrased rather than verbatim).

**Persistence:** the accessibility state is saved to
`PREFERENCES_PATH` (default `data/preferences.json`) every time it
changes. The next session restores it automatically — a visually
impaired user only enables the mode once, ever. To reset to the default
("off"), delete `data/preferences.json`.

### Discovering available modes

There is **no fixed wake phrase** for any mode — Samantha is an LLM and
parses natural language. If a user doesn't know what's on offer, they can
simply ask:

> *"Quali modalità hai?"* / *"What modes do you have?"*

…and Samantha will list the modes she can toggle on demand (currently:
accessibility mode), explain when each is useful, and tell the user how
to activate them. This is the recommended onboarding path for visually
impaired users who can't read the documentation.

---

## Project layout

```text
src/her/
├── main.py                   # uvicorn entrypoint
├── config.py                 # env-driven settings
├── i18n.py                   # 5-language prompts (it / en / es / fr / de)
├── core/
│   ├── event_bus.py          # tiny async pub/sub
│   ├── state.py              # shared session snapshot (status + usage)
│   ├── usage.py              # token & cost tracker for the running session
│   └── orchestrator.py       # wires perception ↔ reasoning ↔ memory
├── perception/
│   ├── vision_capture.py     # receives JPEG frames from the browser
│   ├── vision_scene.py       # singleton Moondream2 captioner
│   └── world_model.py        # V-JEPA 2 stub interface
├── reasoning/
│   └── realtime_session.py   # OpenAI Realtime WS client (GA shape)
├── memory/
│   ├── store.py              # append-only JSONL of session summaries
│   ├── collector.py          # accumulates the live transcript
│   ├── summarizer.py         # OpenAI Chat call (cheap) at session end
│   └── recall.py             # injects past summaries into next session
├── agentic/
│   ├── registry.py           # @tool decorator + schema introspection
│   ├── __init__.py           # imports domain modules to trigger registration
│   ├── macos.py              # @tool functions: open_app, open_url, …
│   ├── calendar.py           # @tool functions: calendar_list/search/create_event
│   ├── email.py              # @tool functions: email_list_unread, email_search, email_send
│   ├── screen.py             # @tool functions: look_at_screen, read_screen
│   ├── web.py                # @tool functions: web_search
│   ├── accessibility.py      # @tool function: toggle_accessibility_mode
│   ├── ocr.py                # Apple Vision OCR backend (used by screen.py)
│   ├── tools.py              # back-compat facade re-exporting TOOLS
│   └── executor.py           # dispatches model-issued tool calls
├── server/
│   ├── app.py                # FastAPI app + REST endpoints
│   └── ws.py                 # WebSocket bridges (audio / vision / events)
└── ui/static/                # HTML / CSS / JS frontend
```

---

## How it works

1. The browser captures microphone audio (PCM16 @ 24 kHz, via an AudioWorklet)
  and webcam frames (1 fps JPEG, hidden — no preview).
2. Mic audio is forwarded over WebSocket to the server, which relays it into
  the OpenAI Realtime session. Server-side VAD on OpenAI handles turn
   detection.
3. Webcam frames hit a separate WebSocket. Every `VISION_CAPTION_INTERVAL`
  seconds Moondream2 produces a short caption that is injected into the
   session as a system context message — that's how she "sees" you.
4. Tools (`open_app`, `web_search`, `look_at_screen`, …) are exposed to the
  model via OpenAI function calling. When she invokes one the server
   executes it asynchronously and feeds the result back, then asks the
   model to continue speaking about it.
5. Audio responses stream back to the browser and are played through the Web
  Audio API. Transcripts (yours and hers) and tool calls land in the terminal
   panel in real time.
6. On session stop, two cheap (`gpt-4o-mini`) summarizers run in parallel:
  one over the spoken transcript, one over the timeline of webcam scene
   captions. Both results are merged into a single entry in
   `data/memory.jsonl`. The next session loads the most recent entries and
   threads them into her instructions, with a short `visto:` (or `saw:`,
   `vu :`, …) sub-line per session whenever a visual summary is available.

---

## Configuration (`.env`)

Sensible defaults are in `.env.example`. The interesting knobs:


| Variable                  | Default             | Purpose                                                                                                                        |
| ------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `OPENAI_API_KEY`          | *required*          | Your OpenAI key                                                                                                                |
| `OPENAI_REALTIME_MODEL`   | `gpt-realtime-mini` | Switch to `gpt-realtime` or `gpt-realtime-2` for top quality (~10× cost)                                                       |
| `OPENAI_VOICE`            | `shimmer`           | Other feminine options: `sage`, `coral`, `alloy`                                                                               |
| `ASSISTANT_LANGUAGE`      | `it`                | Default language; users override via the UI dropdown                                                                           |
| `VISION_ENABLED`          | `true`              | Set `false` to skip Moondream entirely (audio-only mode)                                                                       |
| `VISION_CAPTION_INTERVAL` | `4.0`               | Seconds between webcam captions                                                                                                |
| `VISION_DEVICE`           | `mps`               | `mps` on Apple Silicon, `cpu`, or `cuda`                                                                                       |
| `MEMORY_ENABLED`          | `true`              | Persist session summaries to `data/memory.jsonl`                                                                               |
| `MEMORY_RECALL_COUNT`     | `5`                 | How many past sessions to inject into a new one                                                                                |
| `MEMORY_SUMMARIZER_MODEL` | `gpt-4o-mini`       | Cheap text model for end-of-session summary                                                                                    |
| `VISUAL_MEMORY_ENABLED`   | `true`              | Also summarize what Samantha saw through the webcam and replay it in the next session's recall. Requires `VISION_ENABLED=true` |
| `AGENTIC_ENABLED`         | `true`              | Expose the macOS / web / screen tools to the model                                                                             |
| `WORLD_MODEL_ENABLED`     | `false`             | Keep off until real V-JEPA 2 weights are wired                                                                                 |


---

## Cost

OpenAI Realtime pricing as of early 2026, approximate:


| Model                           | Audio in   | Audio out  | Typical 10-min session |
| ------------------------------- | ---------- | ---------- | ---------------------- |
| `gpt-realtime-mini` *(default)* | ~$0.01/min | ~$0.02/min | **~$0.10 – $0.30**     |
| `gpt-realtime`                  | ~$0.06/min | ~$0.24/min | ~$3 – $6               |


Memory summaries add a few thousandths of a dollar per session. Vision is
fully local (free). The running cost is shown live in the footer and reset
on every new session.

---

## macOS permissions

The first time she uses certain tools macOS will surface a permission
dialog for the process that launched the server (Terminal, PyCharm,
VS Code, …):


| Tool                                                                      | Permission requested                                                                                          |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `focus_window`, `list_running_apps`, `set_volume`, `browser_new_tab`      | Automation → System Events                                                                                    |
| `type_text`, `press_key`                                                  | Privacy & Security → Accessibility (NOT the same as Automation — this lets the process synthesize keystrokes) |
| `take_screenshot`, `look_at_screen`                                       | Privacy & Security → Screen Recording                                                                         |
| `run_shortcut`                                                            | Automation → Shortcuts                                                                                        |
| `calendar_list_events`, `calendar_create_event`, `calendar_search_events` | Privacy & Security → Calendars                                                                                |
| `email_list_unread`, `email_search`, `email_send`                         | Automation → Mail (first call surfaces the prompt)                                                            |
| `open_app`, `open_url`                                                    | *none*                                                                                                        |


Grant the permission, restart the server, and the prompts will not return.

---

## Adding a new agentic tool

The goal of the registry is that **one decorated async function = one tool
Samantha can call**. No JSON-schema by hand, no second place to edit.

### The 60-second version

Pick (or create) a domain file under `src/her/agentic/` and drop in an
async function:

```python
# src/her/agentic/web.py
from .registry import tool

@tool()
async def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web (DuckDuckGo) and return a short list of {title, url, snippet}.
    Use this when the user asks for facts, news, references, or anything
    you don't already know.

    Args:
        query: Search query, ideally in the user's language.
        max_results: How many results to return (default 5).
    """
    ...
```

That's it. The decorator derives everything the OpenAI Realtime API needs:


| From                                                                           | What it becomes                                |
| ------------------------------------------------------------------------------ | ---------------------------------------------- |
| Function name                                                                  | Tool name (override with `@tool(name="…")`)    |
| Type hints (`str`, `int`, `bool`, `list[str]`, `Literal["a","b"]`, `X | None`) | JSON-schema `type` / `enum` / `items`          |
| Parameters without a default                                                   | `"required"` list                              |
| First paragraph of the docstring                                               | Tool description shown to the model            |
| Each `Args:` entry                                                             | Per-parameter description                      |
| `safe=False`                                                                   | Mark the tool as needing confirmation          |
| `params={"x": {"minimum": 0, "maximum": 100}}`                                 | Extra JSON-schema fields merged into param `x` |


If the function is in a domain file that's already wired in
`agentic/__init__.py` (`macos`, `calendar`, `screen`, `web`,
`accessibility`), you're done — restart the server and the tool is live.

### Adding a brand-new domain

If your tool doesn't fit any existing file (say, you want an `email.py`):

1. Create `src/her/agentic/email.py`.
2. `from .registry import tool` and decorate one or more async functions.
3. Add `from . import email  # noqa: F401` to `agentic/__init__.py`. The
  import is what triggers registration.

### Rules the decorator enforces (at import time, not at runtime)

The registry is fail-fast — a misconfigured tool raises before the server
ever starts:

- Function **must be async** (`async def`). Wrap blocking work in
`asyncio.to_thread()`.
- Every parameter **must have a type hint**. Untyped params raise.
- The function **must have a description** — either in the docstring or
explicitly via `@tool(description="…")`.
- Tool names **must be unique** across the whole registry.
- `*args` / `**kwargs` are not allowed (the JSON schema needs concrete
parameter names).
- `params={…}` overrides may only reference real parameter names.

### A more advanced example

```python
@tool(
    name="calendar_create_event",
    safe=False,                                       # require confirmation
    params={"start": {"format": "date-time"}},        # extra JSON-schema keys
)
async def create_event(
    title: str,
    start: str,
    end: str = "",
    location: str = "",
) -> dict:
    """Create a new event on the user's calendar.
    Confirm title/start/end with the user BEFORE calling.

    Args:
        title: Event title.
        start: ISO 8601 start datetime, e.g. '2026-05-24T15:00'.
        end: ISO 8601 end datetime. Omit for a 1h default.
        location: Optional location.
    """
    ...
```

### Verifying

The decorator's contract is covered by `tests/test_registry.py`:

```bash
.venv/bin/python -m pytest tests/test_registry.py -v
```

To inspect what the model will actually see for a given tool:

```bash
.venv/bin/python -c "
from her.agentic import by_name
import json
print(json.dumps(by_name('your_tool_name').to_openai_spec(), indent=2))
"
```

---

## Plugging in real V-JEPA 2

`perception/world_model.py` ships a `MockWorldModel`. To wire the real one:

1. `pip install timm`
2. Download V-JEPA 2 weights from [https://github.com/facebookresearch/jepa](https://github.com/facebookresearch/jepa)
3. Replace the body of `JEPAWorldModel.encode_scene` / `predict_next` with
  the loaded encoder / predictor.
4. Set `WORLD_MODEL_ENABLED=true` in `.env`.

---

## Stopping / restarting

```bash
# stop
pkill -f .venv/bin/her

# start again
.venv/bin/her           # or: ./run.sh
```

### Wiping the memory

To erase everything she remembers from past sessions:

```bash
her-forget          # prompts for confirmation
her-forget --yes    # no prompt — for scripts
```

This deletes `data/memory.jsonl`. The next session will start with a blank
slate (no recalled context).

---

## Contributing

PRs welcome — new tools, extra languages, prompt tuning, screenshots, bug
fixes. See [CONTRIBUTING.md](CONTRIBUTING.md) for scope, style, and how
contributions are licensed.

---

## License & disclaimer

Released under the [MIT License](LICENSE). You can use, modify, and
redistribute it freely (including commercially); the copyright notice
must be preserved.

> **Heads up:** distribute with care. She can act on your machine, see your
> screen, and uses third-party APIs. Audit the registered tools (run
> `python -c "from her.agentic import TOOLS; [print(t.name, t.safe) for t in TOOLS]"`)
> before exposing it to untrusted users.



*Made on a Mac, for a Mac.*

