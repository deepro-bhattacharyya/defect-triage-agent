"""ChromaDB vector store wrapper for duplicate / regression detection.

`check_duplicate` (see docs/PROJECT_PLAN.md) depends on this exact contract:

    results = get_vector_store().similarity_search_with_score(query, k=5)
    for doc, score in results:
        if score < SIMILARITY_THRESHOLD: ...      # higher score == more similar
        doc.metadata["status"], doc.metadata["defect_id"]

So `similarity_search_with_score` returns `(Document, similarity)` pairs where
**similarity is in [0, 1] and HIGHER means more alike** (>= 0.88 is a match).

Chroma natively returns a *distance* (lower == closer). We configure the
collection for cosine space and convert: ``similarity = 1 - cosine_distance``,
so callers can compare against the 0.88 threshold directly.

Embeddings use OpenAI ``text-embedding-3-small`` (needs ``OPENAI_API_KEY``). The
embedder is injectable so unit tests can mock it and run offline.
"""

import os
from dataclasses import dataclass, field

import chromadb

from app.tools.certs import configure_corporate_tls

COLLECTION_NAME = "defect_backlog"
DEFAULT_PERSIST_DIR = "./.chroma"

# Embeddings: Gemini only (this POC standardizes on Google; OpenAI is blocked on
# the corporate network). gemini-embedding-001 is 3072-dim — if you ever change
# the model, re-seed the store (delete .chroma) since the vector size changes.
GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"


def _build_default_embedder():
    """Construct the Gemini embedder. Sets up corporate TLS first so the HTTPS
    call verifies against the proxy's certificate."""
    configure_corporate_tls()
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL)


@dataclass
class Document:
    """LangChain-style document: `.page_content` + `.metadata` (what nodes read)."""

    page_content: str
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """Thin wrapper over a Chroma collection that speaks similarity, not distance."""

    def __init__(self, persist_dir=None, embedder=None, client=None,
                 collection_name=COLLECTION_NAME):
        self._embedder = embedder  # lazily defaults to OpenAIEmbeddings
        if client is not None:
            self._client = client
        else:
            persist_dir = persist_dir or os.environ.get(
                "CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR
            )
            self._client = chromadb.PersistentClient(path=persist_dir)
        # cosine space => distance in [0, 2]; similarity = 1 - distance
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def embedder(self):
        if self._embedder is None:
            # Built lazily so unit tests that inject a fake embedder never
            # construct a real provider client (and never need an API key).
            self._embedder = _build_default_embedder()
        return self._embedder

    def add_defects(self, defects):
        """Upsert backlog defects. `status` + `defect_id` go into metadata
        because they drive the duplicate-vs-regression decision downstream.

        Upsert (not add) makes seeding idempotent and safe to re-run.
        Returns the number of defects written.
        """
        ids, documents, metadatas = [], [], []
        for d in defects:
            ids.append(d["defect_id"])
            documents.append(f"{d['title']} {d['description']}")
            metadatas.append(
                {
                    "defect_id": d["defect_id"],
                    "status": d.get("status", ""),
                    "component": d.get("component", ""),
                    "severity": d.get("severity", ""),
                    "title": d.get("title", ""),
                }
            )
        if not ids:
            return 0
        self._collection.upsert(
            ids=ids,
            embeddings=self.embedder.embed_documents(documents),
            documents=documents,
            metadatas=metadatas,
        )
        return len(ids)

    def similarity_search_with_score(self, query, k=5):
        """Return up to `k` `(Document, similarity)` pairs, most similar first.

        `similarity` is ``1 - cosine_distance`` (∈ [0, 1] for non-negative
        embeddings; >= SIMILARITY_THRESHOLD means a match).
        """
        result = self._collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        def _first(key):
            values = result.get(key) or [[]]
            return values[0] if values else []

        documents = _first("documents")
        metadatas = _first("metadatas")
        distances = _first("distances")

        pairs = []
        for content, metadata, distance in zip(documents, metadatas, distances):
            similarity = 1.0 - float(distance)
            pairs.append((Document(page_content=content, metadata=metadata or {}), similarity))
        return pairs

    def count(self):
        return self._collection.count()


_VECTOR_STORE = None


def get_vector_store():
    """Process-wide singleton used by the graph nodes."""
    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        _VECTOR_STORE = VectorStore()
    return _VECTOR_STORE
