import os
from datetime import datetime, timezone
from pathlib import Path

MEDIA_ROOT = Path(os.environ.get("CDMM_MEDIA_ROOT", Path(__file__).resolve().parent.parent / "data" / "media"))


def save_media(chat_id: int, message_id: int, filename: str, data: bytes) -> str:
    """Writes bytes to data/media/{chat_id}/{year}/{month:02d}/{message_id}_{filename}.
    Returns the absolute path as a string (stored in messages.media_path)."""
    now = datetime.now(timezone.utc)
    path = MEDIA_ROOT / str(chat_id) / str(now.year) / f"{now.month:02d}" / f"{message_id}_{filename}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)
