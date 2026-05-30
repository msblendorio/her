# Cowork integration + Knowledge-base LLM wiki

Two features added to **her** (Samantha):

1. **Cowork connection & skill authoring** — Samantha can delegate open-ended
   knowledge-work tasks to **Claude / Claude Cowork**, and *author new Agent
   Skills* (`SKILL.md` folders) that Cowork and Claude Code pick up
   automatically from `~/.claude/skills/`.
2. **Knowledge-base memory as an LLM wiki** — a persistent, interlinked
   markdown wiki maintained by Claude, following Andrej Karpathy's
   [LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
   (ingest / query / lint over `index.md`, `log.md`, and `pages/`).

Both are powered by the **Anthropic API** (the `anthropic` Python SDK), so they
share one credential layer and one client.

---

## 1. Credentials (both API key *and* Pro/Max subscription)

Resolution order in `CoworkClient`:

1. `settings.anthropic_api_key` (env `ANTHROPIC_API_KEY`) — pay-per-use API key.
2. `settings.anthropic_auth_token` (env `ANTHROPIC_AUTH_TOKEN`) — OAuth token
   from a Claude Pro/Max subscription (`ant auth login` / Claude Code login,
   `sk-ant-oat...`).
3. SDK environment fallback.

The desktop launcher prompts for an Anthropic key the same way it already
prompts for the OpenAI key (optional — Cowork features stay dormant until a
credential is present). If neither is set, the Cowork/wiki tools return a
friendly "configure your Anthropic credentials" message instead of failing.

Model default: **`claude-opus-4-8`** with **adaptive thinking**, **streaming**,
and **prompt caching** on the stable system prefix.

---

## 2. Cowork — `src/her/cowork/`

| File | Responsibility |
|------|----------------|
| `client.py` | `CoworkClient` — thin async wrapper over `anthropic.AsyncAnthropic`. `is_configured()`, `credential_kind()`, `run_task()` (delegate a knowledge-work task), `author_skill()` (generate `SKILL.md` body via structured output). |
| `skills_store.py` | `CoworkSkillStore` — read/write `~/.claude/skills/<slug>/SKILL.md` (+ optional bundled files), parse YAML frontmatter, list/delete. |
| `tools.py` | Agentic voice tools (registered via `@tool`). |

### Agent-Skill layout written by her

```
~/.claude/skills/
  <slug>/
    SKILL.md          # YAML frontmatter: name, description (required) + body
```

`SKILL.md` shape:

```markdown
---
name: <slug>
description: <one line — when/why Claude should use this skill>
---

# <Title>

<instructions, steps, resources…>
```

### Voice tools

| Tool | Safe? | What it does |
|------|-------|--------------|
| `cowork_status` | yes | Whether credentials are present and which kind; skill count. |
| `list_cowork_skills` | yes | Enumerate installed Cowork skills (name, description, slug). |
| `create_cowork_skill(name, description, instructions)` | no | Ask Claude to write a well-formed `SKILL.md` and install it under `~/.claude/skills/`. |
| `run_cowork_task(task, context)` | no | Delegate a multi-step knowledge-work task to Claude (Cowork engine) and summarize the result aloud. |

A short, multilingual **Cowork addendum** is appended to the realtime system
prompt when `cowork_enabled` and credentials are present, so Samantha knows she
can delegate and author skills.

---

## 3. Knowledge wiki — `src/her/memory/wiki/`

Karpathy's three layers:

- **Raw sources** — what the user gives her (text, transcripts). Never mutated.
- **Wiki** — `data/wiki/pages/<slug>.md`, plus `index.md` (catalog) and
  `log.md` (append-only ingest/query/lint log). Claude owns this layer.
- **Schema** — `data/wiki/CLAUDE.md`, the conventions/protocol doc, created on
  first init.

| File | Responsibility |
|------|----------------|
| `store.py` | `WikiStore` — filesystem ops: `ensure_init()`, page CRUD, `read_index()`/`write_index()`, `append_log()`. |
| `engine.py` | `WikiEngine` — uses `CoworkClient` for the three LLM operations. |
| `tools.py` | Agentic voice tools. |

### Operations (engine, via Claude, structured output)

- **ingest(text, title)** — Claude reads the source + current index + relevant
  pages and returns a set of page upserts (`{slug, title, action, content}`);
  the store applies them and logs `ingest`.
- **query(question)** — Claude reads the index + relevant pages, answers with
  citations, and may file a new page; logs `query`.
- **lint()** — Claude flags contradictions, stale claims, orphan pages, missing
  cross-links; logs `lint`.

### Voice tools

| Tool | Safe? | What it does |
|------|-------|--------------|
| `wiki_list_pages` | yes | List wiki page titles/slugs (pure filesystem). |
| `wiki_read_page(slug)` | yes | Read one page (pure filesystem). |
| `wiki_ingest(text, title)` | no | Fold a new source into the wiki via Claude. |
| `wiki_query(question)` | yes | Ask a question against the wiki via Claude. |
| `wiki_lint` | no | Health-check pass via Claude. |

### Recall integration

At session start the orchestrator appends a tiny **knowledge-base overview**
(page titles only, capped) to the recall block, so Samantha knows the KB exists
and can `wiki_query` it. Kept short on purpose (token budget).

---

## 4. Config additions (`config.py` / `.env.example`)

```
# Cowork / Anthropic
anthropic_api_key      ANTHROPIC_API_KEY        ""
anthropic_auth_token   ANTHROPIC_AUTH_TOKEN     ""   # Claude Pro/Max OAuth token
anthropic_model        ANTHROPIC_MODEL          "claude-opus-4-8"
cowork_enabled         COWORK_ENABLED           true
cowork_skills_path     COWORK_SKILLS_PATH       "~/.claude/skills"

# Knowledge wiki
wiki_enabled           WIKI_ENABLED             true
wiki_path              WIKI_PATH                "data/wiki"
wiki_max_context_pages WIKI_MAX_CONTEXT_PAGES   12
```

Dependency added: `anthropic>=0.49` (Python SDK).

---

## 5. Wiring

- `agentic/__init__.py` registration block imports `her.cowork.tools` and
  `her.memory.wiki.tools` so their `@tool`s register.
- `i18n.py` gains `cowork_addendum()` and `wiki_overview_*` helpers (it/en/es/fr/de).
- `reasoning/realtime_session.py` appends the Cowork addendum.
- `core/orchestrator.py` appends the wiki overview to the recall block.
- `server/app.py` gains read-only `GET /api/cowork` and `GET /api/wiki`.
- `desktop/launcher.py` optionally prompts for the Anthropic key.
