"""
engine/account_deletion.py — self-service "delete my account" (GDPR-style
right to erasure), added 2026-09-17 before opening the app to test users who
aren't personal contacts of Наталя -- for people she knows, "just message me
and I'll clean it up" was an acceptable stopgap; for strangers signing in
with a real Google account, there needs to be a real self-service option.

Erases every row keyed by user_id across the tables in schema.sql. Two
tables are NOT touched:
  - content_units, phrase_translations, lesson_explanations,
    phrase_explanations: shared content caches keyed by (topic/phrase/...),
    never by user_id -- there's nothing of this user's to delete there.
  - app_errors: user_id is nulled out, not deleted -- it's an operational
    debugging log (traceback of an app bug), not personal data the student
    "owns" the way their own mastery/progress is; keeping the error with
    its identifying user_id removed preserves its debugging value.
"""
from __future__ import annotations

from engine import billing, db

# Every table in schema.sql with a user_id column whose rows belong
# entirely to that one user (safe to hard-delete, not just anonymize).
_USER_OWNED_TABLES = (
    "mastery", "srs_state", "lesson_pointer", "gamification",
    "user_prefs", "custom_phrases", "lesson_schedule",
    "subscriptions", "daily_feature_usage", "weekly_signup_gate",
    "user_feedback",
)


def delete_account(user_id: str) -> bool:
    """
    Permanently erases every row belonging to user_id. Returns True if the
    data delete itself succeeded (the Stripe cancellation is best-effort and
    doesn't affect the return value -- see billing.cancel_subscription's
    docstring for why). Caller is responsible for ending the session
    (st.logout()) afterward -- this function only touches the database.
    """
    billing.cancel_subscription(user_id)

    for table in _USER_OWNED_TABLES:
        db.execute(f"DELETE FROM {table} WHERE user_id = :uid", {"uid": user_id})
    db.execute(
        "UPDATE app_errors SET user_id = NULL WHERE user_id = :uid",
        {"uid": user_id},
    )
    return True
