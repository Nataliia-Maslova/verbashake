"""
Custom phrases storage — user-created lessons for the same 8-step flow.

Postgres-backed (2026-08-28) via engine.db, same table content_units/
mastery/gamification already live in. Replaces the old CSV-file store
(data/custom_phrases.csv, mirrored to Google Sheets): that version did a
full read-all/append-in-memory/write-all-back on every add/delete/rename,
plus a full clear+rewrite of the Sheets mirror on top — fine with one person
testing alone, but a genuine data-loss race the moment two real users save
around the same time (whoever's full-file write lands last silently
overwrites the other's just-created lesson). Real per-row INSERT/DELETE/
UPDATE removes that race entirely, the same way mastery/srs_state/
gamification already left CSV/Sheets behind (see schema.sql's
`custom_phrases` table for the full writeup).

If DATABASE_URL isn't configured (e.g. a fresh local clone with no
secrets.toml), everything here quietly falls back to the original CSV+Sheets
implementation instead of failing outright — same "degrade, don't crash"
convention engine.gamification already uses for the same reason.

One-time migration: the first call in a process that finds Postgres
available AND the custom_phrases table still empty copies every row out of
the legacy CSV (data/custom_phrases.csv) into Postgres, preserving user_id/
lesson_id/phrase_id/created_at exactly — real users' existing lessons (e.g.
student1's "Тварини") aren't lost by switching backends.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from engine import db as _db

DATA_DIR  = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH  = DATA_DIR / "custom_phrases.csv"
SHEET_TAB = "custom_phrases"

COLUMNS = [
    "user_id", "lesson_id", "lesson_name", "phrase_id",
    "native_lang", "target_lang",
    "native", "target",
    "created_at",
]

LESSON_COLS = ["lesson_id", "lesson_name", "phrases", "native_lang", "target_lang"]
PHRASE_COLS = ["lesson_id", "phrase_id", "difficulty", "native", "target"]


def _db_ok() -> bool:
    return _db.is_available()


# ─── Legacy CSV path (fallback only — see module docstring) ────────────────

def _ensure_csv() -> None:
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writeheader()


def _read_all() -> pd.DataFrame:
    _ensure_csv()
    try:
        df = pd.read_csv(CSV_PATH, dtype={"lesson_id": "Int64", "phrase_id": "Int64"})
    except Exception:
        df = pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = pd.Series(dtype="object")
    return df[COLUMNS]


def _write_all(df: pd.DataFrame) -> None:
    df = df[COLUMNS].copy()
    df.to_csv(CSV_PATH, index=False, encoding="utf-8")


_ws_custom = None


def _get_ws():
    """Return the gspread worksheet for the custom_phrases tab, or None."""
    global _ws_custom
    if _ws_custom is not None:
        return _ws_custom
    try:
        from engine.logger import _get_spreadsheet
        import gspread
        ss = _get_spreadsheet()
        if ss is None:
            return None
        try:
            _ws_custom = ss.worksheet(SHEET_TAB)
        except gspread.exceptions.WorksheetNotFound:
            _ws_custom = ss.add_worksheet(title=SHEET_TAB, rows=5000,
                                           cols=len(COLUMNS))
            _ws_custom.append_row(COLUMNS, value_input_option="RAW")
        return _ws_custom
    except Exception as e:
        print(f"[custom_store] Google Sheets unavailable: {e}")
        return None


def _sync_to_sheets(df: pd.DataFrame) -> None:
    try:
        ws = _get_ws()
        if ws is None:
            return
        ws.clear()
        ws.append_row(COLUMNS, value_input_option="RAW")
        rows = df[COLUMNS].astype(str).values.tolist()
        if rows:
            ws.append_rows(rows, value_input_option="RAW")
    except Exception as e:
        print(f"[custom_store] sheet sync failed: {e}")


def _pull_from_sheets() -> pd.DataFrame | None:
    try:
        ws = _get_ws()
        if ws is None:
            return None
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.DataFrame(records)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = ""
        df["lesson_id"] = pd.to_numeric(df["lesson_id"], errors="coerce").astype("Int64")
        df["phrase_id"] = pd.to_numeric(df["phrase_id"], errors="coerce").astype("Int64")
        return df[COLUMNS]
    except Exception as e:
        print(f"[custom_store] sheet pull failed: {e}")
        return None


_sheets_synced: bool = False   # pulled from Sheets at most once per process start


def _csv_load_all(user_id: str | None = None, prefer_sheets: bool = True) -> pd.DataFrame:
    global _sheets_synced
    local = _read_all()
    if prefer_sheets and not _sheets_synced:
        remote = _pull_from_sheets()
        if remote is not None and len(remote) > len(local):
            _write_all(remote)
            local = remote
        _sheets_synced = True
    if user_id:
        local = local[local["user_id"].astype(str) == str(user_id)]
    return local.reset_index(drop=True)


def _csv_add_lesson(user_id, lesson_name, native_lang, target_lang, cleaned) -> int:
    df = _csv_load_all(user_id=user_id, prefer_sheets=False)
    lesson_id = int(df["lesson_id"].dropna().astype(int).max()) + 1 if not df.empty else 1
    now = datetime.now().isoformat(timespec="seconds")
    new_rows = [{
        "user_id": user_id, "lesson_id": lesson_id, "lesson_name": lesson_name,
        "phrase_id": i, "native_lang": native_lang, "target_lang": target_lang,
        "native": nat, "target": tgt, "created_at": now,
    } for i, (nat, tgt) in enumerate(cleaned, start=1)]
    all_df = pd.concat([_read_all(), pd.DataFrame(new_rows)], ignore_index=True)
    _write_all(all_df)
    _sync_to_sheets(all_df)
    return lesson_id


def _csv_delete_lesson(user_id: str, lesson_id: int) -> bool:
    df = _read_all()
    mask = (df["user_id"].astype(str) == str(user_id)) & \
           (df["lesson_id"].astype("Int64") == int(lesson_id))
    if not mask.any():
        return False
    df = df[~mask]
    _write_all(df)
    _sync_to_sheets(df)
    return True


def _csv_rename_lesson(user_id: str, lesson_id: int, new_name: str) -> bool:
    df = _read_all()
    mask = (df["user_id"].astype(str) == str(user_id)) & \
           (df["lesson_id"].astype("Int64") == int(lesson_id))
    if not mask.any():
        return False
    df.loc[mask, "lesson_name"] = new_name
    _write_all(df)
    _sync_to_sheets(df)
    return True


# ─── Postgres path ──────────────────────────────────────────────────────────

_migrated: bool = False  # migrate legacy CSV rows at most once per process


def _migrate_csv_once() -> None:
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        existing = _db.fetch_one("SELECT 1 FROM custom_phrases LIMIT 1")
        if existing is not None:
            return  # already has data (either migrated before, or real DB rows) -- never overwrite
        if not CSV_PATH.exists():
            return
        df = _read_all()
        if df.empty:
            return
        rows = []
        for _, r in df.iterrows():
            if pd.isna(r["lesson_id"]) or pd.isna(r["phrase_id"]):
                continue
            rows.append({
                "user_id": str(r["user_id"]), "lesson_id": int(r["lesson_id"]),
                "lesson_name": str(r["lesson_name"]), "phrase_id": int(r["phrase_id"]),
                "native_lang": str(r["native_lang"]), "target_lang": str(r["target_lang"]),
                "native": str(r["native"]), "target": str(r["target"]),
                "created_at": str(r["created_at"]) if pd.notna(r["created_at"]) else datetime.now().isoformat(),
            })
        if rows:
            _db.execute_many(
                "INSERT INTO custom_phrases "
                "(user_id, lesson_id, lesson_name, phrase_id, native_lang, target_lang, native, target, created_at) "
                "VALUES (:user_id, :lesson_id, :lesson_name, :phrase_id, :native_lang, :target_lang, :native, :target, :created_at) "
                "ON CONFLICT (user_id, lesson_id, phrase_id) DO NOTHING",
                rows,
            )
            print(f"[custom_store] migrated {len(rows)} rows from {CSV_PATH} into Postgres")
    except Exception as e:
        print(f"[custom_store] CSV migration skipped: {e}")


def _db_list_user_lessons(user_id: str, native_lang: str | None, target_lang: str | None) -> pd.DataFrame:
    sql = ("SELECT lesson_id, lesson_name, native_lang, target_lang, COUNT(*) AS phrases "
           "FROM custom_phrases WHERE user_id = :user_id")
    params: dict = {"user_id": user_id}
    if native_lang:
        sql += " AND native_lang = :native_lang"
        params["native_lang"] = native_lang
    if target_lang:
        sql += " AND target_lang = :target_lang"
        params["target_lang"] = target_lang
    sql += " GROUP BY lesson_id, lesson_name, native_lang, target_lang ORDER BY lesson_id"
    rows = _db.fetch_all(sql, params)
    if not rows:
        return pd.DataFrame(columns=LESSON_COLS)
    return pd.DataFrame(rows)[LESSON_COLS]


def _db_get_lesson_phrases(user_id: str, lesson_id: int) -> pd.DataFrame:
    rows = _db.fetch_all(
        "SELECT lesson_id, phrase_id, native, target FROM custom_phrases "
        "WHERE user_id = :user_id AND lesson_id = :lesson_id ORDER BY phrase_id",
        {"user_id": user_id, "lesson_id": int(lesson_id)},
    )
    if not rows:
        return pd.DataFrame(columns=PHRASE_COLS)
    df = pd.DataFrame(rows)
    df["difficulty"] = 1  # neutral default, same as the CSV path
    return df[PHRASE_COLS]


def _db_add_lesson(user_id, lesson_name, native_lang, target_lang, cleaned) -> int:
    lesson_id = _db.fetch_one("SELECT nextval('custom_lesson_id_seq') AS id")["id"]
    now = datetime.now().isoformat(timespec="seconds")
    rows = [{
        "user_id": user_id, "lesson_id": lesson_id, "lesson_name": lesson_name,
        "phrase_id": i, "native_lang": native_lang, "target_lang": target_lang,
        "native": nat, "target": tgt, "created_at": now,
    } for i, (nat, tgt) in enumerate(cleaned, start=1)]
    _db.execute_many(
        "INSERT INTO custom_phrases "
        "(user_id, lesson_id, lesson_name, phrase_id, native_lang, target_lang, native, target, created_at) "
        "VALUES (:user_id, :lesson_id, :lesson_name, :phrase_id, :native_lang, :target_lang, :native, :target, :created_at)",
        rows,
    )
    return int(lesson_id)


def _db_delete_lesson(user_id: str, lesson_id: int) -> bool:
    existing = _db.fetch_one(
        "SELECT 1 FROM custom_phrases WHERE user_id = :user_id AND lesson_id = :lesson_id LIMIT 1",
        {"user_id": user_id, "lesson_id": int(lesson_id)},
    )
    if existing is None:
        return False
    _db.execute(
        "DELETE FROM custom_phrases WHERE user_id = :user_id AND lesson_id = :lesson_id",
        {"user_id": user_id, "lesson_id": int(lesson_id)},
    )
    return True


def _db_rename_lesson(user_id: str, lesson_id: int, new_name: str) -> bool:
    existing = _db.fetch_one(
        "SELECT 1 FROM custom_phrases WHERE user_id = :user_id AND lesson_id = :lesson_id LIMIT 1",
        {"user_id": user_id, "lesson_id": int(lesson_id)},
    )
    if existing is None:
        return False
    _db.execute(
        "UPDATE custom_phrases SET lesson_name = :name WHERE user_id = :user_id AND lesson_id = :lesson_id",
        {"user_id": user_id, "lesson_id": int(lesson_id), "name": new_name},
    )
    return True


# ─── Public API (unchanged signatures — callers never see which backend) ──

def load_all(user_id: str | None = None, prefer_sheets: bool = True) -> pd.DataFrame:
    """Load every custom phrase for the user (or all users if user_id is None).

    Kept for backward compatibility (nothing in this codebase calls it with
    user_id=None any more, but it's public API) — routes to Postgres when
    available, else the legacy CSV+Sheets path.
    """
    if _db_ok():
        _migrate_csv_once()
        sql = "SELECT * FROM custom_phrases"
        params = {}
        if user_id:
            sql += " WHERE user_id = :user_id"
            params["user_id"] = user_id
        rows = _db.fetch_all(sql, params)
        return pd.DataFrame(rows, columns=COLUMNS) if rows else pd.DataFrame(columns=COLUMNS)
    return _csv_load_all(user_id=user_id, prefer_sheets=prefer_sheets)


def list_user_lessons(user_id: str,
                       native_lang: str | None = None,
                       target_lang: str | None = None) -> pd.DataFrame:
    """Return a DataFrame [lesson_id, lesson_name, phrases, native_lang, target_lang]
    grouped per lesson, filtered to the user (and language pair if given)."""
    if _db_ok():
        _migrate_csv_once()
        return _db_list_user_lessons(user_id, native_lang, target_lang)

    df = _csv_load_all(user_id=user_id)
    if df.empty:
        return pd.DataFrame(columns=LESSON_COLS)
    if native_lang:
        df = df[df["native_lang"] == native_lang]
    if target_lang:
        df = df[df["target_lang"] == target_lang]
    if df.empty:
        return pd.DataFrame(columns=LESSON_COLS)
    out = (df.groupby(["lesson_id", "lesson_name", "native_lang", "target_lang"], dropna=False)
             .size().reset_index(name="phrases").sort_values("lesson_id"))
    return out.reset_index(drop=True)


def get_lesson_phrases(user_id: str, lesson_id: int) -> pd.DataFrame:
    """Return phrases for one user lesson in the format the 8-step flow expects.

    Output columns: lesson_id, phrase_id, difficulty, native, target.
    """
    if _db_ok():
        _migrate_csv_once()
        return _db_get_lesson_phrases(user_id, lesson_id)

    df = _csv_load_all(user_id=user_id)
    df = df[df["lesson_id"].astype("Int64") == int(lesson_id)]
    if df.empty:
        return pd.DataFrame(columns=PHRASE_COLS)
    df = df.sort_values("phrase_id").reset_index(drop=True)
    df["difficulty"] = 1
    return df[PHRASE_COLS]


def add_lesson(user_id: str,
                lesson_name: str,
                native_lang: str,
                target_lang: str,
                pairs: Iterable[tuple[str, str]]) -> int:
    """Create a new lesson with the given native↔target phrase pairs.

    Returns the assigned lesson_id. Empty pairs are filtered out.
    """
    cleaned = [(n.strip(), t.strip()) for n, t in pairs
               if n and t and n.strip() and t.strip()]
    if not cleaned:
        raise ValueError("Потрібна щонайменше одна валідна пара фраз")
    if not lesson_name.strip():
        lesson_name = f"My lesson {datetime.now():%Y-%m-%d %H:%M}"
    lesson_name = lesson_name.strip()

    if _db_ok():
        _migrate_csv_once()
        return _db_add_lesson(user_id, lesson_name, native_lang, target_lang, cleaned)
    return _csv_add_lesson(user_id, lesson_name, native_lang, target_lang, cleaned)


def delete_lesson(user_id: str, lesson_id: int) -> bool:
    """Remove all phrases of a given user lesson."""
    if _db_ok():
        _migrate_csv_once()
        return _db_delete_lesson(user_id, lesson_id)
    return _csv_delete_lesson(user_id, lesson_id)


def rename_lesson(user_id: str, lesson_id: int, new_name: str) -> bool:
    """Change the display name of a user lesson."""
    new_name = new_name.strip()
    if not new_name:
        return False
    if _db_ok():
        _migrate_csv_once()
        return _db_rename_lesson(user_id, lesson_id, new_name)
    return _csv_rename_lesson(user_id, lesson_id, new_name)
