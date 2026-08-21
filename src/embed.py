"""Local embeddings for semantic search — sentence-transformers, fully on-device.
Embeds message text (falling back to transcript for media-only messages), never
raw_json. Vectors are stored L2-normalized so semantic_search in mcp_server.py can
rank by a plain dot product instead of a full cosine-similarity computation.

Model: BAAI/bge-large-en-v1.5 (1024-dim). BGE models are trained asymmetrically —
only the QUERY side gets an instruction prefix, not the indexed documents — so
messages here are embedded with no prefix (see mcp_server.py's semantic_search for
the query-side prefix).

Usage:
    python src/embed.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from db import ensure_tables, get_unembedded, set_embedding

load_dotenv()

MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-large-en-v1.5")
BATCH_SIZE = 32


def run_embedding(limit: int = 200) -> int:
    ensure_tables()
    rows = get_unembedded(limit=limit)
    print(f"Embedding: {len(rows)} messages to process (model={MODEL_NAME})")
    if not rows:
        return 0

    model = SentenceTransformer(MODEL_NAME)

    texts = []
    keys = []
    for chat_id, message_id, text, transcript in rows:
        content = (text or "").strip() or (transcript or "").strip()
        texts.append(content)
        keys.append((chat_id, message_id))

    done = 0
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_keys = keys[i:i + BATCH_SIZE]
        vectors = model.encode(batch_texts, normalize_embeddings=True, convert_to_numpy=True)
        for (chat_id, message_id), vec in zip(batch_keys, vectors):
            set_embedding(chat_id, message_id, vec.astype(np.float32).tobytes())
            done += 1
        print(f"  [{done}/{len(rows)}] embedded")

    print(f"Embedding done. {done} messages embedded.")
    return done


if __name__ == "__main__":
    run_embedding()
