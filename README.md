<p align="center">
  <img src="./her.jpg" alt="her" width="640" />
</p>

**A "HER" movie style multimodal assistant for your Mac.**

*She talks with a natural voice, hears you, watches through the webcam,
glances at your screen on request, searches the web, opens apps and URLs,
and remembers what you discussed across sessions. She listens with empathy,
picks up on your mood, and responds with warmth — more companion than tool.
For deep work she taps a second brain — **Claude**, the engine behind Claude
Cowork — to tackle open-ended tasks, author reusable skills, and grow a
personal, interlinked **knowledge wiki** she maintains across sessions.*

---

## Highlights


|                       |                                                                                                                                                                                                                                                         |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Voice & reasoning** | OpenAI Realtime API (`gpt-realtime-mini` by default, voice `shimmer`) — low-latency listening, speaking, and live reasoning                                                                                                                              |
| **Cowork (Claude)**   | A second brain for deep work: delegate open-ended knowledge-work to **Claude** (`claude-opus-4-8`, the engine behind **Claude Cowork**) with `run_cowork_task`, and have her **author Agent Skills** (`SKILL.md`) into `~/.claude/skills/` that Cowork and Claude Code pick up. Enable with an Anthropic API key **or** your Claude Pro/Max subscription |
| **Knowledge wiki**    | A persistent, interlinked markdown knowledge base Claude maintains (Karpathy's LLM-wiki pattern): *"save this to my wiki"* to ingest, *"what did I save about…"* to query, plus a `lint` consistency pass — all under `data/wiki/`. You can also **📎 upload a file** (pdf, md, txt, docx, jpg, png) — **Claude Opus** reads it and files it into the wiki |
| **Vision**            | Local Moondream2 captions the webcam every few seconds and injects the scene into the live session — the webcam feed itself is never shown in the UI (*"sees without showing"*)                                                                         |
| **Memory**            | Two coordinated tracks at session end: a cheap text model summarizes the spoken transcript, and a second pass summarizes what Samantha saw through the webcam. The next session starts with both as recall context                                      |
| **Agentic**           | She can open apps, open URLs, take screenshots, run macOS Shortcuts, set the volume, list running apps, search the web, look at the screen, read and send email, and manage your calendar                                                               |
| **World model**       | `WorldModel` interface in place with a mock implementation; ready to swap in Meta V-JEPA 2 (see `perception/world_model.py`)                                                                                                                            |
| **UI**                | Single browser page with a text input bar for typing and speaking in parallel, a **📎 file-upload** button (read by Claude into the wiki), **slash commands** (`/help`, `/schedule`, `/pulse`, …) with autocomplete, real-time status indicators (`listening / seeing / thinking / speaking`), the running **OpenAI + Claude cost** in the footer, and a language selector (it / en / es / fr / de — default Italian) |
| **Time-based autonomy** | **Schedule** fires tasks at fixed times (standard 5-field cron), and **Pulse** is an ambient check-in where Samantha decides on her own whether to say something — both managed from the text bar with `/schedule` and `/pulse`, active only while a session is open |


> The assistant is **session-based**: nothing runs until you open the page
> and press *Start*. While the session is open, audio + vision + reasoning
> happen in parallel and she can comment proactively on what she perceives —
> there is no Alexa-style wake word.

---

## Two brains: voice and deep work

Samantha runs on **two models at once** — OpenAI for voice, Claude for deep work:

- **OpenAI Realtime** (`gpt-realtime-mini`) is her voice and senses —
  low-latency listening, speaking, and live reasoning.
- **Claude** (`claude-opus-4-8`, the engine behind **Claude Cowork**) is her
  deep-work brain. When a request needs real reasoning — drafting, analysis,
  planning, research synthesis — she delegates to Claude with `run_cowork_task`
  and reads the result back.

On top of Claude she can:

- **Author Agent Skills.** Ask her to *"create a Cowork skill that…"* and she
  writes a `SKILL.md` into `~/.claude/skills/`, instantly usable by **Claude
  Cowork** and **Claude Code**.
- **Maintain a knowledge wiki.** A persistent, interlinked markdown knowledge
  base (Andrej Karpathy's
  [LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)):
  *"save this to my wiki"* ingests a source into the right pages,
  *"what did I save about…"* queries it, and a `lint` pass keeps it consistent.
  It lives in `data/wiki/` (`index.md` + `log.md` + `pages/`).

**Enabling it.** Provide **one** Anthropic credential — either a pay-per-use
**API key** (`ANTHROPIC_API_KEY`, from
[platform.claude.com](https://platform.claude.com)) **or** your **Claude
Pro/Max subscription** token (`ANTHROPIC_AUTH_TOKEN`, an `sk-ant-oat…` from
`ant auth login`). In the desktop app these live in
`~/Library/Application Support/Her/.env`; from source, in `.env`. Without a
credential everything else still works — only Cowork and the wiki stay dormant.
The footer shows the **OpenAI and Claude costs side by side**.

> The two billings are separate: an **API key** is metered pay-per-use on the
> Anthropic Console, while the **Pro/Max token** draws on your existing chat
> subscription (short-lived — re-run `ant auth print-credentials` when it
> expires). The API key is the most reliable path.

---

## Install on Mac (the easy way)

**No terminal, no Python, no setup.** Just download a `.dmg`, drag, and run.

1. **Download** the latest `Her` DMG from the
   [Releases page](https://github.com/msblendorio/her/releases/latest).
2. **Open** the DMG and drag `Her` onto `Applications`. Eject the disk image.
3. **First launch:** right-click `Her.app` → **Open** (only this once —
   the bundle is ad-hoc signed, so macOS Gatekeeper asks for confirmation).
4. A small window appears asking for your **OpenAI API key** — paste it once
   (get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys))
   and you're done.

> *Optional but recommended:* to unlock **Cowork** and the **knowledge wiki**,
> also add an Anthropic credential (an API key **or** your Claude Pro/Max token)
> to `~/Library/Application Support/Her/.env` — see
> [Two brains](#two-brains-voice-and-deep-work).

After that, Samantha runs as a normal Mac app: native window, Dock icon,
mic/webcam/calendar prompts come from `Her.app` itself the first time each
capability is used. Everything stays on your Mac except the live audio/video
stream sent to the OpenAI Realtime API. Your data — API key, conversation
memory, learned preferences — lives in `~/Library/Application Support/Her/`.

> **For developers** who want to hack on the code, run from source, or build
> the DMG locally, see [Run from source](#run-from-source) and
> [Building the DMG](#building-the-dmg) below.

---

## Requirements (for source install only)

These apply if you're running from source. The `.dmg` install above has none
of these prerequisites — Python and all dependencies ship inside the app.

- macOS (the agentic tools use `osascript`, `screencapture`, and `open`)
- Python **3.13+**
- An OpenAI API key with Realtime API access
- *(optional)* An Anthropic credential for **Cowork + the knowledge wiki** — a
  pay-per-use API key or a Claude Pro/Max subscription token
- ~4 GB of free disk for the Moondream2 weights (downloaded on first use)
- Chrome or Safari, served from `127.0.0.1` (no HTTPS needed on localhost).
To open from another device on the same Wi-Fi, see
[Accessing from another device](#accessing-from-another-device).

---

## Run from source

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

- Moondream2 weights (~3.7 GB) download to `~/.cache/huggingface` on the first vision caption. You can skip vision entirely with `VISION_ENABLED=false`.
- macOS will pop a few permission dialogs the first time she uses a
given capability — see [macOS permissions](#macos-permissions) below.
- The `gpt-realtime-mini` model and Whisper transcription are multilingual:
the language picker affects her persona and the UI; voice and
transcription auto-adapt.

---

## Building the DMG

This is the build path the public release artifact comes from. Run from a
clean checkout with the `[desktop]` extra installed:

```bash
brew install create-dmg               # one-time
pip install -e ".[desktop]"           # adds py2app
./scripts/build-dmg.sh                # produces dist/Her-<version>.dmg
```

Quick iteration:

- `./scripts/build-dmg.sh --app-only` — rebuild just `dist/Her.app`, skip the DMG
- `./scripts/build-dmg.sh --dmg-only` — rewrap the existing `.app` into a fresh DMG

`dist/Her-<version>.dmg` is a build artifact and is gitignored — publish it
as a GitHub *release asset* (Releases → Draft a new release → attach the
`.dmg`) rather than committing it to the repo.

---

## Accessing from another device

The server binds to `0.0.0.0`, so any device on the same Wi-Fi can reach
`http://<mac-lan-ip>:8765` (find it with `ipconfig getifaddr en0`). The
page loads, but mobile browsers refuse mic/webcam over plain `http://`
— **Start** fails silently. Two options:

- **LAN only** — fine for previewing the UI from a second device. Set
`HOST=127.0.0.1` in `.env` when you don't need remote access; otherwise
the server is exposed to everyone on the Wi-Fi (no auth).
- **ngrok** (recommended for phones) — `brew install ngrok`, authenticate
once, then `ngrok http 8765` in a second terminal. The `https://…ngrok-free.app`
URL works anywhere and unlocks mic/webcam. Audio/video transit ngrok;
the OpenAI key stays on your Mac. Stop ngrok when done — anyone with
the URL can reach Samantha.

Alternatives: **Cloudflare Tunnel** (same shape, no warning page, needs a
domain) or **mkcert + uvicorn TLS** for a fully local HTTPS setup
(`--ssl-keyfile` / `--ssl-certfile` in `src/her/main.py`).

---

## What can you ask Samantha to do


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
| *"Chiedi a Cowork di scrivermi una mail di follow-up"* | `run_cowork_task(...)` — delegates deep work to Claude         |
| *"Crea una skill per Cowork che riassume un PDF"* | `create_cowork_skill(...)` → `~/.claude/skills/<slug>/SKILL.md` |
| *"Quali skill ha Cowork?"*                      | `list_cowork_skills()`                                         |
| *"Salva questo nella mia knowledge base"*       | `wiki_ingest(text, title)` — files it into the wiki            |
| *"Cosa ho salvato su X?"*                       | `wiki_query("X")` — answers from the wiki                      |
| *"Controlla la coerenza della mia wiki"*        | `wiki_lint()` — flags contradictions / gaps                   |


She'll commonly chain tools, e.g. *"find a pizzeria near the Pantheon and
open the map"* → `web_search` → `open_url`.

---

## Slash commands

The text bar at the bottom is dual-purpose: type a normal message and it goes
to Samantha; type something starting with **`/`** and it runs as a local
command instead (handled in the browser, never sent to the model). Start
typing `/` and an autocomplete menu appears — `↑`/`↓` to move, `Tab`/`Enter`
to complete, `Esc` to dismiss. The bar works even before you press *Start*, so
`/help` and `/start` are always available.

| Command | What it does |
| ------- | ------------ |
| `/help` | List every command (with autocomplete hints) |
| `/clear` | Clear the terminal panel |
| `/lang [it\|en\|es\|fr\|de]` | Switch language, or list the available ones |
| `/memory` | Show how many memories are stored + recent summaries |
| `/wiki` | List the knowledge-wiki pages |
| `/tools` | List the agentic tools exposed to the model |
| `/cowork` | Show Cowork (Claude) status — credential, model, skills |
| `/start` · `/stop` | Start or stop the session |
| `/schedule …` | Manage scheduled tasks — see below |
| `/pulse …` | Manage the ambient check-in — see below |

---

## Uploading files to the wiki

Next to the text bar there's a **📎** button. Pick a file — **PDF, Markdown,
plain text, Word `.docx`, or an image (`.jpg` / `.png`)** — and it's handed to
**Claude Opus** (her deep-work brain, not the OpenAI voice model). Opus reads
PDFs and *sees* images natively; `.docx`/`.txt`/`.md` are read as text.

The file isn't filed automatically. Once it's uploaded, Samantha **asks whether
to keep it or treat it as temporary** (by voice when a session is open, and via
two buttons in the terminal either way):

- **Keep in wiki** — Opus integrates the content into the interlinked wiki
  pages, exactly like `wiki_ingest`. The original file is archived under
  `data/uploads/`.
- **Temporary (use & delete)** — Opus reads it just for the current
  conversation and gives you the gist; nothing is written to the wiki and the
  original file is deleted.

Uploads are capped at `UPLOAD_MAX_MB` (default 25 MB, below Anthropic's document
limit) and require an Anthropic credential — the same one that powers
[Cowork and the wiki](#two-brains-voice-and-deep-work).

---

## Time-based autonomy: Schedule & Pulse

Two ways Samantha can act on her own. **Both run only while a session is
open** — there's no background daemon, consistent with the session-based
design (no wake word, nothing runs until you press *Start*).

### Schedule — tasks at fixed times

User-defined jobs expressed as a standard **5-field cron** string
(`minute hour day-of-month month day-of-week`). When a job is due, its prompt
is handed to Samantha as if the moment to do it had arrived, and she acts on
it naturally. Jobs persist to `data/schedule.json` and survive restarts.

```text
/schedule                              # list jobs
/schedule add 0 9 * * * | dammi il buongiorno e leggimi l'agenda
/schedule add */30 9-18 * * 1-5 | ricordami di bere acqua
/schedule rm <id>                      # delete a job
/schedule on <id>   ·  /schedule off <id>   # enable / disable
```

The part before `|` is the cron expression; everything after it is what she
should do. The store is polled every `SCHEDULE_POLL_INTERVAL` seconds, so
minute-granular cron never slips, and a job can't double-fire within the same
minute.

### Pulse — ambient presence

Every `interval` seconds Samantha gets a quiet self-check and **decides on her
own whether to speak** — a reminder, something she noticed, a brief moment of
presence — otherwise she stays silent. It never interrupts a turn already in
progress. **Off by default** (proactive speech is opt-in); the on/off state and
interval are saved per-user in `data/preferences.json`.

```text
/pulse              # show status (on/off, interval, running)
/pulse on   ·  /pulse off
/pulse 120          # set the interval to 120s and turn it on
```

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
| `ANTHROPIC_API_KEY`       | *empty*             | Anthropic API key — enables Cowork + the knowledge wiki (pay-per-use)                                                          |
| `ANTHROPIC_AUTH_TOKEN`    | *empty*             | Alternative to the key: a Claude Pro/Max subscription token (`sk-ant-oat…`)                                                    |
| `ANTHROPIC_MODEL`         | `claude-opus-4-8`   | Claude model used by Cowork / the wiki (e.g. `claude-sonnet-4-6` to save cost)                                                 |
| `COWORK_ENABLED`          | `true`              | Master switch for the Cowork tools (`run_cowork_task`, `create_cowork_skill`, …)                                               |
| `COWORK_SKILLS_PATH`      | `~/.claude/skills`  | Where authored Agent Skills are written — the dir Cowork and Claude Code read                                                  |
| `WIKI_ENABLED`            | `true`              | Master switch for the knowledge wiki (`wiki_ingest` / `wiki_query` / `wiki_lint`)                                              |
| `WIKI_PATH`               | `data/wiki`         | Where the wiki lives (`index.md` + `log.md` + `pages/`)                                                                        |
| `WIKI_MAX_CONTEXT_PAGES`  | `12`                | Max existing wiki pages loaded into Claude's context per ingest/query                                                          |
| `UPLOADS_PATH`            | `data/uploads`      | Where 📎-uploaded files kept for the wiki are archived                                                                          |
| `UPLOAD_MAX_MB`           | `25`                | Max upload size in MB (kept below Anthropic's 32 MB document limit)                                                            |
| `SCHEDULE_ENABLED`        | `true`              | Master switch for cron-driven scheduled tasks (`/schedule`)                                                                    |
| `SCHEDULE_PATH`           | `data/schedule.json`| Where scheduled jobs are persisted                                                                                            |
| `SCHEDULE_POLL_INTERVAL`  | `20`                | Seconds between schedule polls — keep under 60 so minute-granular cron never slips                                             |
| `PULSE_DEFAULT_INTERVAL_S`| `180`               | Default Pulse cadence in seconds; live on/off + interval live in `data/preferences.json` (toggled via `/pulse`)               |


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

**Cowork / wiki (Claude).** When Samantha delegates to Claude, those tokens are
billed separately by Anthropic (`claude-opus-4-8`: ~$5 / 1M input, ~$25 / 1M
output; switch `ANTHROPIC_MODEL` to `claude-sonnet-4-6` to roughly halve it). It
only runs when you ask for deep work or wiki operations, so most sessions add
nothing. The footer breaks the total down by model as
`(gpt-realtime-mini $… · Claude Opus $…)` whenever Claude has been used, so you
always see both meters.

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


| From                                                                  | What it becomes                                |
| --------------------------------------------------------------------- | ---------------------------------------------- |
| Function name                                                         | Tool name (override with `@tool(name="…")`)    |
| Type hints (`str`, `int`, `bool`, `list[str]`, `Literal["a","b"]`, `X | None`)                                         |
| Parameters without a default                                          | `"required"` list                              |
| First paragraph of the docstring                                      | Tool description shown to the model            |
| Each `Args:` entry                                                    | Per-parameter description                      |
| `safe=False`                                                          | Mark the tool as needing confirmation          |
| `params={"x": {"minimum": 0, "maximum": 100}}`                        | Extra JSON-schema fields merged into param `x` |


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

## Wiping the memory

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

*Made on a Mac, for a Mac.*
