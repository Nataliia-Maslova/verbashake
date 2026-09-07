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
    ("grammar",    "🗣️", APP_IMG_DIR / "vocab_school.jpg"),
    ("vocab",      "📖", APP_IMG_DIR / "vocab_basic.jpg"),
    ("phrasebook", "💬", APP_IMG_DIR / "vocab_greetings.jpg"),
    ("reading",    "🔤", APP_IMG_DIR / "reading_banner.jpg"),
    ("custom",     "📝", APP_IMG_DIR / "my_phrases_banner.jpg"),
    ("search",     "🔍", APP_IMG_DIR / "search_banner.jpg"),
]

# Module display names all route through this instead of a 4th hardcoded
# English list (2026-09-07 finding: app.py::MODULES, grammar.py's
# _SIDEBAR_MODULES, and this file's own now-removed _TYPE_LABEL/
# _SHORTCUT_MODULES-labels each had their own copy, none of them
# localized). "search" reuses the pre-existing "search_title" key
# (search_app.py) instead of a near-duplicate "module_search".
_MODULE_I18N_KEY = {
    "grammar": "module_grammar", "vocab": "module_vocab",
    "phrasebook": "module_phrasebook", "reading": "module_reading",
    "custom": "module_custom", "search": "search_title", "path": "module_path",
}


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
    st.markdown(f"### {i18n.get(native, 'path_shortcuts_label')}")
    cols = st.columns(len(_SHORTCUT_MODULES))
    for col, (key, icon, img_path) in zip(cols, _SHORTCUT_MODULES):
        with col:
            label = i18n.get(native, _MODULE_I18N_KEY[key])
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


@st.cache_data(show_spinner=False)
def _grammar_topic_map(native_lang: str, target_lang: str) -> dict:
    """{lesson_id: native-language topic name} for Grammar -- reuses the
    same topic_{lang} columns Step 1's rule explanation and the lesson
    picker already resolve (engine.loader.get_lesson_topics), instead of
    duplicating a fresh translation. Cached per (native, target) since it
    loads the whole Grammar dataframe -- the same cost app.py's own
    @st.cache_data _grammar_lesson_ids() already pays for the same data.
    """
    try:
        from grammar import _load_grammar, DB_PATH
        from engine.loader import get_lesson_topics
        df = _load_grammar(DB_PATH, native_lang, target_lang)
        return get_lesson_topics(df, native_lang=native_lang)
    except Exception:
        return {}


def _localized_topic(unit: dict, utype: str, native_lang: str, target_lang: str) -> str:
    """Native-language display name for a My Path unit's topic.

    content_units.topic is always the English canonical form (schema.sql:
    "topic tag, English canonical form" -- it's the recommender's matching
    key, not display text) -- confirmed live 2026-09-07: a Russian-native/
    Catalan-target account saw the raw English topic ("Describing things")
    on this exact card, a third language mixed in alongside the native-
    language chrome and the Catalan lesson content itself.

    Grammar: resolved via the pre-existing topic_{lang} columns (same
    source Step 1's rule explanation and the lesson picker already use) --
    reusing them, not a fresh translation, keeps this card's name
    consistent with what the student sees once they actually open the
    lesson. Vocab/Phrasebook: topic is a CEFR-J/Word-Bank SHEET name
    ("Greetings, Basics & Courtesy") with no pre-existing per-language
    translation anywhere in the data -- translated on demand through the
    same engine.gemini.translate_phrase() CEFR-J vocabulary already uses
    (Postgres-cached forever after the first student who sees a given
    (topic, native_lang) pair, not paid-gated -- @_gated with a 300/day
    free allowance, not @_require_paid). Reading (no topic) and an English
    native (topic is already in English) fall through unchanged.
    """
    topic = unit.get("topic") or "General"
    if native_lang == "English":
        return topic
    if utype == "grammar":
        lid = _recommender.parse_unit_id(unit["unit_id"]).get("lesson_id")
        return _grammar_topic_map(native_lang, target_lang).get(lid) or topic
    if utype in ("vocab", "phrasebook"):
        try:
            return _gemini.translate_phrase(topic, "English", native_lang)
        except Exception:
            return topic
    return topic


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
        if st.button(i18n.get(native, "main_menu"), use_container_width=True, key="path_home"):
            st.session_state["_show_launcher"] = True
            st.rerun()

        st.markdown("---")
        st.markdown(f"**👤** {user}")
        st.markdown(f"**{native} → {target}**")
        st.markdown("")

        # Percentages only, not raw "done / total" counts -- the full catalog
        # size (1000+ lessons) read as a discouragingly huge, unreachable
        # target (Natalia's sister's feedback, 2026-09-06).
        pct = stats["pct"]
        st.markdown(
            f'<div style="font-size:.7rem;color:#aaa;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:3px">{i18n.get(native, "path_coverage_label")}</div>'
            f'{_pct_bar(pct)}'
            f'<div style="font-size:.72rem;color:#aaa;margin-top:2px">'
            f'{pct:.0f}%</div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")

        # Mini type breakdown
        for key, color in [
            ("grammar", "var(--mova-indigo)"),
            ("vocab",   "#f59e0b"),
            ("reading", "var(--mova-mint)"),
        ]:
            label = i18n.get(native, _MODULE_I18N_KEY[key])
            done  = stats[f"done_{key}"]
            total = stats[f"total_{key}"]
            _pct  = round(done / total * 100) if total else 0
            st.markdown(
                f'<div style="margin:6px 0">'
                f'<div style="display:flex;justify-content:space-between;'
                f'font-size:.75rem;color:#aaa;margin-bottom:2px">'
                f'<span>{label}</span><span>{_pct}%</span></div>'
                f'{_pct_bar(_pct, color)}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Page header ──────────────────────────────────────────────────────────
    st.markdown(f"## {i18n.get(native, 'path_title')}")

    # ── Single-module shortcuts ─────────────────────────────────────────────
    # Moved back up here (2026-08-27, Natalia) -- her first request was "add
    # them after My Path", read at the time as after all of My Path's OWN
    # content; turned out she meant right at the top, under the header,
    # where the swipe strip used to live before it got replaced with these
    # plain buttons.
    _render_module_shortcuts(user, native, target)

    # ── Overall progress bar ─────────────────────────────────────────────────
    # Shows percentages only, not raw "done / total" counts -- the full catalog
    # size (1000+ lessons) read as a discouragingly huge, unreachable target
    # (Natalia's sister's feedback, 2026-09-06).
    col1, col2, col3 = st.columns(3)
    for col, key in [(col1, "grammar"), (col2, "vocab"), (col3, "reading")]:
        label = i18n.get(native, _MODULE_I18N_KEY[key])
        total = stats[f"total_{key}"]
        done  = stats[f"done_{key}"]
        _pct  = round(done / total * 100) if total else 0
        with col:
            st.metric(label, f"{_pct}%")

    st.progress(stats["pct"] / 100)
    st.caption(i18n.get(native, "path_overall_progress").format(pct=f"{stats['pct']:.0f}"))

    if stats["total_units"] == 0:
        # Dev/ops-facing state (an unseeded DB) -- a real production student
        # never sees this, left in English (the same rationale as the
        # seed-script's own console output).
        st.info(
            "No content is tagged yet — run `python scripts/seed_content_units.py` "
            "against the database to populate the learning path."
        )
        return

    unit = stats.get("current_unit")

    if unit is None:
        st.success(i18n.get(native, "path_all_caught_up"))
        if st.button(i18n.get(native, "path_start_over_btn"), type="secondary"):
            _recommender.reset_user(user, target)
            st.rerun()
        return

    # ── Next lesson card ─────────────────────────────────────────────────────
    st.markdown(f"### {i18n.get(native, 'path_next_lesson_title')}")

    utype  = unit["module"]
    u_icon = _TYPE_ICON.get(utype, "📚")
    u_lbl  = i18n.get(native, _MODULE_I18N_KEY.get(utype, "module_grammar"))
    u_col  = _TYPE_COLOR.get(utype, "var(--mova-indigo)")
    topic  = _localized_topic(unit, utype, native, target)
    parsed = _recommender.parse_unit_id(unit["unit_id"])
    lid    = parsed["lesson_id"]

    sub = f"{i18n.get(native, 'word_lesson')} {lid}"
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
        _start_label = f"▶ {i18n.get(native, 'start_prefix')}"
        if st.button(_start_label, type="primary", use_container_width=True, key="path_start"):
            _launch_unit(unit, user, native, target)

    if utype == "grammar":
        easier = _recommender.grammar_neighbor(target, lid, -1)
        harder = _recommender.grammar_neighbor(target, lid, +1)
        ec, hc = st.columns(2)
        with ec:
            if st.button(i18n.get(native, "path_easier_btn"), disabled=easier is None,
                         use_container_width=True, key="path_easier"):
                _launch_unit(easier, user, native, target)
        with hc:
            if st.button(i18n.get(native, "path_harder_btn"), disabled=harder is None,
                         use_container_width=True, key="path_harder"):
                _launch_unit(harder, user, native, target)
        _render_topic_explanation(unit, native, target)

    # ── Skip button ──────────────────────────────────────────────────────────
    st.markdown("")
    if st.button(i18n.get(native, "path_skip_btn"), type="secondary", key="path_skip"):
        # No fixed sequence to advance past — nudge this unit's SRS due date
        # forward so a different lesson surfaces next time.
        _recommender.record_result(user, target, unit["unit_id"], correct=True)
        st.rerun()