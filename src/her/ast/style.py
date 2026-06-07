"""Phase 1 — the Style Card.

A small, measurable profile of *how* the user talks and how they like Samantha
to answer, distilled from the captured raw turns (§5.1 of the design). It sits
one notch below ``CharacterProfile`` in the personalization stack: the character
profile is about *who* the user is (empathy), the Style Card is about *style*
(length, register, lexicon, emoji, language mix) and is injected into both
teachers' prompts as in-context personalization (T2).

The measurable features are computed deterministically (no LLM, no GPU) so the
card is cheap to rebuild every consolidation. An optional one-line "voice"
description can be enriched by a cheap chat model in the slow loop, but the card
is fully useful without it.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from .store import now_iso

# Tiny multilingual stop-list (it/en/es/fr/de) so "top phrases" surface content
# words rather than glue. Deliberately short — this is signal, not linguistics.
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "is",
    "are", "be", "i", "you", "it", "that", "this", "with", "my", "me", "we",
    "il", "lo", "la", "le", "un", "una", "di", "che", "e", "per", "non", "mi",
    "ti", "ci", "si", "con", "ho", "ha", "sono", "del", "della", "al", "come",
    "el", "los", "las", "y", "de", "que", "en", "un", "por", "con", "se",
    "le", "les", "des", "et", "à", "un", "une", "pour", "je", "tu", "der",
    "die", "das", "und", "ich", "du", "ist", "den", "ein", "eine",
}
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
_WORD = re.compile(r"[\wàèéìòùáíóúñüöä']+", re.UNICODE)


@dataclass
class StyleCard:
    version: int = 1
    updated_at: str = ""
    sessions_observed: int = 0
    turns_observed: int = 0
    # Measured response-length preference (proxy: how long the user writes, and
    # how long the accepted assistant turns ran).
    avg_user_chars: int = 0
    avg_assistant_chars: int = 0
    length_pref: str = "balanced"      # terse | balanced | verbose
    register: str = "neutral"          # informal | neutral | formal
    emoji: bool = False                # does the user use emoji?
    languages: dict[str, float] = field(default_factory=dict)  # lang -> share
    top_phrases: list[str] = field(default_factory=list)
    voice: str = ""                    # optional one-line LLM enrichment

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StyleCard":
        known = {f for f in cls().__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def is_empty(self) -> bool:
        return self.turns_observed <= 0

    def to_prompt_block(self, token_budget: int = 800, language: str = "it") -> str:
        """Render the card as a compact instruction block for the system prompt.

        Localized lightly (it/en) so it reads naturally inside the persona
        prompt; falls back to English. Kept well under ``token_budget`` chars*4.
        """
        if self.is_empty():
            return ""
        lang = (language or "it").lower()[:2]
        length = {
            "terse": {"it": "molto conciso", "en": "very concise"},
            "balanced": {"it": "equilibrato", "en": "balanced"},
            "verbose": {"it": "disteso e dettagliato", "en": "expansive, detailed"},
        }[self.length_pref]
        register = {
            "informal": {"it": "informale, alla pari", "en": "informal, peer-to-peer"},
            "neutral": {"it": "naturale", "en": "natural"},
            "formal": {"it": "formale, curato", "en": "formal, polished"},
        }[self.register]

        def L(it: str, en: str) -> str:
            return it if lang == "it" else en

        lines = [L("— Style Card (come parla l'utente, impara a rispecchiarla) —",
                   "— Style Card (how the user talks; mirror it) —")]
        lines.append("• " + L("Lunghezza risposte", "Answer length") + ": " +
                     (length.get(lang) or length["en"]) + ".")
        lines.append("• " + L("Registro", "Register") + ": " +
                     (register.get(lang) or register["en"]) + ".")
        if self.emoji:
            lines.append("• " + L("Usa occasionalmente emoji, come fa l'utente.",
                                  "Occasional emoji are welcome, as the user uses them."))
        if self.languages:
            top = sorted(self.languages.items(), key=lambda kv: -kv[1])
            langs = ", ".join(f"{k} ({int(v*100)}%)" for k, v in top[:3])
            lines.append("• " + L("Lingue", "Languages") + ": " + langs + ".")
        if self.top_phrases:
            lines.append("• " + L("Espressioni ricorrenti", "Recurring expressions") +
                         ": " + ", ".join(self.top_phrases[:8]) + ".")
        if self.voice:
            lines.append("• " + self.voice)
        block = "\n".join(x for x in lines if x)
        return block[: max(200, token_budget * 4)]


def _classify_length(avg_user: float, avg_asst: float) -> str:
    # Use the user's own brevity as the strongest cue for what they want back.
    if avg_user < 60:
        return "terse"
    if avg_user > 220:
        return "verbose"
    return "balanced"


def _classify_register(texts: list[str], emoji: bool) -> str:
    blob = " ".join(texts).lower()
    informal_cues = ("ahah", "lol", "cmq", "boh", "raga", "ok dai", "ciao", "hey", "yo")
    formal_cues = ("cordiali saluti", "gentilmente", "la ringrazio", "regards", "sincerely")
    score = 0
    if emoji:
        score -= 1
    score -= sum(1 for c in informal_cues if c in blob)
    score += sum(2 for c in formal_cues if c in blob)
    if score <= -1:
        return "informal"
    if score >= 2:
        return "formal"
    return "neutral"


def build_style_card(turns: list[dict], previous: StyleCard | None = None) -> StyleCard:
    """Compute a fresh Style Card from captured raw-turn records.

    ``turns`` are records as written by ``capture.AstCapture`` (dicts with
    ``role``/``text``/``lang``). Deterministic and cheap.
    """
    user_texts = [t.get("text", "") for t in turns if t.get("role") == "user" and t.get("text")]
    asst_texts = [t.get("text", "") for t in turns if t.get("role") == "assistant" and t.get("text")]
    if not user_texts:
        return previous or StyleCard()

    avg_user = sum(len(x) for x in user_texts) / max(1, len(user_texts))
    avg_asst = sum(len(x) for x in asst_texts) / max(1, len(asst_texts)) if asst_texts else 0.0
    emoji = any(_EMOJI.search(x) for x in user_texts)

    # Language mix from the per-turn lang tags.
    langs = Counter(t.get("lang") for t in turns if t.get("role") == "user" and t.get("lang"))
    total_lang = sum(langs.values())
    languages = {k: round(v / total_lang, 3) for k, v in langs.items()} if total_lang else {}

    # Top recurring content words/bigrams across user turns.
    words = [w.lower() for x in user_texts for w in _WORD.findall(x)]
    # Drop stop-words, very short tokens, and the redaction placeholder so a
    # secret's position never surfaces as a "recurring expression".
    content = [w for w in words if w not in _STOP and len(w) > 2 and w != "redacted"]
    freq = Counter(content)
    top_phrases = [w for w, _ in freq.most_common(10)]

    sessions = len({t.get("session_id") for t in turns if t.get("session_id")})

    return StyleCard(
        version=(previous.version + 1) if previous else 1,
        updated_at=now_iso(),
        sessions_observed=sessions,
        turns_observed=len(turns),
        avg_user_chars=int(avg_user),
        avg_assistant_chars=int(avg_asst),
        length_pref=_classify_length(avg_user, avg_asst),
        register=_classify_register(user_texts, emoji),
        emoji=emoji,
        languages=languages,
        top_phrases=top_phrases,
        voice=previous.voice if previous else "",
    )
