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
from sqlalchemy.exc import DBAPIError, OperationalError

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
    last_exc: DBAPIError | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except DBAPIError as e:
            # A dropped connection also surfaces as InterfaceError ("connection
            # already closed"); this is what replaces pool_pre_ping, see get_engine().
            if not (isinstance(e, OperationalError) or e.connection_invalidated):
                raise
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


def _database_url() -> str:
    try:
        url = st.secrets.get("DATABASE_URL")
    except Exception:
        url = None
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not found in secrets.toml or environment")
    return url


# Two small pools, at most 15 connections between them: Supabase's session
# pooler allows 15 per project by default. No pool_pre_ping on either: it added
# a round trip to Ireland to every query, and a connection the pooler dropped
# is already retried by _with_retry (checked by killing one, 2026-11-02).
@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    return create_engine(_database_url(), pool_recycle=300, pool_size=2, max_overflow=3)


@st.cache_resource(show_spinner=False)
def _read_engine() -> Engine:
    """Autocommit from the start: one round trip for a read instead of three.
    A pool of its own, because switching a shared connection's mode costs a
    round trip of its own."""
    return create_engine(_database_url(), pool_recycle=300, pool_size=5, max_overflow=5,
                         isolation_level="AUTOCOMMIT")


# One click reruns the whole script, and My Path alone asked for the same rows
# up to 8 times: 24 queries, 6.2 s of a 6.3 s click (measured 2026-11-02).
# So a SELECT reaches the database once per run; begin_run() starts each run
# empty and any write through this module empties it again.
_RUN_CACHE_KEY = "_db_run_cache"


def begin_run() -> None:
    """Called first thing in app.main() on every rerun."""
    st.session_state[_RUN_CACHE_KEY] = {}


def _run_cache() -> dict | None:
    """This run's cache, or None outside a Streamlit run (scripts, tests)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx(suppress_warning=True) is None:
            return None
        return st.session_state.setdefault(_RUN_CACHE_KEY, {})
    except Exception:
        return None


def _clear_run_cache() -> None:
    cache = _run_cache()
    if cache:
        cache.clear()


def _query(sql: str, params: dict | None) -> list[dict]:
    def _do():
        with _read_engine().connect() as conn:
            rows = conn.execute(text(sql), params or {})
            return [dict(r._mapping) for r in rows]
    return _with_retry(_do)


def fetch_all(sql: str, params: dict | None = None, fresh: bool = False) -> list[dict]:
    """`fresh` skips this run's cache, for a counter other threads are raising."""
    cache = None if fresh or sql.lstrip()[:6].upper() != "SELECT" else _run_cache()
    if cache is None:
        return _query(sql, params)
    key = (sql, repr(sorted((params or {}).items())))
    if key not in cache:
        cache[key] = _query(sql, params)
    return [dict(r) for r in cache[key]]  # callers may change what they get


def fetch_one(sql: str, params: dict | None = None, fresh: bool = False) -> dict | None:
    rows = fetch_all(sql, params, fresh=fresh)
    return rows[0] if rows else None


def execute(sql: str, params: dict | None = None) -> None:
    def _do():
        with get_engine().begin() as conn:
            conn.execute(text(sql), params or {})
    _with_retry(_do)
    _clear_run_cache()


def execute_many(sql: str, param_list: list[dict]) -> None:
    if not param_list:
        return
    def _do():
        with get_engine().begin() as conn:
            conn.execute(text(sql), param_list)
    _with_retry(_do)
    _clear_run_cache()


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
