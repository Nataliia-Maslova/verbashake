"""
engine/rate_limit.py — per-user daily quota for Gemini-backed features that
accept free-form text input.

Why this exists (Наталія, 2026-08-24): most Gemini calls in this app are
keyed by fixed lesson content (explain_lesson_rule, translate_phrase...) —
Postgres-cached by (topic/phrase, lang pair), so the SAME student re-opening
the same lesson twice costs nothing extra, and abuse is naturally bounded by
how much fixed content the app actually has. "❓ Чому так?" (Step 1's
explain_phrase_part) breaks that assumption: the student types an arbitrary
confusing_part into a text field, so every distinct string is a fresh cache
miss and a real Gemini call — a malicious Premium subscriber (paid once,
$8.88/mo) could script thousands of distinct queries in minutes. This is a
blunt per-feature backstop against exactly that, not a general free-plan
gate (@_require_paid in engine/gemini.py already handles "free = zero live
AI") — it applies to paid users too, since paying once doesn't buy unlimited
API cost.

Usage:
    from engine import rate_limit
    try:
        rate_limit.check_and_increment(user_id, "explain_phrase_part", limit=30)
    except rate_limit.DailyLimitExceeded:
        st.warning(...)
        return
    # ... make the live Gemini call ...
"""
from __future__ import annotations

import datetime as _dt


class DailyLimitExceeded(Exception):
    """Raised when a user has hit their daily quota for a given feature."""


def check_and_increment(user_id: str, feature: str, limit: int) -> None:
    """
    Atomically increment today's (UTC) usage counter for (user_id, feature)
    and raise DailyLimitExceeded if that pushes the count over `limit`.

    Fails OPEN (DATABASE_URL not configured, or DB unreachable -> allow the
    call) — same best-effort convention as every other DB touch in this
    codebase (translate_phrase, lesson_explanations): a broken quota table
    shouldn't be the reason a paying student can't use a feature they
    already unlocked. This means the limit is a soft backstop against
    casual/scripted abuse, not a hard guarantee under DB downtime.

    Two round-trips (write, then read), not a single RETURNING query --
    engine.db's fetch_all()/fetch_one() use a plain connect() with no
    explicit commit (fine for SELECT-only callers), so an INSERT run
    through them would silently roll back on connection close. execute()
    (get_engine().begin()) is the only path in engine.db that actually
    commits a write.
    """
    try:
        from engine import db
        today = _dt.datetime.now(_dt.timezone.utc).date()
        db.execute(
            "INSERT INTO daily_feature_usage (user_id, feature, usage_date, count) "
            "VALUES (:u, :f, :d, 1) "
            "ON CONFLICT (user_id, feature, usage_date) "
            "DO UPDATE SET count = daily_feature_usage.count + 1",
            {"u": user_id, "f": feature, "d": today},
        )
        row = db.fetch_one(
            "SELECT count FROM daily_feature_usage "
            "WHERE user_id = :u AND feature = :f AND usage_date = :d",
            {"u": user_id, "f": feature, "d": today},
        )
        count = row["count"] if row else 1
    except Exception:
        return  # DATABASE_URL not configured, or DB unreachable -- fail open

    if count > limit:
        raise DailyLimitExceeded(
            f"Daily limit ({limit}) reached for {feature!r}."
        )
