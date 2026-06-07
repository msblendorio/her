"""Unit tests for AST (Auto Self-Training) — the zero-GPU Phase 0/1 surface."""
from __future__ import annotations

from her.ast.redact import redact
from her.ast.style import StyleCard, build_style_card


# ---------- redaction (privacy) ------------------------------------------


def test_redact_api_keys():
    assert "sk-ant-" not in redact("key sk-ant-abcdef1234567890XYZ")
    assert "[redacted]" in redact("key sk-ant-abcdef1234567890XYZ")


def test_redact_labelled_code_form():
    assert redact("password: hunter2") == "password: [redacted]"
    assert redact("pwd=bar123") == "pwd=[redacted]"


def test_redact_natural_language_password():
    # The form a user actually dictates — verb, not ':' (it/en/de/es).
    assert "hunter2" not in redact("la mia password è hunter2 non dirla")
    assert "s3cr3t" not in redact("my password is s3cr3t!")
    assert "geheim123" not in redact("mein Passwort ist geheim123")
    assert "abc123" not in redact("mi contraseña es abc123")


def test_redact_credit_card():
    assert "4111" not in redact("carta 4111 1111 1111 1111")


def test_redact_leaves_plain_text_untouched():
    assert redact("ciao come stai") == "ciao come stai"
    # 'pin'/'es' without a value must not trigger over-redaction.
    assert redact("la casa es grande e il pin del telefono") == \
        "la casa es grande e il pin del telefono"


# ---------- Style Card (deterministic features) --------------------------


def _turns(pairs, lang="it"):
    out = []
    for u, a in pairs:
        out.append({"role": "user", "text": u, "lang": lang, "session_id": "s"})
        out.append({"role": "assistant", "text": a, "lang": lang, "session_id": "s"})
    return out


def test_style_card_detects_terse_informal_emoji():
    card = build_style_card(_turns([
        ("ciao 😀", "Bene!"), ("ok raga", "👍"), ("grazie", "prego"),
    ]))
    assert card.length_pref == "terse"
    assert card.register == "informal"
    assert card.emoji is True
    assert card.languages == {"it": 1.0}


def test_style_card_empty_returns_previous():
    prev = StyleCard(register="formal", turns_observed=5)
    assert build_style_card([], prev) is prev


def test_style_card_phrases_exclude_redaction_placeholder():
    # Capture stores already-redacted text, so the Style Card sees "[redacted]";
    # the placeholder must never surface as a "recurring expression".
    card = build_style_card(_turns([
        ("la mia password è [redacted]", "ok"),
        ("altra password è [redacted] davvero", "capito"),
        ("ancora [redacted] qui", "ok"),
    ]))
    assert "redacted" not in card.top_phrases


def test_style_card_prompt_block_renders_and_is_bounded():
    card = build_style_card(_turns([("ciao bello", "ehi")]))
    block = card.to_prompt_block(token_budget=800, language="it")
    assert "Style Card" in block
    assert len(block) <= 800 * 4
