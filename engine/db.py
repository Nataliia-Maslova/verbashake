"""
engine/db.py — Postgres connection layer (Supabase or any Postgres provider).

Used by engine/recommender.py and engine/gamification.py. Connection string
comes from st.secrets["DATABASE_URL"] or env DATABASE_URL — a standard
`postgresql://user:pass@host:port/dbname` string (Supabase: Project Settings →
Database → Connection string → URI, "Session pooler" mode recommended for
Streamlit's per-rerun connections).

Schema: see schema.sql at the repo root — run it once against a fresh DB
before using this module.
"""
from __future__ import annotations

import os
import re
import time

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# scripts/seed_content_units.py hit this same Supabase pooler behavior at
# bulk-write scale (connection dropped mid-round-trip, not just on connect --
# pool_pre_ping doesn't catch it) and worked around it locally with its own
# retry loop (CLAUDE.md, 2026-08-21/22). That fix never made it back to this
# module, so every OTHER caller (engine.recommender, engine.gamification,
# engine.billing...) still had a single-shot query that fails silently
# wherever its own try/except happens to swallow the exception -- confirmed
# 2026-08-23: engine.recommender.record_result() from a real, long-running
# Streamlit process (not the seed script's short-lived one) hit exactly this
# and a real student's target_grammar practice attempt recorded nothing,
# silently, with no error surfaced anywhere. Centralizing the retry here
# fixes it for every caller at once instead of re-adding a local loop
# per call site.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5


def _with_retry(fn):
    last_exc: OperationalError | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except OperationalError as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BASE_DELAY * (attempt + 1))
    raise last_exc


def _safe_identifier(name: str) -> str:
    """
    Guard for table/column names interpolated into SQL text (see upsert()
    below) — these can't go through bind parameters like values can. Every
    caller in this codebase passes hardcoded literals, so this should never
    trip; it exists so a future caller that accidentally threads user input
    into a table/column name fails loudly instead of opening a SQL
    injection hole.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    try:
        url = st.secrets.get("DATABASE_URL")
    except Exception:
        url = None
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not found in secrets.toml or environment")
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    def _do():
        with get_engine().connect() as conn:
            rows = conn.execute(text(sql), params or {})
            return [dict(r._mapping) for r in rows]
    return _with_retry(_do)


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: dict | None = None) -> None:
    def _do():
        with get_engine().begin() as conn:
            conn.execute(text(sql), params or {})
    _with_retry(_do)


def execute_many(sql: str, param_list: list[dict]) -> None:
    if not param_list:
        return
    def _do():
        with get_engine().begin() as conn:
            conn.execute(text(sql), param_list)
    _with_retry(_do)


def upsert(table: str, keys: dict, values: dict, touch_updated_at: bool = True) -> None:
    """
    Generic upsert: INSERT ... ON CONFLICT (keys) DO UPDATE SET values.
    `keys` identify the row (become the conflict target + WHERE-equivalent),
    `values` are the non-key columns to set. `updated_at` (if the table has
    the column, true for every table in schema.sql) is refreshed to now() on
    every update — DEFAULT now() only fires on the initial INSERT, not on a
    conflict UPDATE, so this has to be set explicitly here.
    """
    table = _safe_identifier(table)
    all_cols = {**keys, **values}
    cols = [_safe_identifier(c) for c in all_cols.keys()]
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    conflict_cols = ", ".join(_safe_identifier(c) for c in keys.keys())
    update_parts = [f"{c} = EXCLUDED.{c}" for c in (_safe_identifier(c) for c in values.keys())]
    if touch_updated_at:
        update_parts.append("updated_at = now()")
    update_set = ", ".join(update_parts)

    if update_set:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) DO NOTHING"
        )
    execute(sql, all_cols)


def is_available() -> bool:
    try:
        get_engine()
        return True
    except Exception:
        return False
