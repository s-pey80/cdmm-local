"""Local embeddings for semantic search — sentence-transformers, fully on-device.
Embeds message text, transcript, and vision description combined (whichever are
present), never raw_json. Vectors are stored L2-normalized so semantic_search in
mcp_server.py can rank by a plain dot product instead of a full cosine-similarity
computation.

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

from db import ensure_tables, get_message_content, get_unembedded, set_embedding

load_dotenv()

MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-large-en-v1.5")
BATCH_SIZE = 32

_model = None


def _get_model():
    """Lazy-loaded singleton — mirrors mcp_server.py's _get_embed_model() and
    vision.py's _get_model(), so a live per-message call (embed_one, invoked
    from listener.py/hydration.py) doesn't reload the model from disk every
    single message within one process."""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_one(chat_id: int, message_id: int) -> bool:
    """Embeds a single message's current text+transcript+media_description,
    combined the same way run_embedding() does. Called live from listener.py
    (plain text/edits) and hydration.py (after a transcript/vision
    description is saved). Returns False if there's nothing to embed yet
    (e.g. a photo whose vision description hasn't landed)."""
    row = get_message_content(chat_id, message_id)
    if row is None:
        return False
    text, transcript, media_description = row
    parts = [p.strip() for p in (text, transcript, media_description) if p and p.strip()]
    if not parts:
        return False
    content = "\n\n".join(parts)
    vec = _get_model().encode(content, normalize_embeddings=True, convert_to_numpy=True)
    set_embedding(chat_id, message_id, vec.astype(np.float32).tobytes())
    return True


def run_embedding(limit: int = 200) -> int:
    ensure_tables()
    rows = get_unembedded(limit=limit)
    print(f"Embedding: {len(rows)} messages to process (model={MODEL_NAME})")
    if not rows:
        return 0

    model = _get_model()

    texts = []
    keys = []
    for chat_id, message_id, text, transcript, media_description in rows:
        parts = [p.strip() for p in (text, transcript, media_description) if p and p.strip()]
        texts.append("\n\n".join(parts))
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
