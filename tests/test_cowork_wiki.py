"""Filesystem-layer tests for Cowork skills and the knowledge wiki.

These cover only the parts that don't touch the Anthropic API: the on-disk
Agent-Skill store and the wiki store. The LLM engine is exercised indirectly
via its graceful-degradation path (no credential -> friendly string).
"""
from __future__ import annotations

import asyncio

from her.cowork.skills_store import CoworkSkillStore, slugify
from her.memory.wiki.engine import WikiEngine
from her.memory.wiki.store import WikiStore


# ---------- CoworkSkillStore ---------------------------------------------


def test_skill_write_list_read_delete(tmp_path):
    store = CoworkSkillStore(tmp_path / "skills")
    slug = store.write_skill(
        "Send Weekly Report",
        "Use when the user asks to compile the weekly report",
        "# Weekly Report\n\nDo the thing.",
    )
    assert slug == "send-weekly-report"

    skills = store.list_skills()
    assert skills == [{
        "slug": "send-weekly-report",
        "name": "send-weekly-report",
        "description": "Use when the user asks to compile the weekly report",
    }]

    md = store.read_skill(slug)
    assert md.startswith("---")
    assert "name: send-weekly-report" in md
    assert "# Weekly Report" in md

    assert store.delete_skill(slug) is True
    assert store.list_skills() == []
    assert store.delete_skill(slug) is False


def test_skill_description_is_single_line(tmp_path):
    store = CoworkSkillStore(tmp_path / "skills")
    store.write_skill("X", "line one\nline two", "# X\n\nbody")
    md = store.read_skill("x")
    # The one-line description must not break the frontmatter block.
    assert "description: line one line two" in md


def test_slugify():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("  ") == "skill"


# ---------- WikiStore -----------------------------------------------------


def test_wiki_init_creates_scaffold(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    store.ensure_init()
    assert (tmp_path / "wiki" / "CLAUDE.md").exists()
    assert (tmp_path / "wiki" / "index.md").exists()
    assert (tmp_path / "wiki" / "log.md").exists()
    assert (tmp_path / "wiki" / "pages").is_dir()


def test_wiki_page_roundtrip_and_index(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    store.ensure_init()
    slug = store.write_page("costco", "Costco", "A wholesale retailer", "# Costco\n\nSee [[membership]].")
    assert slug == "costco"

    pages = store.list_pages()
    assert pages[0]["slug"] == "costco"
    assert pages[0]["title"] == "Costco"
    assert pages[0]["summary"] == "A wholesale retailer"

    body = store.page_body("costco")
    assert body.startswith("# Costco")
    assert "[[membership]]" in body

    store.rebuild_index()
    index = store.read_index()
    assert "[Costco](pages/costco.md)" in index
    assert "A wholesale retailer" in index

    assert store.delete_page("costco") is True
    assert store.list_pages() == []


def test_wiki_append_log(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    store.ensure_init()
    store.append_log("ingest", "Costco 10-K", "added revenue figures")
    text = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
    assert "ingest | Costco 10-K" in text
    assert "added revenue figures" in text


# ---------- WikiEngine graceful degradation -------------------------------


def test_wiki_engine_no_credential(monkeypatch):
    # With no Anthropic credential, every LLM op returns a friendly string and
    # never raises (so a session keeps running). This path short-circuits in
    # ``_ready()`` before touching the filesystem, so no store setup is needed.
    from her.cowork.client import client as cowork

    monkeypatch.setattr(cowork, "is_configured", lambda: False)
    eng = WikiEngine()

    out = asyncio.run(eng.query("anything"))
    assert "credential" in out.lower()
    out = asyncio.run(eng.ingest("some text", "src"))
    assert "credential" in out.lower()
