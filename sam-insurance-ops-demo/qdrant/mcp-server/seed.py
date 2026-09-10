#!/usr/bin/env python3
"""Seed the Acme Claims Knowledge collection (one-shot compose service
acme-knowledge-seed, see ../docker-compose.yaml).

Steps:
  1. wait until Qdrant answers,
  2. load and validate /app/seed/documents.yaml (40-60 documents of
     80-250 words in four doc_types; the 17 story anchors must exist),
  3. drop + create collection acme_knowledge (cosine, 384 dims) and
     keyword payload indexes on doc_type / doc_id,
  4. embed "title / section / text" with fastembed
     BAAI/bge-small-en-v1.5 (same model as server.py),
  5. upsert one point per document with payload
     {doc_id, doc_type, title, section, text, effective_from, tags},
  6. print the counts and exit 0 (non-zero on any mismatch).

Re-running is idempotent (the collection is recreated). Point ids are
uuid5(doc_id), so an upsert of the same corpus never duplicates.

Configuration (environment, defaults match docker-compose.yaml):
  QDRANT_URL, COLLECTION, EMBEDDING_MODEL, FASTEMBED_CACHE_DIR,
  SEED_FILE (/app/seed/documents.yaml)
"""

import os
import sys
import time
import uuid
from collections import Counter
from typing import Any

import yaml
from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

QDRANT_URL = os.environ.get("QDRANT_URL", "http://acme-knowledge-qdrant:6333")
COLLECTION = os.environ.get("COLLECTION", "acme_knowledge")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
MODEL_CACHE_DIR = os.environ.get("FASTEMBED_CACHE_DIR", "/app/models")
SEED_FILE = os.environ.get("SEED_FILE", "/app/seed/documents.yaml")

VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5
DOC_TYPES = (
    "policy_wordings",
    "claims_guidelines",
    "partner_contracts",
    "storm_playbooks",
)
REQUIRED_FIELDS = (
    "doc_id",
    "doc_type",
    "title",
    "section",
    "effective_from",
    "tags",
    "text",
)
MIN_WORDS, MAX_WORDS = 80, 250
MIN_DOCS, MAX_DOCS = 40, 60

# Story anchors (spec 3.3): the talk track and the workflow prompts
# quote these ids -- a corpus without them breaks the demo silently.
REQUIRED_DOC_IDS = (
    "PW-HC-7",
    "PW-RN-3",
    "PW-TL-1",
    "CG-FL-1",
    "CG-TL-2",
    "CG-BAFIN-30",
    "CG-FR-5",
    "CG-CX-3",
    "PC-BRAENDLE-2025",
    "PC-DELLENDOC-2024",
    "PC-IC-2",
    "PC-ROADASSIST-2025",
    "PC-RENTAFLEET-2026",
    "PC-RATES-2026",
    "SP-NATCAT-4",
    "SP-HZ-0907",
    "SP-REUTLINGEN-2023",
)

# Deterministic point ids: same doc_id -> same uuid on every run.
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "acme-insurance/knowledge")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_documents(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    docs = data.get("documents") if isinstance(data, dict) else data
    if not isinstance(docs, list) or not docs:
        fail(f"{path}: expected a non-empty list under 'documents'")
    return docs


def validate(docs: list[dict[str, Any]]) -> None:
    if not MIN_DOCS <= len(docs) <= MAX_DOCS:
        fail(f"{len(docs)} documents, expected {MIN_DOCS}-{MAX_DOCS}")
    seen: set[str] = set()
    for i, doc in enumerate(docs):
        where = f"document #{i + 1} ({doc.get('doc_id', '?')})"
        for field in REQUIRED_FIELDS:
            if field not in doc or doc[field] in (None, "", []):
                fail(f"{where}: missing field '{field}'")
        if doc["doc_type"] not in DOC_TYPES:
            fail(f"{where}: doc_type {doc['doc_type']!r} not in {DOC_TYPES}")
        if not isinstance(doc["tags"], list):
            fail(f"{where}: tags must be a list")
        if doc["doc_id"] in seen:
            fail(f"{where}: duplicate doc_id")
        seen.add(doc["doc_id"])
        words = len(str(doc["text"]).split())
        if not MIN_WORDS <= words <= MAX_WORDS:
            # Warn only: a slightly long edit must not break install.sh
            print(
                f"WARN: {where}: {words} words "
                f"(expected {MIN_WORDS}-{MAX_WORDS})"
            )
    missing = [d for d in REQUIRED_DOC_IDS if d not in seen]
    if missing:
        fail(f"story anchor documents missing: {', '.join(missing)}")


def wait_for_qdrant(client: QdrantClient, attempts: int = 60) -> None:
    for attempt in range(1, attempts + 1):
        try:
            client.get_collections()
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts:
                fail(f"Qdrant at {QDRANT_URL} not reachable: {exc}")
            if attempt in (1, 10, 30):
                print(f"waiting for Qdrant at {QDRANT_URL} ({exc})")
            time.sleep(2)


def embed_text(doc: dict[str, Any]) -> str:
    # Title and section carry the clause ids and partner names that
    # questions mention; embedding them with the body lifts the
    # decisive document to the top for "what does RN-3 say" queries.
    return f"{doc['title']}\n{doc['section']}\n{doc['text']}"


def payload_of(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": str(doc["doc_id"]),
        "doc_type": str(doc["doc_type"]),
        "title": str(doc["title"]),
        "section": str(doc["section"]),
        "text": str(doc["text"]).strip(),
        # YAML may parse an unquoted date into datetime.date -> str()
        "effective_from": str(doc["effective_from"]),
        "tags": [str(t) for t in doc["tags"]],
    }


def main() -> None:
    docs = load_documents(SEED_FILE)
    validate(docs)
    print(f"{SEED_FILE}: {len(docs)} documents validated")

    # check_compatibility=False: no "client version X is incompatible
    # with server version 1.15.4" warning when pip resolves a newer
    # client minor than the pinned server image (see requirements.txt).
    client = QdrantClient(url=QDRANT_URL, timeout=60, check_compatibility=False)
    wait_for_qdrant(client)

    print(f"loading embedding model {EMBEDDING_MODEL} (cache {MODEL_CACHE_DIR})")
    embedder = TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=MODEL_CACHE_DIR)
    t0 = time.time()
    vectors = [v.tolist() for v in embedder.embed([embed_text(d) for d in docs], batch_size=32)]
    if len(vectors) != len(docs):
        fail(f"embedded {len(vectors)} vectors for {len(docs)} documents")
    if len(vectors[0]) != VECTOR_SIZE:
        fail(f"vector size {len(vectors[0])}, expected {VECTOR_SIZE}")
    print(f"embedded {len(vectors)} documents in {time.time() - t0:.1f}s")

    # recreate_collection() is deprecated in qdrant-client -> explicit
    # delete + create (idempotent re-seed).
    if client.collection_exists(collection_name=COLLECTION):
        client.delete_collection(collection_name=COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(
            size=VECTOR_SIZE, distance=models.Distance.COSINE
        ),
    )
    for field in ("doc_type", "doc_id"):
        client.create_payload_index(
            collection_name=COLLECTION,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    points = [
        models.PointStruct(
            id=str(uuid.uuid5(ID_NAMESPACE, doc["doc_id"])),
            vector=vector,
            payload=payload_of(doc),
        )
        for doc, vector in zip(docs, vectors)
    ]
    client.upsert(collection_name=COLLECTION, points=points, wait=True)

    count = client.count(collection_name=COLLECTION, exact=True).count
    by_type = Counter(d["doc_type"] for d in docs)
    breakdown = ", ".join(f"{t} {by_type[t]}" for t in DOC_TYPES)
    print(f"{COLLECTION}: {count} documents seeded ({breakdown})")
    if count != len(docs):
        fail(f"collection holds {count} points, expected {len(docs)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
