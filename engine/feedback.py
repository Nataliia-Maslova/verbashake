"""
engine/feedback.py — student bug reports + server-side error logging.

Two independent, best-effort write paths (schema.sql: user_feedback,
app_errors) added 2026-09-16 before the first test-user launch: previously
there was no in-app way for a student to tell Наталя something's wrong (no
"report a problem" button anywhere), and no server-side record of an
uncaught exception beyond Streamlit Cloud's own log viewer, which nobody
watches live. Both tables are read directly via SQL by Наталя -- no admin
UI for them exists or is planned yet.

Both submit_feedback() and log_error() swallow their own DB failures (same
"best-effort, never let a secondary write crash the primary flow" pattern
already used throughout engine/gamification.py and engine/recommender.py) --
log_error() especially must never raise, since it's called FROM an except
block; a failure there would mask the original exception.
"""
from __future__ import annotations

import json
import traceback


def submit_feedback(user_id: str, message: str, context: dict | None = None) -> bool:
    """Save a student's free-text bug report. Returns True on success."""
    if not message.strip():
        return False
    try:
        from engine import db
        db.execute(
            "INSERT INTO user_feedback (user_id, message, context) "
            "VALUES (:user_id, :message, :context)",
            {"user_id": user_id, "message": message.strip(),
             "context": json.dumps(context or {})},
        )
        return True
    except Exception:
        return False


def log_error(user_id: str | None, module: str | None, exc: Exception) -> None:
    """
    Record an uncaught exception. Called from app.py's top-level
    try/except around the module dispatch -- never raises itself.
    """
    try:
        from engine import db
        db.execute(
            "INSERT INTO app_errors (user_id, module, error_type, message, traceback) "
            "VALUES (:user_id, :module, :error_type, :message, :traceback)",
            {
                "user_id": user_id, "module": module,
                "error_type": type(exc).__name__, "message": str(exc)[:2000],
                "traceback": traceback.format_exc()[:8000],
            },
        )
    except Exception:
        pass
