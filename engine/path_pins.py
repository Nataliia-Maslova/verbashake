"""
engine/path_pins.py — lessons a student added to "My Path" themselves
(schema.sql: path_pins, 2026-10-04). First source: the Songs module's
"➕ В мій шлях" on a grammar structure found in a song.

engine.recommender.get_path_next() puts these first, oldest first, until the
lesson's topic reaches the same mastery bar the grammar frontier uses
(GRAMMAR_ADVANCE_THRESHOLD) — then the pin simply stops showing; the row
itself is left alone. "Skip" on My Path removes the pin (path_app.py).

Best-effort like every other progress write here: a DB failure (or a
database that hasn't had path_pins created yet) is swallowed, never raised.
"""
from __future__ import annotations

from engine import db


def add(user_id: str, target_lang: str, unit_id: str, source: str | None = None) -> bool:
    """True if saved (or already pinned)."""
    if not user_id or not unit_id:
        return False
    try:
        db.execute(
            "INSERT INTO path_pins (user_id, target_lang, unit_id, source) "
            "VALUES (:uid, :lang, :unit, :src) "
            "ON CONFLICT (user_id, target_lang, unit_id) DO NOTHING",
            {"uid": user_id, "lang": target_lang, "unit": unit_id, "src": source},
        )
        return True
    except Exception:
        return False


def remove(user_id: str, target_lang: str, unit_id: str) -> None:
    try:
        db.execute(
            "DELETE FROM path_pins WHERE user_id=:uid AND target_lang=:lang AND unit_id=:unit",
            {"uid": user_id, "lang": target_lang, "unit": unit_id},
        )
    except Exception:
        pass


def list_pins(user_id: str, target_lang: str) -> list[dict]:
    """[{unit_id, source, created_at}], oldest first."""
    if not user_id:
        return []
    try:
        return db.fetch_all(
            "SELECT unit_id, source, created_at FROM path_pins "
            "WHERE user_id=:uid AND target_lang=:lang ORDER BY created_at",
            {"uid": user_id, "lang": target_lang},
        )
    except Exception:
        return []
