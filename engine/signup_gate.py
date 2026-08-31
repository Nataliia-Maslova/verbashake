"""
engine/signup_gate.py — weekly cap on NEW signups during the free launch
period (Наталія, 2026-08-31): plan is ~4 months fully free (Stripe stays in
test mode, no changes to @_require_paid needed for this), but new-user
growth still needs a lid on it — partly to bound Gemini API cost while the
app is free for everyone, partly as a deliberate marketing hook ("50 spots
this week") for the Instagram/Telegram/YouTube launch campaign.

This gates ACCOUNT ADMISSION, not AI usage per call — that's a separate,
still-active concern (engine/rate_limit.py, engine/gemini.py::_gated) once
someone is already in. WEEKLY_CAP resets every calendar week (Monday 00:00
UTC), so admission is a GROWING pool by default — week 2's 50 spots are on
top of week 1's, not instead of them. check_and_admit() never auto-revokes
anyone on its own.

Weekly review ritual (Наталія, 2026-08-31) — the manual tool for making
sure the free period doesn't just settle into the same ~50 people for 4
months straight: once a week, pull the report query below (paste into the
Supabase SQL editor, or ask Claude to run it), look at who's actually
active vs. dormant, then use set_admitted()/set_limit_scale() below to
pause dormant users (frees them up to reconsider later, doesn't delete
their progress) and/or throttle heavy AI users, opening room for new
signups without just letting the pool grow unbounded. Nothing here runs
automatically — it's a decision made together each week, not a cron job.

-- Weekly review report -----------------------------------------------------
-- SELECT
--   wsg.user_id,
--   wsg.first_seen_at::date  AS joined,
--   wsg.admitted,
--   wsg.limit_scale,
--   g.streak_last_date,               -- closest proxy to "last active date"
--   g.lessons_completed,
--   g.xp_total,
--   COALESCE(u.calls_last_7d, 0) AS ai_calls_last_7d
-- FROM weekly_signup_gate wsg
-- LEFT JOIN gamification g ON g.user_id = wsg.user_id
-- LEFT JOIN (
--   SELECT user_id, SUM(count) AS calls_last_7d
--   FROM daily_feature_usage
--   WHERE usage_date >= CURRENT_DATE - INTERVAL '7 days'
--   GROUP BY user_id
-- ) u ON u.user_id = wsg.user_id
-- ORDER BY wsg.first_seen_at;
-- -----------------------------------------------------------------------

Usage (engine/auth_gate.py::check_and_gate(), right after login is
confirmed, before returning True):
    from engine import signup_gate
    if not signup_gate.check_and_admit(user_id):
        _show_waitlist()
        return False
"""
from __future__ import annotations

import datetime as _dt

WEEKLY_CAP = 50  # bump this number (and redeploy) to open more spots


def _week_start(today: _dt.date) -> _dt.date:
    """Monday 00:00 UTC of the ISO week containing `today`."""
    return today - _dt.timedelta(days=today.weekday())


def check_and_admit(user_id: str) -> bool:
    """
    True if `user_id` is (or becomes) admitted. Already-seen users are
    always admitted — the check only gates a user's FIRST login ever. A
    brand-new user is admitted only if fewer than WEEKLY_CAP other new
    users were admitted since this week's Monday 00:00 UTC.

    Fails OPEN (no DATABASE_URL, or DB unreachable -> admit) — same
    convention as engine/rate_limit.py and every other best-effort DB touch
    in this codebase: a broken gate table should never be the reason a real
    student can't get in.
    """
    try:
        from engine import db
        row = db.fetch_one(
            "SELECT admitted FROM weekly_signup_gate WHERE user_id = :u",
            {"u": user_id},
        )
        if row is not None:
            return row["admitted"]

        week_start = _week_start(_dt.datetime.now(_dt.timezone.utc).date())
        count_row = db.fetch_one(
            "SELECT count(*) AS c FROM weekly_signup_gate "
            "WHERE first_seen_at >= :ws AND admitted = true",
            {"ws": week_start},
        )
        count = count_row["c"] if count_row else 0
        admitted = count < WEEKLY_CAP

        db.execute(
            "INSERT INTO weekly_signup_gate (user_id, admitted) "
            "VALUES (:u, :a) ON CONFLICT (user_id) DO NOTHING",
            {"u": user_id, "a": admitted},
        )
        return admitted
    except Exception:
        return True  # DATABASE_URL not configured, or DB unreachable -- fail open


def spots_left_this_week() -> int | None:
    """
    How many admission spots remain this week — for a "X spots left this
    week" banner. None if it can't be determined (DB down / not
    configured); caller should just omit the number in that case.
    """
    try:
        from engine import db
        week_start = _week_start(_dt.datetime.now(_dt.timezone.utc).date())
        row = db.fetch_one(
            "SELECT count(*) AS c FROM weekly_signup_gate "
            "WHERE first_seen_at >= :ws AND admitted = true",
            {"ws": week_start},
        )
        count = row["c"] if row else 0
        return max(0, WEEKLY_CAP - count)
    except Exception:
        return None


# ── Weekly review tools ──────────────────────────────────────────────────────

def get_limit_scale(user_id: str) -> float:
    """
    Per-user throttle multiplier read by engine.gemini::_gated to scale a
    specific user's daily AI limits up or down without touching everyone
    else's. Defaults to 1.0 (no throttle) for any user without an explicit
    override. Fails OPEN (DB down/not configured -> 1.0), same convention
    as the rest of this module.
    """
    try:
        from engine import db
        row = db.fetch_one(
            "SELECT limit_scale FROM weekly_signup_gate WHERE user_id = :u",
            {"u": user_id},
        )
        return float(row["limit_scale"]) if row and row["limit_scale"] is not None else 1.0
    except Exception:
        return 1.0


def set_admitted(user_id: str, admitted: bool) -> None:
    """
    Weekly-review tool: pause ("поставити в очікування") an existing user
    by passing admitted=False — their NEXT login shows the waitlist screen
    again, exactly as if they'd never gotten a spot. Their progress
    (mastery/SRS/gamification/etc.) is untouched, only re-entry is blocked,
    so re-admitting later (admitted=True) picks up right where they left
    off. Passing admitted=True for a user who has never logged in at all
    pre-admits them — their first real login finds this row already here
    and skips the weekly-cap count entirely, useful for manually guaranteeing
    a spot to someone outside the normal first-come-first-served flow.
    """
    from engine import db
    db.upsert(
        "weekly_signup_gate",
        keys={"user_id": user_id},
        values={"admitted": admitted},
        touch_updated_at=False,
    )


def set_limit_scale(user_id: str, scale: float) -> None:
    """
    Weekly-review tool: multiply every engine.gemini @_gated daily limit for
    THIS user only by `scale` (e.g. 0.3 = 30% of the normal daily allowance)
    without fully pausing them (see set_admitted for the harder tool) — they
    keep full access to the non-AI parts of the app (fixed lesson content,
    navigation, gamification), just a smaller live-AI ration. scale=1.0
    removes the throttle. Only meaningful for a user who already has a
    weekly_signup_gate row (has logged in at least once) -- silently does
    nothing otherwise, same as any UPDATE against a nonexistent row; use
    set_admitted(user_id, True) first if pre-throttling someone who hasn't
    logged in yet is ever needed.
    """
    from engine import db
    db.execute(
        "UPDATE weekly_signup_gate SET limit_scale = :s WHERE user_id = :u",
        {"s": scale, "u": user_id},
    )
