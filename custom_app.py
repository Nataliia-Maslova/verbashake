"""
custom_app.py — "My phrases" practice mode.

Lets the user create their own lessons (lesson name + native↔target pairs)
and then run them through the exact same 8-step flow as grammar / vocabulary.
Storage: data/custom_phrases.csv (mirrored to Google Sheets if configured).

Run via app.py launcher; direct entry: ``custom_app.main()``.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import json
import streamlit as st
import streamlit.components.v1 as components

ROOT        = Path(__file__).parent
APP_IMG_DIR = ROOT / "static" / "app_images"
sys.path.insert(0, str(ROOT))

from engine.custom_store import (
    add_lesson, delete_lesson, get_lesson_phrases,
    list_user_lessons, parse_pairs_text, rename_lesson,
)
from engine import i18n
from engine.loader  import LANG_COLUMNS, TTS_LANG, WHISPER_LANG
from engine.session import LessonSession

import grammar as grammar_app  # we reuse its 8-step machinery


# All 14 languages the rest of the app supports (2026-08-28 — was hardcoded
# to just English/Ukrainian/Spanish/Korean; My Phrases has no language-
# specific content of its own, unlike CEFR-J Vocabulary, so there was no
# real reason for the narrower list once its i18n moved to engine.i18n).
LANGUAGES = list(LANG_COLUMNS.keys())


# ─── i18n strings ─────────────────────────────────────────────────────────

def _t(key: str, **kwargs) -> str:
    """Return localized string for the current native language.

    Migrated off this file's own hand-rolled _I18N dict (2026-08-28, part of
    extending My Phrases from 4 languages to all 14) onto engine.i18n's
    shared STRINGS, prefixed "custom_" to avoid colliding with other
    modules' keys -- except "main_menu", which reuses the app-wide key
    verbatim (this file's own value was byte-identical to it in every
    language it had). en/uk/es/ko are hand-written there (copied straight
    from this file's old dict, not re-translated); the other 10 languages
    come from scripts/generate_i18n_strings.py, same as every other
    module's strings.
    """
    lang = st.session_state.get("launcher_native", "Ukrainian")
    ikey = key if key == "main_menu" else f"custom_{key}"
    tmpl = i18n.get(lang, ikey)
    return tmpl.format(**kwargs) if kwargs else tmpl


# ─── Styling reused from grammar module ───────────────────────────────────

def _inject_css():
    grammar_app._inject_css()


def _show_upsell_custom(key: str) -> None:
    """Same pattern as grammar.py::_show_upsell / reading_app.py::
    _show_upsell_reading — kept local since custom_app.py otherwise never
    touches engine.gemini."""
    st.warning("⭐ This is a Premium feature — live AI generation isn't included in the free plan.")
    if st.button("⭐ Go to Upgrade", key=f"upsell_{key}"):
        st.session_state["_show_launcher"] = True
        st.rerun()


# ─── Setup screen ─────────────────────────────────────────────────────────

def render_setup():
    _inject_css()

    # ── Query-params bridge: wave clicked a lesson ────────────────────────────
    _qp = st.query_params
    if "vnav_lesson" in _qp:
        try:
            from urllib.parse import unquote as _uq
            _qp_lid    = int(_qp["vnav_lesson"])
            _qp_native = _uq(_qp.get("vnav_native", "Ukrainian"))
            _qp_target = _uq(_qp.get("vnav_target", "English"))
            # Identity must come from the authenticated session, never from
            # the URL — vnav_user is only echoed there for the JS wave-nav
            # widget to round-trip navigation; trusting it directly would let
            # anyone edit the address bar to read/write another user's data.
            _qp_user   = st.session_state.get("launcher_user", "student1")
            if _qp_native not in LANGUAGES:
                _qp_native = "Ukrainian"
            if _qp_target not in LANGUAGES or _qp_target == _qp_native:
                _qp_target = next(l for l in LANGUAGES if l != _qp_native)
            st.query_params.clear()
            _qp_lp = f"{WHISPER_LANG.get(_qp_native,'?')}-{WHISPER_LANG.get(_qp_target,'?')}-custom"
            _start_lesson(_qp_user, _qp_lid, _qp_native, _qp_target, _qp_lp)
        except Exception:
            st.query_params.clear()


    st.markdown(f"""
    <div style="text-align:center;padding:32px 0 16px">
      <h1 style="color:var(--mova-ink);font-weight:700;margin:0;font-size:2rem">{_t("title")}</h1>
    </div>
    """, unsafe_allow_html=True)

    _my_phrases_banner = APP_IMG_DIR / "my_phrases_banner.jpg"
    if _my_phrases_banner.exists():
        _, _mid, _ = st.columns([1, 2, 1])
        with _mid:
            st.image(str(_my_phrases_banner), use_container_width=True)

    # ── Identity + language pair ──────────────────────────────────────────
    user_id        = st.session_state.get("launcher_user",   "student1")
    default_native = st.session_state.get("launcher_native", "Ukrainian")
    default_target = st.session_state.get("launcher_target", "English")

    cB, cC = st.columns([1.3, 1.3])
    with cB:
        if default_native not in LANGUAGES:
            default_native = "Ukrainian"
        native = st.selectbox(_t("native_label"), LANGUAGES,
                              index=LANGUAGES.index(default_native), key="cu_native")
    with cC:
        target_opts = [l for l in LANGUAGES if l != native]
        tdef = (target_opts.index(default_target)
                if default_target in target_opts else 0)
        target = st.selectbox(_t("target_label"), target_opts, index=tdef, key="cu_target")

    lang_pair = f"{WHISPER_LANG.get(native,'?')}-{WHISPER_LANG.get(target,'?')}-custom"

    # ── Existing lessons for this user + pair ─────────────────────────────
    lessons_df = list_user_lessons(user_id, native_lang=native, target_lang=target)

    st.markdown("---")
    st.markdown(f"### {_t('your_lessons', native=native, target=target)}")
    if lessons_df.empty:
        st.info(_t("no_lessons"))
    else:
        # ── Wave navigator ────────────────────────────────────────────────────
        _cu_lp = f"{WHISPER_LANG.get(native,'?')}-{WHISPER_LANG.get(target,'?')}-custom"
        _cu_lessons    = [int(row["lesson_id"])   for _, row in lessons_df.iterrows()]
        _cu_names_dict = {int(row["lesson_id"]): str(row["lesson_name"])
                          for _, row in lessons_df.iterrows()}
        _cu_counts_dict= {int(row["lesson_id"]): int(row["phrases"])
                          for _, row in lessons_df.iterrows()}

        from engine.picker import _render_wave_plotly

        _cu_clicked = _render_wave_plotly(
            lessons=_cu_lessons,
            lesson_names=_cu_names_dict,
            lesson_counts=_cu_counts_dict,
            default_lid=_cu_lessons[0] if _cu_lessons else None,
            resume_step=1,
            key_suffix=f"custom_{native}_{target}",
            show_lesson_image=False,
        )
        if _cu_clicked is not None:
            _start_lesson(user_id, _cu_clicked, native, target, _cu_lp)
        else:
            # Fallback: circular native Streamlit buttons
            st.markdown("""
<style>
[data-testid="stHorizontalBlock"] [data-testid="stButton"] button {
    border-radius: 50% !important;
    width: 76px !important; height: 76px !important;
    min-width: 76px !important; padding: 3px !important;
    font-size: 0.57rem !important; line-height: 1.22 !important;
    white-space: pre-wrap !important; overflow: hidden !important;
    text-align: center !important;
}
</style>""", unsafe_allow_html=True)
            _cu_emojis = ['📖','🌟','💡','🎯','🔤','🗣️','✏️','📝','🎓','💬','🔑','🏆']
            _cu_n = len(_cu_lessons)
            _cu_rows_per_row = 10
            for _cu_rs in range(0, _cu_n, _cu_rows_per_row):
                _cu_chunk_ids = _cu_lessons[_cu_rs:_cu_rs + _cu_rows_per_row]
                _cu_cols = st.columns(len(_cu_chunk_ids))
                for _cu_ci, (_cu_col, _cu_lid) in enumerate(zip(_cu_cols, _cu_chunk_ids)):
                    _cu_name  = _cu_names_dict.get(_cu_lid, f"Lesson {_cu_lid}")
                    _cu_cnt   = _cu_counts_dict.get(_cu_lid, 0)
                    _cu_gidx  = _cu_rs + _cu_ci
                    _cu_emoji = _cu_emojis[_cu_gidx % len(_cu_emojis)]
                    _cu_short = (_cu_name[:10] + "…") if len(_cu_name) > 10 else _cu_name
                    with _cu_col:
                        if st.button(
                            f"{_cu_emoji}\n{_cu_short}",
                            key=f"cu_wv_{_cu_lid}_{_cu_gidx}",
                            type="secondary",
                            use_container_width=False,
                            help=f"{_cu_name} · {_cu_cnt} phrases",
                        ):
                            _start_lesson(user_id, _cu_lid, native, target, _cu_lp)

        # ── Manage lessons (edit / delete) ──────────────────────────────────────
        with st.expander(_t("manage_lessons"), expanded=False):
            for _, row in lessons_df.iterrows():
                lid = int(row["lesson_id"])
                with st.container():
                    c1, c2, c3 = st.columns([5, 1.5, 1.5])
                    with c1:
                        st.markdown(
                            f"**{html.escape(str(row['lesson_name']))}** "
                            f"<span style='color:var(--mova-ink-3);font-size:.8rem'>"
                            f"{html.escape(_t('phrases_count', n=row['phrases']))}</span>",
                            unsafe_allow_html=True,
                        )
                    with c2:
                        if st.button(_t("rename_btn"), key=f"cu_edit_{lid}",
                                     use_container_width=True):
                            st.session_state[f"cu_edit_open_{lid}"] = True
                    with c3:
                        if st.button(_t("delete_btn"), key=f"cu_del_{lid}",
                                     use_container_width=True):
                            st.session_state[f"cu_del_confirm_{lid}"] = True

                if st.session_state.get(f"cu_edit_open_{lid}"):
                    new_name = st.text_input(
                        _t("new_name_label"),
                        value=row["lesson_name"],
                        key=f"cu_new_name_{lid}",
                    )
                    e1, e2 = st.columns(2)
                    with e1:
                        if st.button(_t("save_btn"), key=f"cu_save_name_{lid}",
                                     type="primary", use_container_width=True):
                            if rename_lesson(user_id, lid, new_name):
                                st.session_state.pop(f"cu_edit_open_{lid}", None)
                                st.rerun()
                    with e2:
                        if st.button(_t("cancel_btn"), key=f"cu_cancel_name_{lid}",
                                     use_container_width=True):
                            st.session_state.pop(f"cu_edit_open_{lid}", None)
                            st.rerun()

                if st.session_state.get(f"cu_del_confirm_{lid}"):
                    st.warning(_t("delete_confirm", name=row["lesson_name"]))
                    d1, d2 = st.columns(2)
                    with d1:
                        if st.button(_t("delete_yes"), type="primary",
                                     key=f"cu_del_yes_{lid}",
                                     use_container_width=True):
                            delete_lesson(user_id, lid)
                            st.session_state.pop(f"cu_del_confirm_{lid}", None)
                            st.rerun()
                    with d2:
                        if st.button(_t("cancel_btn"), key=f"cu_del_no_{lid}",
                                     use_container_width=True):
                            st.session_state.pop(f"cu_del_confirm_{lid}", None)
                            st.rerun()

    # ── Create new lesson ────────────────────────────────────────
    st.markdown("---")
    with st.expander(_t("create_expander"), expanded=lessons_df.empty):
        lesson_name = st.text_input(_t("lesson_name"),
                                     placeholder=_t("lesson_name_ph"),
                                     key="cu_new_lesson_name")

        # ── Generate from a word list + grammar topic (Natalia's idea,
        # 2026-08-28) — an alternative to typing pairs by hand: student
        # supplies a short word list ("nose, eye, lips, leg") and a grammar
        # construction ("I have got / we have / they have"), Gemini writes
        # one example sentence per word using that construction. Result is
        # written into the SAME cu_new_pairs textarea the manual-entry flow
        # already reads from below, so parsing/preview/save needs no
        # changes — this only ever pre-fills that one field.
        with st.expander(_t("generate_expander"), expanded=False):
            gen_words = st.text_input(
                _t("generate_words_label"),
                placeholder=_t("generate_words_ph"),
                key="cu_gen_words",
            )
            gen_topic = st.text_input(
                _t("generate_topic_label"),
                placeholder=_t("generate_topic_ph"),
                key="cu_gen_topic",
            )
            if st.button(_t("generate_btn"), key="cu_gen_btn"):
                word_list = [w.strip() for w in gen_words.split(",") if w.strip()]
                if not word_list or not gen_topic.strip():
                    st.warning(_t("generate_need_both"))
                elif len(word_list) > 20:
                    st.warning(_t("generate_too_many"))
                else:
                    try:
                        from engine import gemini as _gemini
                        with st.spinner("…"):
                            result = _gemini.generate_custom_word_drill(
                                word_list, gen_topic.strip(), native, target)
                        items = result.get("items") or []
                        if not items:
                            st.error(_t("generate_failed"))
                        else:
                            st.session_state["cu_new_pairs"] = "\n".join(
                                f"{it['native']} = {it['target']}" for it in items
                                if it.get("native") and it.get("target")
                            )
                            st.success(_t("generate_filled", n=len(items)))
                            st.rerun()
                    except _gemini.PaidFeatureRequired:
                        _show_upsell_custom("cu_gen")

        st.caption(_t("pairs_hint", native=native, target=target))
        text = st.text_area(
            _t("pairs_label", native=native, target=target),
            height=200,
            key="cu_new_pairs",
            placeholder=_t("pairs_ph", native=native, target=target),
        )

        pairs = parse_pairs_text(text, sep="=")
        if pairs:
            st.caption(_t("recognized", n=len(pairs)))
            preview_html = ""
            for i, (nat, tgt) in enumerate(pairs[:8], start=1):
                preview_html += (
                    f'<div style="display:flex;gap:14px;padding:6px 10px;'
                    f'background:var(--mova-card);border-bottom:1px solid var(--mova-line)">'
                    f'<span style="color:var(--mova-indigo-ink);min-width:28px;'
                    f'font-family:\'JetBrains Mono\',monospace;font-size:.72rem">{i:02d}</span>'
                    f'<span style="flex:1;color:var(--mova-ink)">{nat}</span>'
                    f'<span style="flex:1;color:#ffffff;font-weight:500">{tgt}</span>'
                    f'</div>'
                )
            if len(pairs) > 8:
                preview_html += (
                    f'<div style="padding:6px 10px;color:var(--mova-ink-3);font-size:.78rem">'
                    f'{_t("more_pairs", n=len(pairs)-8)}</div>'
                )
            st.markdown(
                f'<div style="border-radius:10px;overflow:hidden;'
                f'background:var(--mova-card);border:1px solid var(--mova-line)">{preview_html}</div>',
                unsafe_allow_html=True,
            )
        elif text.strip():
            st.warning(_t("no_pairs"))

        save_disabled = (not pairs) or (not user_id)
        if st.button(_t("save_lesson"), type="primary",
                     use_container_width=True,
                     disabled=save_disabled, key="cu_save_new"):
            try:
                lid = add_lesson(user_id, lesson_name, native, target, pairs)
                st.success(_t("saved_ok", lid=lid, n=len(pairs)))
                st.session_state.pop("cu_new_pairs", None)
                st.session_state.pop("cu_new_lesson_name", None)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"{e}")


# ─── Start a lesson — push state and let grammar.main() run the 8 steps ──

def _start_lesson(user_id: str, lesson_id: int,
                   native: str, target: str, lang_pair: str):
    lesson_df = get_lesson_phrases(user_id, lesson_id)
    if lesson_df.empty:
        st.error(_t("no_phrases_err"))
        return

    for k in list(st.session_state):
        if k.startswith(("s1_", "s2_", "s3_", "s4_", "s5_", "s6_", "s7_", "s8_",
                          "mic_", "up_")):
            del st.session_state[k]
    st.session_state.pop("_progress_saved", None)
    st.session_state.pop("_last_saved_progress", None)

    from engine.loader import TTS_LANG, WHISPER_LANG
    from engine.session import LessonSession
    st.session_state.update({
        "practice_module": "custom",
        "session":         LessonSession(user_id, lesson_df, lesson_id,
                                          native, target,
                                          language_pair=lang_pair,
                                          unit_id=f"custom:{lesson_id}"),
        "lesson_step":     1,
        "tts_lang":        TTS_LANG.get(target, "en"),
        "wh_lang":         WHISPER_LANG.get(target, "en"),
        "active_module":   "custom",
    })
    st.query_params["module"] = "custom"
    st.rerun()


def main():
    grammar_app.main(module="custom")


if __name__ == "__main__":
    main()
