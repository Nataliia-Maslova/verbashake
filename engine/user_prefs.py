"""
engine/user_prefs.py — persisted native/target language choice per user
(CLAUDE.md, 2026-08-22).

Previously app.py's launcher only kept native/target language in
st.session_state, which resets on every fresh login/browser session and
never survives a Streamlit Cloud redeploy — a returning student had to
re-pick their languages every single time, even though it's the very first
thing they see after logging in. This makes that choice sticky across
sessions and devices, via user_prefs (schema.sql), the same way progress
already is.
"""
from __future__ import annotations

from engine import db


def get_prefs(user_id: str) -> dict | None:
    """Saved {"native_lang": str, "target_lang": str} for this user, or None
    if they've never saved one yet (or DATABASE_URL isn't configured)."""
    if not user_id:
        return None
    try:
        return db.fetch_one(
            "SELECT native_lang, target_lang FROM user_prefs WHERE user_id = :uid",
            {"uid": user_id},
        )
    except Exception:
        return None


def save_prefs(user_id: str, native_lang: str, target_lang: str) -> None:
    """Best-effort save — a failure here just means the choice stays
    session-only for this run, it doesn't block anything."""
    if not user_id:
        return
    try:
        db.upsert(
            "user_prefs",
            keys={"user_id": user_id},
            values={"native_lang": native_lang, "target_lang": target_lang},
        )
    except Exception:
        pass
