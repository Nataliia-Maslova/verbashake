"""
engine/parallel.py — run independent per-item calls concurrently while keeping
Streamlit's ScriptRunContext available in the worker threads.

Written for the lazy lesson translations (engine/session.py,
engine/target_grammar_loader.py): opening a lesson used to translate its ~10
phrases one Gemini call after another (~2-3 s each -> ~25 s before the lesson
even rendered, found live 2026-09-20). The calls are independent, so they run
in a small thread pool instead. Every one of them goes through
engine.gemini's @_gated wrapper, which reads st.session_state / st.user (who
is calling, are they paid, daily quota) -- without the script-run context
copied onto the worker threads those reads fail, hence add_script_run_ctx.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

MAX_WORKERS = 8


def parallel_map(fn: Callable[[T], R], items: Iterable[T], max_workers: int = MAX_WORKERS) -> list[R]:
    """[fn(x) for x in items], concurrently, results in input order. `fn` must
    handle its own exceptions (an uncaught one propagates from here)."""
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        ctx = None

    def _init() -> None:
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(items)), initializer=_init) as pool:
        return list(pool.map(fn, items))
