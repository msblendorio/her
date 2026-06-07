## 0.8.0

- **Settings panel (⚙️).** A new gear button in the header opens a Preferences
  panel where modes, models, variables and API keys can be edited without
  touching a terminal. Changes are written straight to the local `.env`
  (under `~/Library/Application Support/Her` in the packaged app) and applied
  to the next session — no manual file editing required.
- **Changelog in-app.** This file is now viewable from the same Preferences
  panel, so release notes travel with the app.

## 0.7.0

- **Skill Forge.** Teach Samantha a new skill just by describing it — no
  demonstration needed. A chat model turns the spoken/typed description into an
  AppleScript artefact, previewed before it is saved. Drive it with `/forge`.
- **Local, on-device backends.** Two independent switches go fully free and
  offline: `VOICE_BACKEND=local` (faster-whisper → Ollama → Kokoro) and
  `LLM_BACKEND=local` (routes Cowork, wiki, summaries and skills to Ollama).

## 0.6.1

- Fixed the upload file picker so every supported format is selectable.
- Added drag-and-drop of a file onto the input bar.
- Decoupled the README from the version number.

## 0.6.0

- **File upload → knowledge wiki.** Drop a PDF/MD/TXT/DOCX/JPG/PNG with 📎;
  Claude Opus reads it and either files it into the wiki or uses it once.
- Status-bar costs are now labelled by the model behind each (OpenAI Realtime
  vs. Claude).

## 0.5.0

- **Slash commands** in the input bar (`/help`, `/memory`, `/wiki`, …) with
  autocomplete.
- **Time-based autonomy:** Schedule (cron-driven prompts) and Pulse (ambient
  proactive check-ins), managed via `/schedule` and `/pulse`.

## 0.4.1

- The status bar now shows the Anthropic (Cowork/wiki) cost alongside OpenAI.
- README overhaul.

## 0.3.0

- Camera and microphone permissions persist across launches of the packaged
  app.
