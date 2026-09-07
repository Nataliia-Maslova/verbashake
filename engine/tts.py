"""
TTS module — Google TTS with local file caching.
Audio files are cached to avoid re-generating the same phrases.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

# pygame is NOT used on Streamlit Cloud — audio plays via base64 HTML in the browser
# It is optional for local development only
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

CACHE_DIR = Path(__file__).parent.parent / "audio_cache"
CACHE_DIR.mkdir(exist_ok=True)


def get_audio_path(text: str, lang: str) -> str | None:
    """
    Return path to an MP3 file for the given text+lang.
    Generates and caches if not already on disk.
    Returns None if gTTS is not available.
    """
    if not GTTS_AVAILABLE:
        return None

    key  = hashlib.md5(f"{lang}::{text}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.mp3"

    if not path.exists():
        # Write to a per-call temp file then atomically rename into place
        # (2026-09-07) -- the exists-check above and the write used to be
        # two separate steps, so two students requesting audio for the same
        # not-yet-cached (text, lang) pair for the first time (e.g. a common
        # roleplay opener) could both see it missing and both call
        # tts.save() on the same final path concurrently, risking a reader
        # picking up a partially-written file mid-write. os.replace() is
        # atomic on POSIX, so any concurrent writer's rename either fully
        # lands or doesn't -- never a partial file at `path`.
        tmp_path = CACHE_DIR / f"{key}.{uuid.uuid4().hex}.tmp"
        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(str(tmp_path))
            os.replace(tmp_path, path)
        except Exception as e:
            print(f"[TTS] Error generating audio: {e}")
            tmp_path.unlink(missing_ok=True)
            return None

    return str(path)


def tts_available() -> bool:
    return GTTS_AVAILABLE
