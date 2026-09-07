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
    session-only for this run, it doesn't block anything. Only touches
    native_lang/target_lang — db.upsert() only sets the columns passed in
    `values`, so this never clobbers a profile saved via save_onboarding()."""
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


def get_profile(user_id: str) -> dict | None:
    """Full onboarding profile — {"native_lang", "target_lang", "display_name",
    "self_level", "literacy_required"} — or None if never saved / DB
    unavailable. self_level is "zero"/"A1".."C2"/None; literacy_required is
    True/False/None (None = never asked, see schema.sql's user_prefs comment)."""
    if not user_id:
        return None
    try:
        return db.fetch_one(
            "SELECT native_lang, target_lang, display_name, self_level, literacy_required "
            "FROM user_prefs WHERE user_id = :uid",
            {"uid": user_id},
        )
    except Exception:
        return None


def get_timezone(user_id: str) -> str | None:
    """Saved IANA zone name (e.g. "Europe/Kyiv"), or None if never captured
    yet / DB unavailable. See engine/client_tz.py for how it gets here."""
    if not user_id:
        return None
    try:
        row = db.fetch_one(
            "SELECT timezone FROM user_prefs WHERE user_id = :uid", {"uid": user_id},
        )
        return row["timezone"] if row else None
    except Exception:
        return None


def save_timezone(user_id: str, tz_name: str) -> None:
    """Best-effort save, same fail-silent convention as save_prefs() —
    only touches the timezone column."""
    if not user_id or not tz_name:
        return
    try:
        db.upsert("user_prefs", keys={"user_id": user_id}, values={"timezone": tz_name})
    except Exception:
        pass


def is_onboarded(user_id: str) -> bool:
    """True once the student has been through the first-run onboarding
    screen (app.py::_render_onboarding) — name + self-reported level saved,
    not just a language pair (save_prefs() alone, e.g. from an old install,
    doesn't count)."""
    profile = get_profile(user_id)
    return bool(profile and profile.get("display_name") and profile.get("self_level"))


def save_onboarding(
    user_id: str, display_name: str, native_lang: str, target_lang: str,
    self_level: str, literacy_required: bool | None,
) -> None:
    """One-time write from the first-run onboarding screen — sets every
    profile field at once, including the language pair (so this can run
    before app.py's regular save_prefs() call ever fires for this user)."""
    if not user_id:
        return
    try:
        db.upsert(
            "user_prefs",
            keys={"user_id": user_id},
            values={
                "display_name": display_name,
                "native_lang": native_lang,
                "target_lang": target_lang,
                "self_level": self_level,
                "literacy_required": literacy_required,
            },
        )
    except Exception:
        pass
