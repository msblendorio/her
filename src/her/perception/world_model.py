"""World-model interface — placeholder for Meta V-JEPA 2 / V-JEPA AC.

Why this exists
---------------
V-JEPA 2 (Meta, 2025) is a self-supervised video world model that predicts
future representations of a scene in latent space. The "AC" variant adds
action-conditioning. Plugging it in here would let the assistant build
"anticipation embeddings" — a coarse sense of what is *about to happen* — and
feed them into the Realtime session as extra textual context.

The repo ships with a `MockWorldModel` so the rest of the system can be wired
end-to-end without downloading ~1 GB of weights or requiring a GPU. To swap in
the real model:

1. `pip install timm`
2. Download V-JEPA 2 weights:
   https://github.com/facebookresearch/jepa
3. Replace `JEPAWorldModel.encode_scene` / `predict_next` with real calls to
   the loaded encoder / predictor.
4. Set `WORLD_MODEL_ENABLED=true` in `.env` and the orchestrator will start
   using the real model.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..config import settings

log = logging.getLogger(__name__)


@dataclass
class SceneEmbedding:
    """Latent representation of the current scene."""
    vector: np.ndarray  # shape (D,)
    timestamp: float


@dataclass
class Anticipation:
    """A short textual summary of what the world model thinks is about to happen."""
    summary: str
    confidence: float  # 0..1


class WorldModel(ABC):
    @abstractmethod
    async def encode_scene(self, image) -> SceneEmbedding: ...

    @abstractmethod
    async def predict_next(self, embedding: SceneEmbedding) -> Anticipation: ...


class MockWorldModel(WorldModel):
    """No-op implementation: returns random embeddings and a neutral anticipation.

    Lets the orchestrator's wiring stay correct while shipping without GPU
    dependencies.
    """

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    async def encode_scene(self, image) -> SceneEmbedding:
        from time import monotonic
        return SceneEmbedding(
            vector=np.random.default_rng().standard_normal(self.dim).astype("float32"),
            timestamp=monotonic(),
        )

    async def predict_next(self, embedding: SceneEmbedding) -> Anticipation:
        return Anticipation(summary="(world model disabled — mock)", confidence=0.0)


class JEPAWorldModel(WorldModel):
    """Real V-JEPA 2 integration — NOT implemented yet, kept as a hook.

    See module docstring for the steps to wire this up.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "JEPAWorldModel is a placeholder. See perception/world_model.py docstring "
            "for instructions on plugging in Meta V-JEPA 2."
        )

    async def encode_scene(self, image) -> SceneEmbedding: ...  # noqa: D401
    async def predict_next(self, embedding: SceneEmbedding) -> Anticipation: ...


def build_world_model() -> WorldModel:
    if settings.world_model_enabled:
        log.info("instantiating real JEPA world model")
        return JEPAWorldModel()
    log.info("using MockWorldModel (V-JEPA disabled)")
    return MockWorldModel()
