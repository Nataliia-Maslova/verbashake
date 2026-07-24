"""
path_app.py — "My Path" guided learning screen for IMLLS.

Shows the student's progress through the structured curriculum and
launches the next lesson with a single click.

Flow:
  1. User clicks "My Path" on the launcher → app.py sets active_module="path"
  2. path_app.main() renders progress + "▶ Start next lesson" button
  3. Button calls _launch_unit() → sets session state + query params → rerun
  4. app.py routes to grammar / vocab / reading module for that lesson
     (curriculum_mode=True is preserved in session state)
  5. When the lesson finishes, _clear_all() / clear_all() in grammar/reading sees
     curriculum_mode → sets active_module="path" + curriculum_advance_pending=True
  6. On next render path_app.main() calls advance() and shows updated progress
"""
from __future__ import annotations

from urllib.parse import quote as _quote

import streamlit as st

from engine.curriculum import (
    advance,
    build_path,
    get_stats,
    reset_progress,
    LANG_TO_CODE,
)

# ── Stage metadata ───────────────────────────────────────────────────────────

_STAGE_META = {
    0: ("🔤", "Foundation",         "Sounds & script — alphabet and reading rules"),
    1: ("🌱", "Absolute Beginner",   "First words, greetings, basic sentences"),
    2: ("📗", "Beginner",            "Daily life, food, transport & routines"),
    3: ("📘", "Elementary",          "Travel, emotions, shopping & more"),
    4: ("📙", "Pre-Intermediate",    "Work, school, family & city life"),
    5: ("📕", "Intermediate",        "Technology, health, culture & sports"),
    6: ("🏆", "Upper-Intermediate",  "Deep vocabulary, complex grammar"),
}

_TYPE_ICON  = {"reading": "🔤", "grammar": "🗣️", "vocabulary": "📖"}
_TYPE_LABEL = {"reading": "Reading",    "grammar": "Grammar",    "vocabulary": "Vocabulary"}
_TYPE_COLOR = {
    "reading":    "var(--mova-mint)",
    "grammar":    "var(--mova-indigo)",
    "vocabulary": "#f59e0b",
}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _launch_unit(unit: dict, user: str, native: str, target: str) -> None:
    """
    Set up session state so that the next rerun lands inside the right module
    at the right lesson.  Uses the existing vnav_lesson query-param bridge
    that grammar.py and reading_app.py already support.
    """
    utype = unit["type"]

    # Keep launcher prefs + curriculum mode across the clear
    st.session_state["curriculum_mode"] = True

    if utype == "reading":
        lang_code = unit.get("lang_code", LANG_TO_CODE.get(target, "en"))
        st.session_state["r_lang"] = lang_code
        st.session_state["active_module"] = "reading"
        st.query_params.update({
            "module":       "reading",
            "vnav_lesson":  str(unit["lesson_id"]),
            "r_lang":       lang_code,
            "vnav_user":    _quote(user),
        })

    elif utype == "grammar":
        st.session_state["active_module"] = "grammar"
        st.query_params.update({
            "module":       "grammar",
            "vnav_lesson":  str(unit["lesson_id"]),
            "vnav_native":  _quote(native),
            "vnav_target":  _quote(target),
            "vnav_user":    _quote(user),
        })

    elif utype == "vocabulary":
        st.session_state["active_module"] = "vocab"
        st.query_params.update({
            "module":       "vocab",
            "vnav_lesson":  str(unit["lesson_id"]),
            "vnav_native":  _quote(native),
            "vnav_target":  _quote(target),
            "vnav_user":    _quote(user),
        })

    st.rerun()


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

    # Advance curriculum if returning from a completed lesson
    if st.session_state.pop("curriculum_advance_pending", False):
        advance(user, target)

    stats = get_stats(user, target)

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
            f'letter-spacing:.06em;margin-bottom:3px">Overall</div>'
            f'{_pct_bar(pct)}'
            f'<div style="font-size:.72rem;color:#aaa;margin-top:2px">'
            f'{stats["current_index"]} / {stats["total"]} · {pct:.0f}%</div>',
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

    # ── Overall progress bar ─────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Grammar",    f"{stats['done_grammar']} / {stats['total_grammar']}")
    with col2:
        st.metric("Vocabulary", f"{stats['done_vocab']}  / {stats['total_vocab']}")
    with col3:
        st.metric("Reading",    f"{stats['done_reading']} / {stats['total_reading']}")

    st.progress(stats["pct"] / 100)
    st.caption(f"{stats['current_index']} of {stats['total']} units complete · {stats['pct']:.0f}%")

    # ── Current stage card ───────────────────────────────────────────────────
    stage      = stats["current_stage"]
    s_icon, s_name, s_desc = _STAGE_META.get(stage, ("📚", f"Stage {stage}", ""))
    st.markdown(
        f'<div style="background:var(--mova-card);border:1px solid var(--mova-line);'
        f'border-left:4px solid var(--mova-indigo);border-radius:10px;'
        f'padding:14px 20px;margin:14px 0 8px">'
        f'<div style="font-size:.7rem;color:#aaa;text-transform:uppercase;'
        f'letter-spacing:.06em">Stage {stage}</div>'
        f'<div style="font-size:1.25rem;font-weight:700;margin:3px 0">'
        f'{s_icon} {s_name}</div>'
        f'<div style="color:var(--mova-ink-2);font-size:.9rem">{s_desc}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Completed / not started ───────────────────────────────────────────────
    unit = stats.get("current_unit")

    if unit is None:
        st.success(
            "🎉 **You've completed the entire learning path!**\n\n"
            "You've covered all reading, grammar, and vocabulary lessons."
        )
        if st.button("🔄 Start over", type="secondary"):
            reset_progress(user, target)
            st.rerun()
        return

    # ── Next lesson card ─────────────────────────────────────────────────────
    st.markdown("### ▶ Next lesson")

    utype  = unit["type"]
    u_icon = _TYPE_ICON.get(utype, "📚")
    u_lbl  = _TYPE_LABEL.get(utype, utype.title())
    u_col  = _TYPE_COLOR.get(utype, "var(--mova-indigo)")
    topic  = unit["topic_en"]
    lid    = unit["lesson_id"]
    sheet  = unit.get("sheet") or ""

    # Sub-label line
    if utype == "vocabulary" and sheet and sheet != topic:
        sub = f"Lesson {lid} · {sheet}"
    else:
        sub = f"Lesson {lid}"
    if unit.get("difficulty"):
        sub += f" · difficulty {unit['difficulty']}"

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

    # ── Upcoming lessons ─────────────────────────────────────────────────────
    upcoming = stats.get("upcoming", [])[1:]  # skip current (already shown above)
    if upcoming:
        st.markdown("### Coming up")
        for u in upcoming:
            _u_icon  = _TYPE_ICON.get(u["type"], "📚")
            _u_label = _TYPE_LABEL.get(u["type"], u["type"].title())
            _u_color = _TYPE_COLOR.get(u["type"], "var(--mova-indigo)")
            st.markdown(
                f'<div style="background:var(--mova-card);border:1px solid var(--mova-line);'
                f'border-radius:8px;padding:10px 16px;margin:4px 0;'
                f'display:flex;align-items:center;gap:12px">'
                f'<span style="font-size:1.2rem">{_u_icon}</span>'
                f'<div>'
                f'<div style="font-weight:600;font-size:.9rem">{u["topic_en"]}</div>'
                f'<div style="font-size:.75rem;color:#aaa">'
                f'{_u_label} · Lesson {u["lesson_id"]}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

    # ── Skip button ──────────────────────────────────────────────────────────
    st.markdown("")
    if st.button("⏭ Skip this lesson", type="secondary", key="path_skip"):
        advance(user, target)
        st.rerun()
