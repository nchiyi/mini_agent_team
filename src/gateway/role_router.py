# src/gateway/role_router.py
"""
Semantic role router — matches user intent to roster roles.

Strategy (in order):
  1. FastEmbed (ONNX) — lightweight local embeddings (<150 MB)
  2. Heuristic keyword matching against role summaries — zero-dependency fallback
"""
import logging
import re

import numpy as np

from src.roles import load_roles

logger = logging.getLogger(__name__)


def _cosine_similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _heuristic_score(text: str, summary: str) -> float:
    """Simple word-overlap score: |intersection| / |union|."""
    stop = {"the", "a", "an", "is", "are", "to", "for", "and", "or", "of", "in", "with"}
    text_words = {w for w in re.findall(r"\w+", text.lower()) if w not in stop}
    summary_words = {w for w in re.findall(r"\w+", summary.lower()) if w not in stop}
    if not text_words or not summary_words:
        return 0.0
    intersection = text_words & summary_words
    union = text_words | summary_words
    return len(intersection) / len(union)


class RoleRouter:
    """
    Routes natural language user messages to roster role slugs.

    Tries FastEmbed first; falls back to heuristic keyword overlap.
    Returns None when no role exceeds its threshold.
    """

    SEMANTIC_THRESHOLD = 0.45
    HEURISTIC_THRESHOLD = 0.12

    def __init__(self, roster_dir: str = "roster"):
        self.roster_dir = roster_dir
        self._roles: list[dict] = []
        self._summaries: list[str] = []
        self._embeddings: "np.ndarray | None" = None
        self._embed_fn = None  # callable: (texts: list[str]) -> np.ndarray
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _lazy_init(self) -> None:
        if self._initialized:
            return
        self._initialized = True  # prevent re-entry on failure
        self._load_roster()
        self._try_fastembed()

    def _load_roster(self) -> None:
        for slug, meta in load_roles().items():
            summary = meta.get("summary", "")
            if summary:
                self._roles.append({"slug": slug, "name": meta.get("name", slug)})
                self._summaries.append(summary)

    def _try_fastembed(self) -> None:
        if not self._summaries:
            return
        try:
            from fastembed import TextEmbedding
            model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

            def _embed(texts: list[str]) -> "np.ndarray":
                return np.array(list(model.embed(texts)))

            self._embed_fn = _embed
            self._embeddings = _embed(self._summaries)
            logger.info("RoleRouter: FastEmbed initialised (%d roles)", len(self._roles))
        except Exception as e:
            logger.info("RoleRouter: FastEmbed unavailable (%s), using heuristics", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warm_up(self) -> None:
        """Call at bot startup so the first real message has no cold-start penalty."""
        self._lazy_init()

    def route(self, text: str, threshold: float | None = None) -> str | None:
        """
        Return the best matching role slug, or None if confidence is below threshold.
        Falls back from semantic to heuristic matching automatically.
        """
        self._lazy_init()
        if not self._roles:
            return None

        if self._embed_fn is not None and self._embeddings is not None:
            sem_threshold = threshold if threshold is not None else self.SEMANTIC_THRESHOLD
            result = self._semantic_route(text, sem_threshold)
            if result is not None:
                return result

        # Heuristic fallback
        heu_threshold = threshold if threshold is not None else self.HEURISTIC_THRESHOLD
        return self._heuristic_route(text, heu_threshold)

    # ------------------------------------------------------------------
    # Internal strategies
    # ------------------------------------------------------------------

    def _semantic_route(self, text: str, threshold: float) -> str | None:
        try:
            query_vec = self._embed_fn([text])[0]
            scores = np.array([
                _cosine_similarity(self._embeddings[i], query_vec)
                for i in range(len(self._roles))
            ])
            best = int(np.argmax(scores))
            if scores[best] >= threshold:
                slug = self._roles[best]["slug"]
                logger.debug("Semantic match: %s (%.2f)", slug, scores[best])
                return slug
        except Exception as e:
            logger.warning("Semantic routing error: %s", e)
        return None

    def _heuristic_route(self, text: str, threshold: float) -> str | None:
        best_score = 0.0
        best_slug = None
        for role, summary in zip(self._roles, self._summaries):
            score = _heuristic_score(text, summary)
            if score > best_score:
                best_score = score
                best_slug = role["slug"]
        if best_slug and best_score >= threshold:
            logger.debug("Heuristic match: %s (%.2f)", best_slug, best_score)
            return best_slug
        return None
