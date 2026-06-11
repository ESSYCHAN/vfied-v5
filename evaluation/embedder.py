"""
Embedder backends (MIGRATION.md Step 2 + cost-boundary fixed decision).

VFIED never serves inference on its own account, so semantic scoring must default
to a LOCAL embedder at fixed hosting cost. A customer-supplied embedding key is an
enterprise override only.

Every backend exposes a stable `embedder_id`. Embedding vectors are NOT comparable
across embedder models, so this id MUST be stored alongside any anchor/experiment
(semantic_anchors.embedder_id, experiment_runs.embedder_id). Comparing vectors
built by different embedders is a correctness bug, which the id lets us detect.

Backends:
  - LocalEmbedder: sentence-transformers (BGE/E5-small class), CPU, $0 marginal.
    Production default. Falls back to HashingEmbedder if the library is absent so
    the code runs in dev without a heavy install.
  - HashingEmbedder: dependency-free deterministic embedding. NOT semantically
    meaningful — dev/test fallback only. Its id is namespaced so it can never be
    mistaken for (or compared against) real anchors.
  - OpenAIEmbedder: enterprise override, customer key. Per-call cost on the
    customer's account, never VFIED's.
"""
import hashlib
import math
import os
from abc import ABC, abstractmethod
from typing import List, Optional


class Embedder(ABC):
    @property
    @abstractmethod
    def embedder_id(self) -> str:
        """Stable identity stored with anchors. Vectors are only comparable
        within the same embedder_id."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        raise NotImplementedError


class HashingEmbedder(Embedder):
    """Deterministic, dependency-free fallback. Not semantically meaningful —
    a feature-hashing bag-of-tokens projected to fixed dimensions. Used only when
    no real local model is installed, so dev/CI can run the full pipeline."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    @property
    def embedder_id(self) -> str:
        # Namespaced so anchors built this way are never compared with real ones.
        return f"hashing-dev-v1:{self.dim}"

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


class LocalEmbedder(Embedder):
    """Local sentence-transformers model (BGE/E5-small class), CPU. Production
    default — fixed hosting cost, $0 marginal per run."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer  # soft dep
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    @property
    def embedder_id(self) -> str:
        return f"local:{self.model_name}"

    def embed(self, text: str) -> List[float]:
        vec = self._model.encode(text[:2000], normalize_embeddings=True)
        return vec.tolist()


class OpenAIEmbedder(Embedder):
    """Enterprise override: customer-supplied embedding key. Cost lands on the
    customer's account, never VFIED's."""

    def __init__(self, api_key: str, model_name: str = "text-embedding-3-small"):
        from openai import OpenAI  # soft dep
        self.model_name = model_name
        self._client = OpenAI(api_key=api_key)

    @property
    def embedder_id(self) -> str:
        return f"openai:{self.model_name}"

    def embed(self, text: str) -> List[float]:
        r = self._client.embeddings.create(input=[text[:2000]], model=self.model_name)
        return r.data[0].embedding


_default_embedder: Optional[Embedder] = None


def get_embedder(embedding_key: Optional[str] = None) -> Embedder:
    """Resolve the embedder for a run.

    Precedence:
      1. Explicit customer embedding key  -> OpenAIEmbedder (enterprise override).
      2. Local sentence-transformers model -> LocalEmbedder (production default).
      3. HashingEmbedder                   -> dependency-free dev fallback.

    The default (no key) is local-first, so VFIED's per-run cost stays ~zero.
    """
    if embedding_key:
        return OpenAIEmbedder(api_key=embedding_key)

    global _default_embedder
    if _default_embedder is None:
        model_name = os.getenv("VFIED_LOCAL_EMBEDDER", "BAAI/bge-small-en-v1.5")
        try:
            _default_embedder = LocalEmbedder(model_name=model_name)
        except Exception:
            # sentence-transformers not installed (dev/CI) — fall back so the
            # pipeline still runs. Production installs the library.
            _default_embedder = HashingEmbedder()
    return _default_embedder
