"""
engine/schedule.py — optional lesson-day/time routine ("soft status, not a
gate" — CLAUDE.md concept discussion, 2026-09-07).

Design, agreed with Natalia before any code was written:
- Never blocks the app outside a scheduled slot, never sends a push — only
  drives a visual badge on the My Path screen when it's opened.
- A small, deliberately capped core routine: 1-3 days a week, each with its
  own time (not a shared time for all days, not a "part of day" range).
  Extra practice beyond those days/times is unlimited and doesn't need a
  slot of its own.
- One shared gamification streak (engine/gamification.py), not a second,
  stricter "kept the schedule" streak — missing a scheduled slot never
  breaks the regular streak, it only withholds the "🎯 on time" badge for
  that day.
- ±TOLERANCE_MINUTES around the scheduled time counts as "on time".
- The "want a routine?" setup prompt is offered ~1 day after signup, not on
  first-run onboarding — see should_show_setup_prompt().
"""
from __future__ import annotations

import datetime as _dt

from engine import db

MAX_DAYS = 3
TOLERANCE_MINUTES = 30

# Index = Python's date.weekday()/datetime.weekday(): 0=Monday..6=Sunday.
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def get_schedule(user_id: str) -> list[dict]:
    """[{"day_of_week": int, "time_of_day": "HH:MM"}, ...] sorted by day, or
    [] if none saved yet (or DATABASE_URL isn't configured)."""
    if not user_id:
        return []
    try:
        rows = db.fetch_all(
            "SELECT day_of_week, time_of_day FROM lesson_schedule "
            "WHERE user_id = :uid ORDER BY day_of_week",
            {"uid": user_id},
        )
        return [
            {"day_of_week": r["day_of_week"], "time_of_day": str(r["time_of_day"])[:5]}
            for r in rows
        ]
    except Exception:
        return []


def save_schedule(user_id: str, entries: list[dict]) -> None:
    """
    Replaces the whole schedule with `entries` ({"day_of_week": int,
    "time_of_day": "HH:MM"}), capped at MAX_DAYS. Delete-then-insert rather
    than per-row upsert — the set of days itself can shrink between saves
    (e.g. going from 3 days to 2), not just the time on an existing day, so
    a plain upsert would leave orphaned rows behind. Best-effort, same
    fail-silently convention as engine.user_prefs.save_prefs() — a failed
    save just means the routine stays session-only for this run.
    """
    if not user_id:
        return
    entries = entries[:MAX_DAYS]
    try:
        db.execute("DELETE FROM lesson_schedule WHERE user_id = :uid", {"uid": user_id})
        if entries:
            db.execute_many(
                "INSERT INTO lesson_schedule (user_id, day_of_week, time_of_day) "
                "VALUES (:uid, :dow, :t)",
                [
                    {"uid": user_id, "dow": int(e["day_of_week"]), "t": e["time_of_day"]}
                    for e in entries
                ],
            )
    except Exception:
        pass


def today_status(user_id: str, done_today: bool) -> dict:
    """
    Soft, non-blocking status for today's scheduled slot (if any):
      {"state": "no_schedule" | "not_scheduled_today" | "not_yet"
                | "in_window" | "missed_window" | "done",
       "time_of_day": "HH:MM" | None}

    "no_schedule"         — student never set up a routine at all.
    "not_scheduled_today" — has a routine, just not for today's weekday.
    "not_yet"              — today's slot hasn't opened yet.
    "in_window"            — within ±TOLERANCE_MINUTES of today's time.
    "missed_window"        — window passed today, no lesson done yet.
    "done"                 — already practised today (whenever that
                              happened — see done_today below).

    `done_today` is supplied by the caller rather than read from
    engine.gamification here, to keep this module a leaf (gamification
    already imports engine.recommender) — pass
    gamification.load_stats(user_id)["streak_last_date"] == date.today().isoformat().
    A "missed_window" state never implies anything broke — the regular
    streak this module doesn't touch is unaffected either way.
    """
    entries = get_schedule(user_id)
    if not entries:
        return {"state": "no_schedule", "time_of_day": None}

    now = _dt.datetime.now()
    today_entry = next((e for e in entries if e["day_of_week"] == now.weekday()), None)
    if today_entry is None:
        return {"state": "not_scheduled_today", "time_of_day": None}

    time_of_day = today_entry["time_of_day"]
    if done_today:
        return {"state": "done", "time_of_day": time_of_day}

    hh, mm = (int(p) for p in time_of_day.split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta_minutes = (now - slot).total_seconds() / 60

    if delta_minutes < -TOLERANCE_MINUTES:
        state = "not_yet"
    elif delta_minutes <= TOLERANCE_MINUTES:
        state = "in_window"
    else:
        state = "missed_window"

    return {"state": state, "time_of_day": time_of_day}


def should_show_setup_prompt(user_id: str) -> bool:
    """
    True when the delayed "want a routine?" banner should be offered: no
    schedule saved yet, not dismissed before, and it's been at least a day
    since this account's first login (weekly_signup_gate.first_seen_at) —
    deliberately not shown on first-run onboarding (Natalia: offer it once
    the student has actually tried the app and feels ready to think about
    regularity, not before the first lesson). Fails closed (False) on any
    DB error — a broken check just means the banner doesn't show, never a
    crash.
    """
    if not user_id:
        return False
    try:
        if get_schedule(user_id):
            return False
        prefs_row = db.fetch_one(
            "SELECT schedule_prompt_dismissed FROM user_prefs WHERE user_id = :uid",
            {"uid": user_id},
        )
        if prefs_row and prefs_row.get("schedule_prompt_dismissed"):
            return False
        signup_row = db.fetch_one(
            "SELECT first_seen_at FROM weekly_signup_gate WHERE user_id = :uid",
            {"uid": user_id},
        )
        if not signup_row or not signup_row.get("first_seen_at"):
            return False
        first_seen = signup_row["first_seen_at"]
        age = _dt.datetime.now(_dt.timezone.utc) - first_seen
        return age >= _dt.timedelta(days=1)
    except Exception:
        return False


def dismiss_setup_prompt(user_id: str) -> None:
    """Best-effort — "Not now" on the setup banner, never nag again."""
    if not user_id:
        return
    try:
        db.upsert(
            "user_prefs",
            keys={"user_id": user_id},
            values={"schedule_prompt_dismissed": True},
        )
    except Exception:
        pass
