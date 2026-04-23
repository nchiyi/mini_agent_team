import logging
import numpy as np

from src.roles import load_roles

logger = logging.getLogger(__name__)

class RoleRouter:
    def __init__(self, roster_dir: str = "roster"):
        self.roster_dir = roster_dir
        self.roles = []
        self.embeddings = None
        self.model = None
        self._initialized = False

    def _lazy_init(self):
        if self._initialized:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self._load_roster()
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize RoleRouter: {e}")

    def _load_roster(self):
        summaries = []
        for slug, meta in load_roles().items():
            summary = meta.get("summary", "")
            if summary:
                self.roles.append({"slug": slug, "name": meta.get("name", slug)})
                summaries.append(summary)
        
        if summaries:
            self.embeddings = self.model.encode(summaries)

    def route(self, text: str, threshold: float = 0.5) -> str | None:
        """Match user text to the best role slug based on semantic similarity."""
        self._lazy_init()
        if not self._initialized or not self.roles or self.embeddings is None:
            return None

        try:
            query_embedding = self.model.encode([text])[0]
            # Simple cosine similarity (since embeddings are normalized by default in many models)
            similarities = np.dot(self.embeddings, query_embedding) / (
                np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(query_embedding)
            )
            
            best_idx = np.argmax(similarities)
            if similarities[best_idx] >= threshold:
                logger.info(f"Semantic match found: {self.roles[best_idx]['slug']} (score: {similarities[best_idx]:.2f})")
                return self.roles[best_idx]['slug']
        except Exception as e:
            logger.error(f"Routing error: {e}")
            
        return None
