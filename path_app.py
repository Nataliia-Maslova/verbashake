"""
path_app.py — "My Path" guided learning screen for IMLLS.

Shows the student's progress and launches the recommender's top-scored lesson
with a single click. Unlike the old fixed curriculum sequence, this is a live
snapshot: finishing a lesson updates mastery/SRS immediately (via
LessonSession.score()/complete() in engine/session.py), so the recommendation
can reorder itself on the very next render — there is no "advance to index N"
step to run when returning here, get_stats() just reflects current state.

Flow:
  1. User clicks "My Path" on the launcher → app.py sets active_module="path"
  2. path_app.main() renders progress + "▶ Start next lesson" button
  3. Button calls _launch_unit() → sets session state + query params → rerun
  4. app.py routes to grammar / vocab / reading module for that lesson
     (session_state["_return_module"] is preserved across the lesson)
  5. When the lesson finishes, _clear_all() / clear_all() in grammar/reading
     reads _return_module and sets active_module to it (defaults to "path",
     since My Path is _launch_unit()'s original and most common caller --
     search_app.py also reuses _launch_unit() to jump into a lesson from a
     search hit, passing return_module="search" so exiting the lesson goes
     back to the search results instead of always landing on My Path)
  6. That screen (My Path or Search) re-renders with fresh state
"""
from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote as _quote

import streamlit as st

from engine import recommender as _recommender
from engine import gemini as _gemini
from engine import i18n

ROOT        = Path(__file__).parent
APP_IMG_DIR = ROOT / "static" / "app_images"


def _img_b64(path) -> str:
    """Return base64 data-URL for an image, or empty string if missing.
    Duplicated from app.py::_img_b64 (not imported) for the same reason
    _switch_module() below duplicates _switch_to() -- app.py already
    imports path_app for its router, so the reverse import would be
    circular."""
    p = Path(path)
    if not p.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()

_TYPE_ICON  = {"reading": "🔤", "grammar": "🗣️", "vocab": "📖", "phrasebook": "💬"}
_TYPE_LABEL = {"reading": "Reading",    "grammar": "Grammar",    "vocab": "Vocabulary",
               "phrasebook": "Phrasebook"}
_TYPE_COLOR = {
    "reading": "var(--mova-mint)",
    "grammar": "var(--mova-indigo)",
    "vocab":   "#f59e0b",
    "phrasebook": "var(--mova-coral)",
}

# Single-module shortcuts, shown as plain buttons below My Path's own
# content (design review, 2026-08-27). First tried a custom swipeable
# scroll-snap strip -- looked right, but two rounds of live testing on
# Natalia's own machine (onclick attributes silently stripped by
# st.markdown, then scroll-snap locking scrollLeft in place at some
# viewport widths) both needed iframe/JS workarounds and STILL didn't
# swipe for her. Real st.button widgets have none of that fragility --
# guaranteed to work everywhere Streamlit itself works, at the cost of a
# tap instead of a swipe.
# Images match app.py::MODULES' "img" entries -- same artwork the launcher
# grid used to show, reused here instead of the plain emoji (design review,
# 2026-08-27, Natalia).
_SHORTCUT_MODULES = [
    ("grammar",    "🗣️", "Grammar",     APP_IMG_DIR / "vocab_school.jpg"),
    ("vocab",      "📖", "Vocabulary",  APP_IMG_DIR / "vocab_basic.jpg"),
    ("phrasebook", "💬", "Phrasebook",  APP_IMG_DIR / "vocab_greetings.jpg"),
    ("reading",    "🔤", "Reading",     APP_IMG_DIR / "reading_banner.jpg"),
    ("custom",     "📝", "My Phrases",  APP_IMG_DIR / "my_phrases_banner.jpg"),
    ("search",     "🔍", "Search",      APP_IMG_DIR / "search_banner.jpg"),
]


def _switch_module(module_key: str, user: str, native: str, target: str) -> None:
    """Same wipe-and-reset app.py::_switch_to() does -- duplicated locally
    (not imported) because app.py already imports path_app for its router,
    so the reverse import would be circular."""
    for k in list(st.session_state):
        del st.session_state[k]
    st.session_state["active_module"]   = module_key
    st.session_state["launcher_user"]   = user
    st.session_state["launcher_native"] = native
    st.session_state["launcher_target"] = target
    st.query_params["module"] = module_key
    st.rerun()


def _render_module_shortcuts(user: str, native: str, target: str) -> None:
    st.markdown("### Or open a module directly")
    cols = st.columns(len(_SHORTCUT_MODULES))
    for col, (key, icon, label, img_path) in zip(cols, _SHORTCUT_MODULES):
        with col:
            b64 = _img_b64(img_path)
            if b64:
                # Shorter than the first pass (72px -> 44px, design review,
                # 2026-08-27): on a real phone st.columns(5) stacks into 5
                # full-width rows (Streamlit switches multi-column layouts to
                # a vertical stack below ~640px viewport width, regardless of
                # column count/ratio -- confirmed on Natalia's own screenshot,
                # not a workaround-able CSS quirk) -- 5x a wide banner crop
                # pushed the actual "Next lesson" card a full screen down.
                # Roughly button-height now, so the block reads as a compact
                # icon list instead of 5 stacked banners.
                st.markdown(
                    f'<img src="{b64}" style="width:100%;height:44px;'
                    f'object-fit:cover;border-radius:8px;margin-bottom:4px"/>',
                    unsafe_allow_html=True,
                )
                btn_label = label
            else:
                # Missing file (shouldn't happen -- these ship with the repo)
                # falls back to the emoji instead of a broken/blank image.
                btn_label = f"{icon}\n\n{label}"
            if st.button(btn_label, key=f"path_shortcut_{key}",
                         use_container_width=True):
                _switch_module(key, user, native, target)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _launch_unit(unit: dict, user: str, native: str, target: str,
                  return_module: str = "path") -> None:
    """
    Set up session state so that the next rerun lands inside the right module
    at the right lesson.  Uses the existing vnav_lesson query-param bridge
    that grammar.py and reading_app.py already support.

    return_module: where grammar.py/reading_app.py's _clear_all() should
    send the user once they exit the lesson (default "path", since My Path
    is this function's original caller). search_app.py passes "search" so a
    lesson opened from a search hit returns to the search results instead
    of always landing on My Path.
    """
    parsed = _recommender.parse_unit_id(unit["unit_id"])
    utype  = parsed["module"]
    lid    = parsed["lesson_id"]

    st.session_state["_return_module"] = return_module

    if utype == "reading":
        lang_code = parsed["lang_code"]
        st.session_state["r_lang"] = lang_code
        st.session_state["active_module"] = "reading"
        st.query_params.update({
            "module":       "reading",
            "vnav_lesson":  str(lid),
            "r_lang":       lang_code,
            "vnav_user":    _quote(user),
        })
    elif utype == "grammar":
        st.session_state["active_module"] = "grammar"
        st.query_params.update({
            "module":       "grammar",
            "vnav_lesson":  str(lid),
            "vnav_native":  _quote(native),
            "vnav_target":  _quote(target),
            "vnav_user":    _quote(user),
        })
    elif utype == "vocab":
        st.session_state["active_module"] = "vocab"
        st.query_params.update({
            "module":       "vocab",
            "vnav_lesson":  str(lid),
            "vnav_native":  _quote(native),
            "vnav_target":  _quote(target),
            "vnav_user":    _quote(user),
        })
    elif utype == "phrasebook":
        st.session_state["active_module"] = "phrasebook"
        st.query_params.update({
            "module":       "phrasebook",
            "vnav_lesson":  str(lid),
            "vnav_native":  _quote(native),
            "vnav_target":  _quote(target),
            "vnav_user":    _quote(user),
        })

    st.rerun()


def _render_topic_explanation(unit: dict, native_lang: str, target_lang: str) -> None:
    """
    "Explain this topic" for the recommended Grammar unit, right on the My
    Path card -- Наталія's request, 2026-08-24: previewing the rule before
    committing to "Start" (grammar.py's Step 1 already has this same panel
    once the lesson is actually opened; this lets a student decide FROM
    My Path whether to start it at all).

    Grammar only, same as Step 1's panel -- Vocab/Phrasebook don't have a
    "rule" the same way. Reuses explain_lesson_rule() with an empty
    seed_phrases list: My Path doesn't load the lesson's own dataframe (it
    only has the content_units summary row), and the function already
    handles no-seed-phrases gracefully (it just leans on the topic name
    alone) -- the cache key is (topic_key, level, target_lang, native_lang)
    only, seed_phrases never part of it, so this shares the exact same
    cached row Step 1 would produce for the same lesson, as long as both
    pass the same topic_key (see explain_lesson_rule's docstring).
    """
    level = unit.get("level") or "A1"
    # content_units.topic is seeded from topic_en (scripts/seed_content_units.py)
    # -- already language-invariant, so it doubles as topic_key directly.
    topic = unit.get("topic") or "General"
    # Keyed by unit_id (not a flat key) so a stale explanation from a
    # previously-recommended unit can never show under a new one once the
    # recommender reorders (same reasoning as grammar.py's
    # s1_explanation_{lesson_id}).
    state_key = f"path_explanation_{unit['unit_id']}"
    with st.expander(i18n.get(native_lang, "rule_explanation_title"), expanded=False):
        if st.button(i18n.get(native_lang, "rule_explanation_btn"), key="path_explain_btn"):
            try:
                with st.spinner("..."):
                    st.session_state[state_key] = _gemini.explain_lesson_rule(
                        topic, level, target_lang, native_lang, [], topic_key=topic,
                    )
            except _gemini.PaidFeatureRequired:
                st.warning("⭐ Premium feature, or you've hit today's free AI limit for it — try again tomorrow, or upgrade to Premium for unlimited.")
                if st.button("⭐ Go to Upgrade", key="path_explain_upsell"):
                    st.session_state["_show_launcher"] = True
                    st.rerun()

        explanation = st.session_state.get(state_key)
        if explanation:
            st.markdown(explanation.get("rule", ""))
            for ex in explanation.get("examples", []):
                st.markdown(f"- **{ex.get('target', '')}** — {ex.get('native', '')}")
            if explanation.get("exceptions"):
                st.markdown(f"**{i18n.get(native_lang, 'rule_exceptions_label')}**")
                for exc in explanation["exceptions"]:
                    st.markdown(f"- {exc}")


def _pct_bar(pct: float, color: str = "var(--mova-indigo)") -> str:
    return (
        f'<div style="background:var(--mova-surface-3);border-radius:6px;'
        f'height:7px;overflow:hidden;margin:4px 0">'
        f'<div style="height:7px;border-radius:6px;background:{color};'
        f'width:{min(pct, 100):.1f}%;transition:width .4s"></div></div>'
    )


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    user   = st.session_state.get("launcher_user",   "student1")
    native = st.session_state.get("launcher_native", "Ukrainian")
    target = st.session_state.get("launcher_target", "English")

    st.session_state.pop("curriculum_advance_pending", None)  # no-op under the recommender

    # get_stats()/get_path_next() (engine/recommender.py) exclude
    # non-launchable "target_grammar" units at the source now -- this page
    # used to filter its own copy of stats["upcoming"] here after a real
    # KeyError (target_grammar units have no lesson_id, per CLAUDE.md's
    # uk->es example), but that only protected this one call site.
    stats = _recommender.get_stats(user, target)

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        if st.button("🏠 Main menu", use_container_width=True, key="path_home"):
            st.session_state["_show_launcher"] = True
            st.rerun()

        st.markdown("---")
        st.markdown(f"**👤** {user}")
        st.markdown(f"**{native} → {target}**")
        st.markdown("")

        pct = stats["pct"]
        st.markdown(
            f'<div style="font-size:.7rem;color:#aaa;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:3px">Coverage</div>'
            f'{_pct_bar(pct)}'
            f'<div style="font-size:.72rem;color:#aaa;margin-top:2px">'
            f'{stats["done_total"]} / {stats["total_units"]} · {pct:.0f}%</div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")

        # Mini type breakdown
        for key, label, color in [
            ("grammar", "Grammar",    "var(--mova-indigo)"),
            ("vocab",   "Vocabulary", "#f59e0b"),
            ("reading", "Reading",    "var(--mova-mint)"),
        ]:
            done  = stats[f"done_{key}"]
            total = stats[f"total_{key}"]
            _pct  = round(done / total * 100) if total else 0
            st.markdown(
                f'<div style="margin:6px 0">'
                f'<div style="display:flex;justify-content:space-between;'
                f'font-size:.75rem;color:#aaa;margin-bottom:2px">'
                f'<span>{label}</span><span>{done}/{total}</span></div>'
                f'{_pct_bar(_pct, color)}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Page header ──────────────────────────────────────────────────────────
    st.markdown("## 🗺️ My Learning Path")

    # ── Single-module shortcuts ─────────────────────────────────────────────
    # Moved back up here (2026-08-27, Natalia) -- her first request was "add
    # them after My Path", read at the time as after all of My Path's OWN
    # content; turned out she meant right at the top, under the header,
    # where the swipe strip used to live before it got replaced with these
    # plain buttons.
    _render_module_shortcuts(user, native, target)

    # ── Overall progress bar ─────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Grammar",    f"{stats['done_grammar']} / {stats['total_grammar']}")
    with col2:
        st.metric("Vocabulary", f"{stats['done_vocab']}  / {stats['total_vocab']}")
    with col3:
        st.metric("Reading",    f"{stats['done_reading']} / {stats['total_reading']}")

    st.progress(stats["pct"] / 100)
    st.caption(f"{stats['done_total']} of {stats['total_units']} lessons attempted · {stats['pct']:.0f}%")

    if stats["total_units"] == 0:
        st.info(
            "No content is tagged yet — run `python scripts/seed_content_units.py` "
            "against the database to populate the learning path."
        )
        return

    unit = stats.get("current_unit")

    if unit is None:
        st.success("🎉 **You're all caught up!** No lessons are due for review right now.")
        if st.button("🔄 Start over", type="secondary"):
            _recommender.reset_user(user, target)
            st.rerun()
        return

    # ── Next lesson card ─────────────────────────────────────────────────────
    st.markdown("### ▶ Next lesson")

    utype  = unit["module"]
    u_icon = _TYPE_ICON.get(utype, "📚")
    u_lbl  = _TYPE_LABEL.get(utype, utype.title())
    u_col  = _TYPE_COLOR.get(utype, "var(--mova-indigo)")
    topic  = unit.get("topic") or "General"
    parsed = _recommender.parse_unit_id(unit["unit_id"])
    lid    = parsed["lesson_id"]

    sub = f"Lesson {lid}"
    if unit.get("level"):
        sub += f" · {unit['level']}"

    left, right = st.columns([4, 1])
    with left:
        st.markdown(
            f'<div style="background:var(--mova-card);border:2px solid {u_col};'
            f'border-radius:12px;padding:20px 24px">'
            f'<div style="font-size:.75rem;color:{u_col};text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:6px">{u_icon} {u_lbl}</div>'
            f'<div style="font-size:1.25rem;font-weight:700">{topic}</div>'
            f'<div style="color:var(--mova-ink-2);font-size:.88rem;margin-top:4px">{sub}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        if st.button("▶ Start", type="primary", use_container_width=True, key="path_start"):
            _launch_unit(unit, user, native, target)

    if utype == "grammar":
        easier = _recommender.grammar_neighbor(target, lid, -1)
        harder = _recommender.grammar_neighbor(target, lid, +1)
        ec, hc = st.columns(2)
        with ec:
            if st.button("⬅ Easier", disabled=easier is None,
                         use_container_width=True, key="path_easier"):
                _launch_unit(easier, user, native, target)
        with hc:
            if st.button("Try harder ➡", disabled=harder is None,
                         use_container_width=True, key="path_harder"):
                _launch_unit(harder, user, native, target)
        _render_topic_explanation(unit, native, target)

    # ── Skip button ──────────────────────────────────────────────────────────
    st.markdown("")
    if st.button("⏭ Skip this lesson", type="secondary", key="path_skip"):
        # No fixed sequence to advance past — nudge this unit's SRS due date
        # forward so a different lesson surfaces next time.
        _recommender.record_result(user, target, unit["unit_id"], correct=True)
        st.rerun()