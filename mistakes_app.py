"""
mistakes_app.py — "My mistakes" screen (2026-09-20).

Shows the grammar mistakes persisted by grammar.py::_record_mistake() into
user_mistakes (engine/mistakes.py): still-open ones (default), resolved ones,
and the topics that keep recurring. A mistake becomes "resolved" when the
student writes the same structure correctly in the error-drill step
(grammar.py::_error_drill_step). Each row can jump straight into the lesson
the mistake was attributed to, reusing path_app.py's _launch_unit() bridge
(return_module="mistakes" so exiting the lesson lands back here).

Scoped to the current target_lang, like everything else that keys off
(user, target_lang). Rows are best-effort by design (see engine/mistakes.py)
-- an unavailable DB just shows the empty state.
"""
from __future__ import annotations

import streamlit as st

from engine import i18n
from engine import mistakes as _mistakes
from engine import recommender as _recommender
from engine.gamification import sidebar_widget as _gami_sidebar
from path_app import _launch_unit

_LAUNCHABLE = {"grammar", "vocab", "phrasebook", "reading"}
_MAX_ROWS = 100


def _clear_and_home() -> None:
    """Same wipe-and-return-to-launcher pattern as search_app.py's copy."""
    _keep = {k: st.session_state[k] for k in
             ("launcher_user", "launcher_native", "launcher_target", "_dark_mode")
             if k in st.session_state}
    for k in list(st.session_state):
        del st.session_state[k]
    st.session_state.update(_keep)
    st.query_params.clear()


def _launchable_unit(unit_id: str | None) -> bool:
    if not unit_id:
        return False
    try:
        parsed = _recommender.parse_unit_id(unit_id)
    except Exception:
        return False
    return parsed.get("module") in _LAUNCHABLE and "lesson_id" in parsed


def _render_row(m: dict, idx: int, user: str, native: str, target: str, resolved: bool) -> None:
    with st.container(border=True):
        st.markdown(f"~~{m['original']}~~ → **{m['corrected']}**")
        if m.get("explanation"):
            st.caption(m["explanation"])
        meta = [x for x in (m.get("topic_en"),
                            (m["resolved_at"] if resolved else m["created_at"]).strftime("%Y-%m-%d")) if x]
        st.caption(" · ".join(meta))
        if not resolved and _launchable_unit(m.get("unit_id")):
            if st.button(i18n.get(native, "mistakes_practice_btn"),
                         key=f"mistake_go_{idx}_{m['id']}"):
                _launch_unit({"unit_id": m["unit_id"]}, user, native, target,
                             return_module="mistakes")


def main() -> None:
    user   = st.session_state.get("launcher_user",   "student1")
    native = st.session_state.get("launcher_native", "Ukrainian")
    target = st.session_state.get("launcher_target", "English")

    with st.sidebar:
        _gami_sidebar(user)
        st.markdown(
            '<div style="font-size:.7rem;color:var(--mova-ink-3);'
            'text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">'
            f'{i18n.get(native, "pq_module_label")}</div>',
            unsafe_allow_html=True,
        )
        for _mk, _mi, _mn in (
            ("grammar",    "🗣️", i18n.get(native, "module_grammar")),
            ("vocab",      "📖", i18n.get(native, "module_vocab")),
            ("phrasebook", "💬", i18n.get(native, "module_phrasebook")),
            ("reading",    "🔤", i18n.get(native, "module_reading")),
            ("custom",     "📝", i18n.get(native, "module_custom")),
            ("search",     "🔍", i18n.get(native, "search_title")),
            ("songs",      "🎵", i18n.get(native, "module_songs")),
            ("mistakes",   "✏️", i18n.get(native, "mistakes_title")),
        ):
            _is_current = (_mk == "mistakes")
            if st.button(f"{_mi} {_mn}", key=f"sb_mod_{_mk}", use_container_width=True,
                         type="primary" if _is_current else "secondary",
                         disabled=_is_current):
                _dark = st.session_state.get("_dark_mode", False)
                for _k in list(st.session_state):
                    del st.session_state[_k]
                st.session_state["active_module"]   = _mk
                st.session_state["launcher_user"]   = user
                st.session_state["launcher_native"] = native
                st.session_state["launcher_target"] = target
                st.session_state["_dark_mode"]      = _dark
                st.query_params["module"] = _mk
                st.rerun()
        if st.button(i18n.get(native, "main_menu"), use_container_width=True, key="mistakes_home"):
            _clear_and_home()
            st.rerun()

    st.title(f"✏️ {i18n.get(native, 'mistakes_title')}")
    st.caption(f"{native} → {target}")

    c = _mistakes.counts(user, target)
    if c["open"] == 0 and c["resolved"] == 0:
        st.info(i18n.get(native, "mistakes_empty"))
        return

    m1, m2 = st.columns(2)
    m1.metric(i18n.get(native, "mistakes_open"), c["open"])
    m2.metric(i18n.get(native, "mistakes_resolved"), c["resolved"])
    st.caption(i18n.get(native, "mistakes_intro"))

    top = _mistakes.top_open_topics(user, target)
    if top:
        st.markdown(f"#### {i18n.get(native, 'mistakes_topics_title')}")
        for t in top:
            st.markdown(f"- **{t['topic_en']}** · {t['n']}")

    _opt_open = i18n.get(native, "mistakes_open")
    _opt_done = i18n.get(native, "mistakes_resolved")
    view = st.radio(i18n.get(native, "mistakes_title"), [_opt_open, _opt_done],
                    horizontal=True, key="mistakes_view", label_visibility="collapsed")
    show_resolved = view == _opt_done

    rows = _mistakes.list_mistakes(user, target, resolved=show_resolved, limit=_MAX_ROWS)
    if not rows:
        st.info(i18n.get(native, "mistakes_none_resolved" if show_resolved else "mistakes_none_open"))
        return
    for i, m in enumerate(rows):
        _render_row(m, i, user, native, target, show_resolved)
    if len(rows) == _MAX_ROWS:
        st.caption(i18n.get(native, "mistakes_limit_note").format(n=_MAX_ROWS))


if __name__ == "__main__":
    main()
