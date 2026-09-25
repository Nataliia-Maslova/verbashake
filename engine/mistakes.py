"""
engine/mistakes.py — persisted text of a student's grammar mistakes
(schema.sql: user_mistakes, 2026-09-20).

Best-effort, like every other progress write in this project: a DB failure
(or a database that hasn't had the user_mistakes table created yet) is
swallowed, never raised -- losing a mistake log row must not break a lesson.
"""
from __future__ import annotations

from engine import db


def log_mistakes(user_id: str, target_lang: str, module: str | None, rows: list[dict]) -> None:
    """rows: [{unit_id, phase, topic_en, original, corrected, explanation}, ...]"""
    params = [
        {
            "uid": user_id, "lang": target_lang, "module": module,
            "unit_id": r.get("unit_id"), "phase": r.get("phase"),
            "topic": r.get("topic_en"),
            "original": r["original"], "corrected": r["corrected"],
            "expl": r.get("explanation"),
        }
        for r in rows
        if r.get("original") and r.get("corrected")
        and r["original"].strip() != r["corrected"].strip()
    ]
    if not params:
        return
    try:
        db.execute_many(
            "INSERT INTO user_mistakes "
            "(user_id, target_lang, module, unit_id, phase, topic_en, original, corrected, explanation) "
            "VALUES (:uid, :lang, :module, :unit_id, :phase, :topic, :original, :corrected, :expl)",
            params,
        )
    except Exception:
        pass


def mark_resolved(user_id: str, target_lang: str, original: str, corrected: str) -> None:
    """The student reproduced this structure correctly in the error drill."""
    try:
        db.execute(
            "UPDATE user_mistakes SET resolved_at = now() "
            "WHERE user_id=:uid AND target_lang=:lang AND original=:o AND corrected=:c "
            "AND resolved_at IS NULL",
            {"uid": user_id, "lang": target_lang, "o": original, "c": corrected},
        )
    except Exception:
        pass


def open_mistakes(user_id: str, target_lang: str, limit: int = 50) -> list[dict]:
    """Still-unresolved mistakes, newest first (for a future 'my mistakes' view)."""
    try:
        return db.fetch_all(
            "SELECT * FROM user_mistakes WHERE user_id=:uid AND target_lang=:lang "
            "AND resolved_at IS NULL ORDER BY created_at DESC LIMIT :n",
            {"uid": user_id, "lang": target_lang, "n": limit},
        )
    except Exception:
        return []


def list_mistakes(user_id: str, target_lang: str, resolved: bool, limit: int = 100) -> list[dict]:
    """Open (resolved=False) or resolved (True) mistakes, newest first."""
    col_filter = "IS NOT NULL" if resolved else "IS NULL"
    order = "resolved_at" if resolved else "created_at"
    try:
        return db.fetch_all(
            f"SELECT * FROM user_mistakes WHERE user_id=:uid AND target_lang=:lang "
            f"AND resolved_at {col_filter} ORDER BY {order} DESC LIMIT :n",
            {"uid": user_id, "lang": target_lang, "n": limit},
        )
    except Exception:
        return []


def counts(user_id: str, target_lang: str) -> dict[str, int]:
    """{"open": n, "resolved": n} for this target_lang."""
    try:
        row = db.fetch_one(
            "SELECT count(*) FILTER (WHERE resolved_at IS NULL) AS open, "
            "count(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved "
            "FROM user_mistakes WHERE user_id=:uid AND target_lang=:lang",
            {"uid": user_id, "lang": target_lang},
        )
        return {"open": int(row["open"]), "resolved": int(row["resolved"])} if row else {"open": 0, "resolved": 0}
    except Exception:
        return {"open": 0, "resolved": 0}


def top_open_topics(user_id: str, target_lang: str, limit: int = 5) -> list[dict]:
    """[{"topic_en": str, "n": int}, ...] -- topics with the most still-open mistakes."""
    try:
        return db.fetch_all(
            "SELECT topic_en, count(*) AS n FROM user_mistakes "
            "WHERE user_id=:uid AND target_lang=:lang AND resolved_at IS NULL "
            "AND topic_en IS NOT NULL AND topic_en <> '' "
            "GROUP BY topic_en ORDER BY n DESC, topic_en LIMIT :n",
            {"uid": user_id, "lang": target_lang, "n": limit},
        )
    except Exception:
        return []
