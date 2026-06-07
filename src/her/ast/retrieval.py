"""Phase 1 — few-shot retrieval over the captured raw turns (T1).

Embeds past ``(user → assistant)`` exchanges with a small local multilingual
model (``multilingual-e5-small``, ~118M) and keeps them in a light on-disk
index (a numpy matrix + a jsonl of the exchange texts). At inference time the
most relevant exchanges can be pulled in as dynamic few-shot examples to steer
either teacher toward the user's own voice.

The embedder is an **optional dependency** (the ``ast`` extra). If
``sentence-transformers`` isn't installed the whole module degrades gracefully:
``available()`` returns ``False``, indexing is a no-op, and selection returns an
empty list — so Phase 0 capture and the (deterministic) Style Card keep working
without it. The model is loaded lazily on first use and cached process-wide.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import settings
from .store import AstStore

log = logging.getLogger(__name__)

_EMBED_FILE = "exchanges.npy"
_META_FILE = "exchanges.jsonl"

_model = None          # cached SentenceTransformer
_model_failed = False  # don't retry a missing/broken dependency every call


def available() -> bool:
    """True if the embedder can be loaded (dependency present + model loads)."""
    return _load_model() is not None


def _load_model():
    global _model, _model_failed
    if _model is not None:
        return _model
    if _model_failed:
        return None
    try:
        import numpy as np  # noqa: F401  (index needs it too; check early)
        from sentence_transformers import SentenceTransformer
    except Exception:
        log.info(
            "ast: retrieval embedder unavailable (install the `ast` extra for "
            "few-shot retrieval); Style Card still works"
        )
        _model_failed = True
        return None
    try:
        _model = SentenceTransformer(settings.ast_embedding_model)
        log.info("ast: loaded retrieval embedder %s", settings.ast_embedding_model)
        return _model
    except Exception:
        log.exception("ast: failed to load embedder %s", settings.ast_embedding_model)
        _model_failed = True
        return None


def _exchanges_from_turns(turns: list[dict]) -> list[dict]:
    """Pair each user turn with the assistant turn that follows it."""
    pairs: list[dict] = []
    pending_user: dict | None = None
    for t in turns:
        role = t.get("role")
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if role == "user":
            pending_user = t
        elif role == "assistant" and pending_user is not None:
            pairs.append({
                "user": pending_user.get("text", ""),
                "assistant": text,
                "lang": pending_user.get("lang", t.get("lang", "")),
                "session_id": t.get("session_id", ""),
            })
            pending_user = None
    return pairs


class Retrieval:
    def __init__(self, store: AstStore) -> None:
        self.store = store

    @property
    def _npy(self) -> Path:
        return self.store.index_dir / _EMBED_FILE

    @property
    def _meta(self) -> Path:
        return self.store.index_dir / _META_FILE

    # ── build ────────────────────────────────────────────────────────────
    def reindex(self, turns: list[dict]) -> int:
        """Rebuild the exchange index from raw turns. Returns #exchanges indexed
        (0 if the embedder is unavailable or there's nothing to index)."""
        model = _load_model()
        if model is None:
            return 0
        import numpy as np

        exchanges = _exchanges_from_turns(turns)
        if not exchanges:
            return 0
        # We retrieve on the *user* message (that's what a live query looks like).
        # e5 wants a "query:" / "passage:" prefix; use "passage:" for the corpus.
        corpus = [f"passage: {e['user']}" for e in exchanges]
        try:
            vecs = model.encode(corpus, normalize_embeddings=True)
        except Exception:
            log.exception("ast: embedding the corpus failed")
            return 0
        self.store.index_dir.mkdir(parents=True, exist_ok=True)
        np.save(self._npy, np.asarray(vecs, dtype="float32"))
        with self._meta.open("w", encoding="utf-8") as f:
            for e in exchanges:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        log.info("ast: reindexed %d exchanges for retrieval", len(exchanges))
        return len(exchanges)

    # ── query ────────────────────────────────────────────────────────────
    def _load_index(self):
        if not self._npy.exists() or not self._meta.exists():
            return None, []
        try:
            import numpy as np
            mat = np.load(self._npy)
        except Exception:
            return None, []
        meta = self.store.read_turns(self._meta)  # read_turns parses jsonl lines
        return mat, meta

    def select_fewshot(self, query: str, k: int | None = None) -> list[dict]:
        """Return up to ``k`` past exchanges most similar to ``query`` (cosine).

        Empty list if the embedder/index is unavailable — callers should treat
        few-shot as best-effort enrichment, never a hard dependency.
        """
        k = k or settings.ast_fewshot_k
        model = _load_model()
        if model is None or not query.strip():
            return []
        mat, meta = self._load_index()
        if mat is None or not meta:
            return []
        import numpy as np
        try:
            q = model.encode([f"query: {query}"], normalize_embeddings=True)
            sims = (np.asarray(q, dtype="float32") @ mat.T)[0]
            top = np.argsort(-sims)[:k]
        except Exception:
            log.exception("ast: few-shot selection failed")
            return []
        return [meta[i] for i in top if 0 <= i < len(meta)]

    def representative(self, k: int | None = None) -> list[dict]:
        """Session-start few-shot when there's no live query yet: the most recent
        complete exchanges. Works even without the embedder (reads the meta
        jsonl, or falls back to deriving pairs from raw turns)."""
        k = k or settings.ast_fewshot_k
        _, meta = self._load_index()
        if meta:
            return meta[-k:]
        # No index yet (embedder absent) — derive recent pairs straight from raw.
        pairs = _exchanges_from_turns(self.store.recent_turns(max_sessions=5))
        return pairs[-k:]
