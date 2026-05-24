# Contributing to her

Thanks for thinking of contributing — small fixes, new tools, extra languages,
better prompts, screenshots for the README, all welcome.

## Quick start

1. Fork and clone the repo.
2. Follow the [Quick start](README.md#quick-start) in the README to get a
   working local install on Python 3.13.
3. Create a branch: `git checkout -b my-improvement`.
4. Make your change. Keep diffs small and focused.
5. Open a pull request describing **what** you changed and **why**.

## What's in scope

- New agentic tools (extend `src/her/agentic/tools.py`)
- Additional UI languages (extend `src/her/i18n.py` and the
  `UI_STRINGS` dictionary in `src/her/ui/static/app.js`)
- Prompt tuning for Samantha's persona (per language)
- Bug fixes, performance improvements, clearer error messages
- Documentation, examples, screenshots, demo GIFs
- Tests for any of the above

## What's out of scope (for now)

- Cross-platform agentic tools (Windows/Linux) — the macOS focus is
  intentional; a clean abstraction PR would be welcome though
- Heavy new dependencies without a clear payoff
- Major refactors without a prior discussion (open an issue first)

## Style

- Python 3.13, type hints where useful, `from __future__ import annotations`
  at the top of new modules
- `ruff` is configured in `pyproject.toml`; please run it before pushing
- Keep functions short and modules cohesive — the codebase is small on
  purpose
- Comments only when the *why* is non-obvious; well-named identifiers
  beat explanatory comments
- Don't add UI text without also adding it to all 5 locales (`it`, `en`,
  `es`, `fr`, `de`) — even a placeholder fallback is fine

## Proposing larger changes

For anything beyond a small fix, please open an issue first describing the
idea. A short discussion upfront often saves a lot of back-and-forth on the
PR itself.

## Testing

There are no formal tests yet. At minimum, please verify your change with:

```bash
.venv/bin/python -c "from her.server.app import app; print('imports ok')"
./run.sh                              # boot the server
# open http://127.0.0.1:8765 and exercise the change in the browser
```

If your change touches the agentic loop, the WebSocket bridges, or the
OpenAI session shape, please describe the manual test you ran in the PR.

## Licensing of contributions

By submitting a pull request you agree to license your contribution under
the [MIT License](LICENSE), the same license that covers the rest of the
project. No CLA is required.

## Security

Please **do not** open a public issue for vulnerabilities. Email the
maintainer directly (see the commit history for the address) and allow
reasonable time for a fix before any disclosure.

## Code of conduct

Be kind, be specific, assume good faith. We're all here because we find
this fun.
