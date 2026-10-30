"""
inbox_app.py — «Скарбничка» (word box), 2026-10-30.

Two parts:
  render_collector() / render_save_button()
      small widgets other screens embed (lesson Step 1, the end-of-phase
      error review, «Мої помилки», the Songs vocabulary tab): tap words of a
      sentence -> ➕ -> engine.word_inbox. Free for everyone — saving is a
      DB write, no AI.
  main()
      the screen itself (routing `active == "inbox"` in app.py, entry button
      on My Path and in My Phrases): the saved list, pick 5-15 -> «Зібрати
      блок» -> gemini.generate_custom_word_drill (one sentence per phrase)
      -> custom_store.add_lesson -> the picked rows are removed and the new
      My Phrases lesson starts right away (custom_app._start_lesson, the
      usual 8 steps). Building is Premium, like My Phrases itself.

Natalia's rules (engine/word_inbox.py): no source/context stored; "run a
company" and "run" are two separate items.

Top-level imports stay light on purpose: grammar.py and songs_app.py import
this module, and custom_app/path_app import grammar — those are imported
inside main() only, to avoid a cycle.
"""
from __future__ import annotations

import datetime as _dt
import re

import streamlit as st

from engine import i18n
from engine import word_inbox as _inbox

# Scripts written without spaces between words: tapping "words" there would
# offer whole clauses, so only the typed field is shown.
_NO_SPACE_LANGS = {"Japanese", "Chinese"}
_DEFAULT_PICK = 12
_TOKEN_RE = re.compile(r"[\w'’-]+", re.UNICODE)


def tokens(sentence: str) -> list[str]:
    return [t.strip("'’-") for t in _TOKEN_RE.findall(str(sentence or "")) if t.strip("'’-")]


def _flash(user: str, native: str, target: str, phrase: str, ok: bool) -> None:
    if ok:
        st.session_state["_inbox_flash"] = ("ok", i18n.get(native, "inbox_saved").format(phrase=phrase))
    else:
        st.session_state["_inbox_flash"] = ("warn", i18n.get(native, "inbox_full").format(n=_inbox.MAX_ITEMS)
                                             if _inbox.is_full(user, target)
                                             else i18n.get(native, "inbox_save_failed"))


def _show_flash() -> None:
    kind, msg = st.session_state.pop("_inbox_flash", (None, None))
    if kind == "ok":
        st.success(msg, icon="📥")
    elif kind:
        st.warning(msg)


def save(user: str, native: str, target: str, phrase: str, translation: str | None = None) -> bool:
    phrase = _inbox.clean_phrase(phrase)
    if not phrase:
        return False
    ok = _inbox.add(user, target, phrase, translation)
    _flash(user, native, target, phrase, ok)
    return ok


def _collector_save_cb(user: str, native: str, target: str, pills_key: str,
                       text_key: str, toks: list[str]) -> None:
    typed = (st.session_state.get(text_key) or "").strip()
    picked = sorted(st.session_state.get(pills_key) or [])
    phrase = typed or " ".join(toks[i] for i in picked if 0 <= i < len(toks))
    if save(user, native, target, phrase):
        st.session_state[pills_key] = []
        st.session_state[text_key] = ""


def render_collector(sentences: list[str], user: str, native: str, target: str,
                     key: str, expanded: bool = False) -> None:
    """Expander: choose a sentence, tap its words (any of them, in sentence
    order), or type a phrase -> save to the word box."""
    sentences = [s for s in dict.fromkeys(str(s or "").strip() for s in sentences) if s]
    if not user or not sentences:
        return
    with st.expander(i18n.get(native, "inbox_collect_title"), expanded=expanded):
        _show_flash()
        idx = 0
        if len(sentences) > 1:
            idx = st.selectbox(i18n.get(native, "inbox_collect_sentence"),
                               range(len(sentences)), format_func=lambda i: sentences[i],
                               key=f"{key}_sent")
        sent = sentences[idx]
        toks = [] if target in _NO_SPACE_LANGS else tokens(sent)
        pills_key = f"{key}_pills_{idx}"
        text_key = f"{key}_typed"
        if toks:
            st.pills(i18n.get(native, "inbox_collect_pick"), list(range(len(toks))),
                     format_func=lambda i: toks[i], selection_mode="multi", key=pills_key)
        else:
            st.caption(sent)
        st.text_input(i18n.get(native, "inbox_collect_type"), key=text_key,
                      max_chars=_inbox.MAX_PHRASE_CHARS)
        typed = (st.session_state.get(text_key) or "").strip()
        picked = sorted(st.session_state.get(pills_key) or [])
        phrase = _inbox.clean_phrase(typed or " ".join(toks[i] for i in picked if 0 <= i < len(toks)))
        st.button(i18n.get(native, "inbox_collect_save").format(phrase=phrase) if phrase
                  else i18n.get(native, "inbox_collect_save_empty"),
                  key=f"{key}_save", disabled=not phrase,
                  on_click=_collector_save_cb,
                  args=(user, native, target, pills_key, text_key, toks))


def render_save_button(phrase: str, translation: str | None, user: str, native: str,
                       target: str, key: str) -> None:
    """One ➕ for an item that already is a word/phrase (Songs vocabulary)."""
    if not user:
        return
    st.button("➕", key=key, help=i18n.get(native, "inbox_save_help"),
              on_click=save, args=(user, native, target, phrase, translation))


# ─── The screen ──────────────────────────────────────────────────────────────

def _sel_key(item: dict) -> str:
    return f"inbox_sel_{item['phrase_key']}"


def _build_block(user: str, native: str, target: str, picked: list[dict]) -> None:
    from engine import billing, gemini as _gemini, recommender as _recommender
    from engine.custom_store import add_lesson
    from engine.loader import WHISPER_LANG
    import custom_app

    if not billing.is_paid(user):
        st.info(i18n.get(native, "inbox_premium_note"))
        custom_app._show_upsell_custom("inbox")
        return
    words = [it["phrase"] for it in picked]
    try:
        with st.spinner("…"):
            result = _gemini.generate_custom_word_drill(
                words, None, native, target, level=_recommender.current_level(user, target))
    except _gemini.PaidFeatureRequired:
        custom_app._show_upsell_custom("inbox")
        return
    except Exception as e:
        print(f"[inbox_app] generate_custom_word_drill failed: {e}")
        result = {}
    pairs = [(it["native"], it["target"]) for it in (result.get("items") or [])
             if it.get("native") and it.get("target")]
    if not pairs:
        st.error(i18n.get(native, "inbox_build_failed"))
        return
    name = i18n.get(native, "inbox_block_name").format(date=_dt.date.today().strftime("%d.%m"))
    try:
        lid = add_lesson(user, name, native, target, pairs)
    except Exception as e:
        print(f"[inbox_app] add_lesson failed: {e}")
        st.error(i18n.get(native, "inbox_build_failed"))
        return
    _inbox.remove(user, target, [it["phrase_key"] for it in picked])
    lang_pair = f"{WHISPER_LANG.get(native, '?')}-{WHISPER_LANG.get(target, '?')}-custom"
    custom_app._start_lesson(user, lid, native, target, lang_pair)


def main() -> None:
    from engine.gamification import sidebar_widget as _gami_sidebar
    from path_app import _switch_module

    user   = st.session_state.get("launcher_user",   "student1")
    native = st.session_state.get("launcher_native", "Ukrainian")
    target = st.session_state.get("launcher_target", "English")

    with st.sidebar:
        _gami_sidebar(user)
        for _mk, _label in (("path", f"🗺️ {i18n.get(native, 'module_path')}"),
                            ("custom", f"📝 {i18n.get(native, 'module_custom')}")):
            if st.button(_label, key=f"inbox_sb_{_mk}", use_container_width=True):
                _switch_module(_mk, user, native, target)

    st.title(i18n.get(native, "inbox_title"))
    st.caption(f"{native} → {target}")
    _show_flash()

    with st.form("inbox_add_form", clear_on_submit=True, border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        typed = c1.text_input(i18n.get(native, "inbox_add_label"),
                              max_chars=_inbox.MAX_PHRASE_CHARS)
        if c2.form_submit_button(i18n.get(native, "inbox_add_btn"), use_container_width=True):
            if save(user, native, target, typed):
                st.rerun()

    items = _inbox.list_items(user, target)
    if not items:
        st.info(i18n.get(native, "inbox_empty"))
        return
    st.caption(i18n.get(native, "inbox_intro").format(min=_inbox.BLOCK_MIN, max=_inbox.BLOCK_MAX))

    for i, it in enumerate(items):
        label = f"**{it['phrase']}**" + (f" — {it['translation']}" if it.get("translation") else "")
        st.checkbox(label, value=i < _DEFAULT_PICK, key=_sel_key(it))

    picked = [it for it in items if st.session_state.get(_sel_key(it))]
    n = len(picked)
    in_range = _inbox.BLOCK_MIN <= n <= _inbox.BLOCK_MAX
    st.markdown(i18n.get(native, "inbox_picked").format(
        n=n, min=_inbox.BLOCK_MIN, max=_inbox.BLOCK_MAX))
    b1, b2 = st.columns(2)
    build = b1.button(i18n.get(native, "inbox_build_btn"), type="primary",
                      use_container_width=True, disabled=not in_range, key="inbox_build")
    if b2.button(i18n.get(native, "inbox_delete_btn"), use_container_width=True,
                 disabled=n == 0, key="inbox_delete"):
        _inbox.remove(user, target, [it["phrase_key"] for it in picked])
        for it in picked:
            st.session_state.pop(_sel_key(it), None)
        st.rerun()
    if build:
        _build_block(user, native, target, picked)


if __name__ == "__main__":
    main()
