"""Seed the vector store with the existing backlog.

Loads ``tests/fixtures/seed_backlog.json`` and upserts every defect into the
Chroma collection, storing ``defect_id`` and ``status`` in metadata (status
drives the duplicate-vs-regression decision in ``check_duplicate``).

Idempotent — upsert means it's safe to re-run. Requires ``OPENAI_API_KEY`` for
embeddings. Run once before the duplicate/regression tests:

    python scripts/seed_vector_store.py
"""

import json
from pathlib import Path

from dotenv import load_dotenv

from app.tools.vector_store import get_vector_store

FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "seed_backlog.json"
)


def main():
    load_dotenv()  # pull OPENAI_API_KEY (and friends) from .env
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    defects = data["defects"]

    store = get_vector_store()
    written = store.add_defects(defects)
    print(
        f"Seeded {written} defect(s) into the vector store "
        f"(collection now holds {store.count()})."
    )
    for d in defects:
        print(f"  - {d['defect_id']:<8} [{d['status']:<11}] {d['title']}")


if __name__ == "__main__":
    main()
