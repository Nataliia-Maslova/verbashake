"""
engine/word_inbox.py — «Скарбничка»: words/phrases the student saved with ➕
while working (schema.sql: word_inbox, 2026-10-30). inbox_app.py shows them
and turns 5-15 picked ones into a My Phrases lesson; the picked rows are
then removed here.

Natalia's rules: only the phrase (+ a translation when the place it was
saved from already had one) — no source, no context sentence. Each phrase is
its own unit: "run a company" and "run" are two rows. The dedupe key is just
the phrase lowercased with spaces collapsed, never a lemma.

Best-effort like engine/path_pins.py: a DB failure is swallowed, never raised.
"""
from __future__ import annotations

import re

from engine import db

MAX_PHRASE_CHARS = 80
MAX_ITEMS = 300
BLOCK_MIN = 5
BLOCK_MAX = 15


def clean_phrase(text: str) -> str:
    """Collapse whitespace and trim edge punctuation; commas are dropped too
    (the block builder sends the phrases to Gemini as a comma list)."""
    s = re.sub(r"\s+", " ", str(text or "").replace(",", " ")).strip()
    s = s.strip(" .!?;:…\"«»“”„()[]{}")
    return s[:MAX_PHRASE_CHARS].strip()


def phrase_key(text: str) -> str:
    return clean_phrase(text).lower()


def add(user_id: str, target_lang: str, phrase: str, translation: str | None = None) -> bool:
    """True if saved (or already there). False on empty input, a full inbox
    or a DB failure."""
    phrase = clean_phrase(phrase)
    if not user_id or not phrase:
        return False
    try:
        if count(user_id, target_lang) >= MAX_ITEMS:
            return False
        db.execute(
            "INSERT INTO word_inbox (user_id, target_lang, phrase_key, phrase, translation) "
            "VALUES (:uid, :lang, :key, :phrase, :tr) "
            "ON CONFLICT (user_id, target_lang, phrase_key) DO NOTHING",
            {"uid": user_id, "lang": target_lang, "key": phrase.lower(),
             "phrase": phrase, "tr": (str(translation).strip()[:MAX_PHRASE_CHARS * 2] or None)
             if translation else None},
        )
        return True
    except Exception:
        return False


def remove(user_id: str, target_lang: str, keys: list[str]) -> None:
    if not user_id or not keys:
        return
    try:
        db.execute_many(
            "DELETE FROM word_inbox WHERE user_id=:uid AND target_lang=:lang AND phrase_key=:key",
            [{"uid": user_id, "lang": target_lang, "key": k} for k in keys],
        )
    except Exception:
        pass


def list_items(user_id: str, target_lang: str) -> list[dict]:
    """[{phrase_key, phrase, translation, created_at}], oldest first."""
    if not user_id:
        return []
    try:
        return db.fetch_all(
            "SELECT phrase_key, phrase, translation, created_at FROM word_inbox "
            "WHERE user_id=:uid AND target_lang=:lang ORDER BY created_at, phrase_key",
            {"uid": user_id, "lang": target_lang},
        )
    except Exception:
        return []


def is_full(user_id: str, target_lang: str) -> bool:
    return count(user_id, target_lang) >= MAX_ITEMS


def count(user_id: str, target_lang: str) -> int:
    if not user_id:
        return 0
    try:
        row = db.fetch_one(
            "SELECT COUNT(*) AS n FROM word_inbox WHERE user_id=:uid AND target_lang=:lang",
            {"uid": user_id, "lang": target_lang},
        )
        return int(row["n"]) if row else 0
    except Exception:
        return 0
