"""
songs_app.py — "Songs" module (2026-10-04, Наталья): study a song.

The student types the song's name and pastes the lyrics THEMSELVES — the app
only links to the official video and a lyrics search, and never stores the
lyrics (copyright; her decision). One Gemini call (engine.gemini.analyze_song)
returns a line-by-line translation into the student's own language,
vocabulary and grammar for their level, and "song language" (gonna, ain't...)
with the standard form. Every grammar structure is mapped to one of OUR
lessons, with three actions:
  📖 open the lesson            -> path_app._launch_unit(return_module="songs")
  ➕ add it to My Path          -> engine.path_pins (shown first on My Path)
  🏋️ practise it now            -> the same lesson opened straight on Practice

Premium only (her decision). Works for every target language: the lesson
catalog comes from grammar._load_grammar for the current pair; for English,
word levels are re-checked against CEFR-J instead of trusting the model.

State lives only in st.session_state["songs_work"] (kept across a lesson
opened from here by grammar._clear_all) — nothing is written to the DB
except the optional My Path pin.
"""
from __future__ import annotations

from urllib.parse import quote_plus

import streamlit as st

import grammar as _grammar
from engine import billing, i18n
from engine import gemini as _gemini
from engine import path_pins as _path_pins
from engine import rate_limit
from engine import recommender as _recommender
from engine import user_prefs as _user_prefs
from engine.gamification import sidebar_widget as _gami_sidebar
from path_app import _launch_unit

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
DAILY_LIMIT = 20          # analyses per day, Premium too (rate_limit.py's rationale)
MAX_LINE_CHARS = 200


def _clear_and_home() -> None:
    """Same wipe-and-return-to-launcher pattern as search_app.py's copy."""
    _keep = {k: st.session_state[k] for k in
             ("launcher_user", "launcher_native", "launcher_target", "_dark_mode")
             if k in st.session_state}
    for k in list(st.session_state):
        del st.session_state[k]
    st.session_state.update(_keep)
    st.query_params.clear()


def _render_sidebar(user: str, native: str, target: str) -> None:
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
            _is_current = (_mk == "songs")
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
        if st.button(i18n.get(native, "main_menu"), use_container_width=True, key="songs_home"):
            _clear_and_home()
            st.rerun()


# ── Data helpers ──────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _lesson_catalog(native: str, target: str) -> list[dict]:
    """One row per grammar lesson available for this pair:
    {id, topic (English, for the model), title (student's language),
    level, example (a target-language sentence)}. English verb-form
    reference lists are left out — a song line should map to the lesson
    that teaches the tense, not to a list of irregular verbs."""
    from engine.verb_form_topics import ENGLISH_PIVOT_VERB_LESSONS
    df = _grammar._load_grammar(_grammar.DB_PATH, native, target)
    df = df[~df["lesson_id"].isin(ENGLISH_PIVOT_VERB_LESSONS)]
    native_col = f"topic_{i18n.LANG_TO_CODE.get(native, 'en')}"
    out = []
    for lid, grp in df.groupby("lesson_id", sort=False):
        row = grp.iloc[0]
        try:
            level = _recommender.DIFFICULTY_TO_CEFR.get(int(row["difficulty"]), "")
        except (TypeError, ValueError):
            level = ""
        title = row.get(native_col) if native_col in df.columns else None
        if not isinstance(title, str) or not title.strip():   # NaN for language-path lessons
            title = row["topic_en"]
        out.append({
            "id": int(lid),
            "topic": str(row["topic_en"]),
            "title": str(title),
            "level": level,
            "example": str(row["target"])[:120],
        })
    return out


@st.cache_data(show_spinner=False)
def _cefrj_levels() -> dict[str, str]:
    """English headword -> its lowest CEFR-J level."""
    from engine.cefr_wordlist import CEFR_RANK, _load
    df = _load()
    out: dict[str, str] = {}
    for hw, lvl in zip(df["headword"], df["level"]):
        key = str(hw).strip().lower()
        if key not in out or CEFR_RANK[lvl] < CEFR_RANK[out[key]]:
            out[key] = lvl
    return out


def split_lyrics(text: str) -> list[str]:
    """Non-empty lines, section labels like [Chorus] dropped, each capped."""
    lines = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or (line.startswith("[") and line.endswith("]")):
            continue
        lines.append(line[:MAX_LINE_CHARS])
    return lines


def split_vocab_by_level(vocab: list[dict], level: str, target: str) -> tuple[list[dict], list[dict]]:
    """(for this student: their level and one above, everything else).
    English levels come from CEFR-J when the word is in it."""
    rank = {l: i for i, l in enumerate(LEVELS)}
    me = rank.get(level, 0)
    cefrj = _cefrj_levels() if target == "English" else {}
    mine, other = [], []
    for v in vocab:
        lvl = cefrj.get(v["word"].lower(), v.get("level") or "")
        v = {**v, "level": lvl}
        r = rank.get(lvl)
        (mine if r is None or me <= r <= me + 1 else other).append(v)
    return mine, other


def split_grammar_by_level(items: list[dict], level: str, by_id: dict) -> tuple[list[dict], list[dict]]:
    """(up to one level above the student, harder). A structure mapped to one
    of our lessons takes that lesson's level, not the model's guess."""
    rank = {l: i for i, l in enumerate(LEVELS)}
    me = rank.get(level, 0)
    mine, harder = [], []
    for g in items:
        lesson = by_id.get(g.get("lesson_id"))
        lvl = (lesson or {}).get("level") or g.get("level") or ""
        g = {**g, "level": lvl}
        r = rank.get(lvl)
        (harder if r is not None and r > me + 1 else mine).append(g)
    return mine, harder


def default_level(user: str, target: str) -> str:
    """The higher of the grammar frontier's level and the self-reported
    onboarding level (only if that was for this language): one skipped early
    lesson keeps the frontier at A1 for an otherwise advanced student."""
    found = []
    try:
        found.append(_recommender.current_level(user, target))
    except Exception:
        pass
    prof = _user_prefs.get_profile(user) or {}
    if prof.get("target_lang") == target:
        found.append(prof.get("self_level"))
    found = [l for l in found if l in LEVELS]
    return max(found, key=LEVELS.index) if found else "A1"


# ── Screens ───────────────────────────────────────────────────────────────

def _render_input(user: str, native: str, target: str) -> None:
    st.caption(i18n.get(native, "songs_intro"))
    title = st.text_input(i18n.get(native, "songs_title_label"), key="songs_title",
                          placeholder=i18n.get(native, "songs_title_placeholder")).strip()
    if title:
        c1, c2 = st.columns(2)
        with c1:
            st.link_button(i18n.get(native, "songs_watch_btn"),
                           "https://www.youtube.com/results?search_query=" + quote_plus(title),
                           use_container_width=True)
        with c2:
            st.link_button(i18n.get(native, "songs_find_lyrics_btn"),
                           "https://genius.com/search?q=" + quote_plus(title),
                           use_container_width=True)

    lyrics = st.text_area(i18n.get(native, "songs_lyrics_label"), key="songs_lyrics", height=220)
    st.caption(i18n.get(native, "songs_lyrics_help"))
    lvl_default = default_level(user, target)
    level = st.selectbox(i18n.get(native, "songs_level_label"), LEVELS,
                         index=LEVELS.index(lvl_default), key="songs_level")

    lines = split_lyrics(lyrics)
    if len(lines) > _gemini.SONG_MAX_LINES:
        st.info(i18n.get(native, "songs_too_long").format(n=_gemini.SONG_MAX_LINES))
    if not st.button(i18n.get(native, "songs_analyze_btn"), type="primary",
                     disabled=not (title and lines), key="songs_analyze"):
        return

    try:
        rate_limit.check_and_increment(user, "analyze_song", DAILY_LIMIT)
    except rate_limit.DailyLimitExceeded:
        st.warning(i18n.get(native, "songs_limit_reached"))
        return
    lines = lines[:_gemini.SONG_MAX_LINES]
    catalog = _lesson_catalog(native, target)
    with st.spinner(i18n.get(native, "songs_analyzing")):
        try:
            result = _gemini.analyze_song(
                title, lines, level, target, native,
                [{k: l[k] for k in ("id", "level", "topic", "example")} for l in catalog],
            )
        except _gemini.PaidFeatureRequired:
            _render_premium_gate(native)
            return
        except Exception as e:
            print(f"[songs_app] analyze_song failed: {e}")
            st.error(i18n.get(native, "songs_error"))
            return
    st.session_state["songs_work"] = {"title": title, "lines": lines, "level": level,
                                      "result": result}
    st.rerun()


def _render_premium_gate(native: str) -> None:
    st.info(i18n.get(native, "songs_premium_only"))
    if st.button(i18n.get(native, "sidebar_upgrade_btn"), type="primary", key="songs_upgrade"):
        st.session_state["_show_launcher"] = True
        st.rerun()


def _line_ref(native: str, n: int | None) -> str:
    return f" · {i18n.get(native, 'songs_line').format(n=n)}" if n else ""


def _render_text_tab(native: str, work: dict) -> None:
    res = work["result"]
    show = st.toggle(i18n.get(native, "songs_show_translation"),
                     value=work["level"] in ("A1", "A2", "B1"), key="songs_show_tr")
    for n, line in enumerate(work["lines"], 1):
        tr = res["translations"].get(n, "")
        st.markdown(
            f"<div style='margin:2px 0'><span style='color:var(--mova-ink-3);font-size:.75rem'>{n}</span> "
            f"<b>{_esc(line)}</b>"
            + (f"<br><span style='color:var(--mova-ink-2)'>{_esc(tr)}</span>" if show and tr else "")
            + "</div>",
            unsafe_allow_html=True,
        )


def _esc(s: str) -> str:
    import html
    return html.escape(str(s or ""))


def _render_vocab_tab(native: str, target: str, work: dict) -> None:
    mine, other = split_vocab_by_level(work["result"]["vocab"], work["level"], target)

    def _rows(items: list[dict]) -> None:
        for v in items:
            note = f"  \n<span style='color:var(--mova-ink-3)'>{_esc(v['note'])}</span>" if v.get("note") else ""
            lvl = f" `{v['level']}`" if v.get("level") else ""
            st.markdown(f"**{_esc(v['word'])}**{lvl} — {_esc(v['native'])}"
                        f"<span style='color:var(--mova-ink-3)'>{_line_ref(native, v.get('line'))}</span>{note}",
                        unsafe_allow_html=True)

    if mine:
        _rows(mine)
    else:
        st.info(i18n.get(native, "songs_no_words"))
    if other:
        with st.expander(i18n.get(native, "songs_more_words").format(n=len(other))):
            _rows(other)


def _render_grammar_tab(user: str, native: str, target: str, work: dict) -> None:
    items = work["result"]["grammar"]
    if not items:
        st.info(i18n.get(native, "songs_no_grammar"))
        return
    by_id = {l["id"]: l for l in _lesson_catalog(native, target)}
    mine, harder = split_grammar_by_level(items, work["level"], by_id)
    for i, g in enumerate(mine):
        _render_grammar_item(i, g, by_id, user, native, target, work)
    if harder:
        with st.expander(i18n.get(native, "songs_more_grammar").format(n=len(harder))):
            for j, g in enumerate(harder, len(mine)):
                _render_grammar_item(j, g, by_id, user, native, target, work)


def _render_grammar_item(i: int, g: dict, by_id: dict, user: str, native: str,
                         target: str, work: dict) -> None:
    with st.container(border=True):
        lvl = f" `{g['level']}`" if g.get("level") else ""
        st.markdown(f"**{_esc(g['structure'])}**{lvl}", unsafe_allow_html=True)
        if g.get("fragment"):
            st.markdown(f"<i>«{_esc(g['fragment'])}»</i>"
                        f"<span style='color:var(--mova-ink-3)'>{_line_ref(native, g.get('line'))}</span>",
                        unsafe_allow_html=True)
        if g.get("explanation"):
            st.write(g["explanation"])
        lesson = by_id.get(g.get("lesson_id"))
        if not lesson:
            st.caption(i18n.get(native, "songs_no_lesson"))
            return
        unit = {"unit_id": f"grammar:{lesson['id']}"}
        pos = _recommender.lesson_position(target, "grammar", lesson["id"]) or lesson["id"]
        st.caption(i18n.get(native, "songs_lesson_label").format(
            n=pos, title=lesson["title"], level=lesson["level"]))
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button(i18n.get(native, "songs_open_lesson_btn"), key=f"song_open_{i}",
                         use_container_width=True):
                _launch_unit(unit, user, native, target, return_module="songs")
        with c2:
            if st.button(i18n.get(native, "songs_add_path_btn"), key=f"song_pin_{i}",
                         use_container_width=True):
                if _path_pins.add(user, target, unit["unit_id"], source=work["title"][:120]):
                    st.toast(i18n.get(native, "songs_added_path"))
                else:
                    st.error(i18n.get(native, "songs_error"))
        with c3:
            if st.button(i18n.get(native, "songs_practice_btn"), key=f"song_practice_{i}",
                         type="primary", use_container_width=True):
                _launch_unit(unit, user, native, target, return_module="songs",
                             phase="practice")


def _render_song_language_tab(native: str, work: dict) -> None:
    items = work["result"]["song_language"]
    if not items:
        st.info(i18n.get(native, "songs_no_song_language"))
        return
    for s in items:
        st.markdown(
            f"~~{_esc(s['fragment'])}~~ → **{_esc(s['standard'])}**"
            f"<span style='color:var(--mova-ink-3)'>{_line_ref(native, s.get('line'))}</span>",
            unsafe_allow_html=True,
        )
        if s.get("explanation"):
            st.caption(s["explanation"])


def _render_analysis(user: str, native: str, target: str, work: dict) -> None:
    res = work["result"]
    st.markdown(f"### 🎵 {_esc(work['title'])}")
    st.caption(f"{native} → {target} · {work['level']}")
    if not res.get("language_ok", True):
        st.warning(i18n.get(native, "songs_wrong_language").format(
            song_lang=res.get("detected_language", "?"), target=target))
    t_text, t_vocab, t_gram, t_song = st.tabs([
        i18n.get(native, "songs_tab_text"), i18n.get(native, "songs_tab_vocab"),
        i18n.get(native, "songs_tab_grammar"), i18n.get(native, "songs_tab_song_language"),
    ])
    with t_text:
        _render_text_tab(native, work)
    with t_vocab:
        _render_vocab_tab(native, target, work)
    with t_gram:
        _render_grammar_tab(user, native, target, work)
    with t_song:
        _render_song_language_tab(native, work)
    st.markdown("")
    if st.button(i18n.get(native, "songs_new_song_btn"), key="songs_new"):
        for k in ("songs_work", "songs_title", "songs_lyrics"):
            st.session_state.pop(k, None)
        st.rerun()


def main() -> None:
    user   = st.session_state.get("launcher_user",   "student1")
    native = st.session_state.get("launcher_native", "Ukrainian")
    target = st.session_state.get("launcher_target", "English")
    st.session_state.pop("curriculum_advance_pending", None)

    _render_sidebar(user, native, target)
    st.title(f"🎵 {i18n.get(native, 'module_songs')}")

    if not billing.is_paid(user):
        st.caption(i18n.get(native, "songs_intro"))
        _render_premium_gate(native)
        return

    work = st.session_state.get("songs_work")
    if work:
        _render_analysis(user, native, target, work)
    else:
        _render_input(user, native, target)


if __name__ == "__main__":
    main()
