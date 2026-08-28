"""
search_app.py — cross-module search: type a word, find every lesson across
Grammar, Vocabulary, Phrasebook, and Reading that contains it for the
current language pair, then jump straight in.

In-memory (Option 1, agreed with Natalia 2026-08-28, over a Postgres
full-text index): reuses the exact same @st.cache_data-cached loaders every
other module already calls (grammar.py's _load_grammar/_load_vocabulary/
_load_phrasebook, reading_app.load) instead of building a new DB-backed
index — zero schema changes, zero reseeding, and results stay in sync
automatically whenever the source workbooks change. At current content
volume (thousands of rows per language pair, not millions, and cached after
the first load) a plain in-memory substring search is fast enough; if that
ever stops being true, indexing content_units in Postgres (it already
carries module/level/topic for every unit — just needs the phrase text
added) is the natural next step.

Vocabulary is a known partial case: engine.cefr_j_vocab_loader only fills
`native`/`target` when that language IS English — every other pair's
translation is lazy (loaded on demand when a lesson is opened, cached in
Postgres). So Vocabulary search matches against `headword`/`source_en`
(always populated, English) rather than the target-language text, and
results are shown in English with a note — same constraint the rest of the
app already lives with for this module, not something new to search.

Jump-to-lesson reuses path_app.py's exact vnav_lesson bridge (_launch_unit)
— the same mechanism My Path already uses to land a click inside any of
grammar/vocab/phrasebook/reading at a specific lesson.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from rapidfuzz import fuzz

import grammar as _grammar
import reading_app as _reading
from engine import i18n
from engine.gamification import sidebar_widget as _gami_sidebar
from engine.grammar_search_synonyms import GRAMMAR_TERMS, NO_DEDICATED_LESSON
from engine.recommender import LANG_TO_CODE, unit_id_for
from path_app import _launch_unit

_SYNONYMS_PATH = Path(__file__).parent / "data" / "grammar_search_synonyms_translated.json"
_synonym_cache: dict | None = None


def _load_synonym_translations() -> dict:
    """{lang_code: {term_key: translated_phrase}} from
    scripts/generate_grammar_search_synonym_translations.py's output.
    Loaded once per process; a language/term missing here just falls back
    to the English alias in _match_grammar_term (safe — the file is filled
    in incrementally, language by language, and may be partial)."""
    global _synonym_cache
    if _synonym_cache is None:
        _synonym_cache = (
            json.loads(_SYNONYMS_PATH.read_text(encoding="utf-8"))
            if _SYNONYMS_PATH.exists() else {}
        )
    return _synonym_cache


def _match_grammar_term(native: str, query: str) -> tuple[str, bool] | None:
    """Best-matching curated grammar-term alias (engine.grammar_search_synonyms)
    for `query` in the user's native language, falling back to the English
    alias for any term not yet translated. Returns (term_key, has_dedicated_
    lessons) or None if nothing clears the fuzzy bar."""
    translated = _load_synonym_translations().get(LANG_TO_CODE.get(native, "en"), {})
    best_key, best_score, best_dedicated = None, 0, True
    for key, entry in GRAMMAR_TERMS.items():
        score = _match_score(query, entry["en"][0], translated.get(key))
        if score > best_score:
            best_key, best_score, best_dedicated = key, score, True
    for key, aliases in NO_DEDICATED_LESSON.items():
        score = _match_score(query, aliases[0], translated.get(key))
        if score > best_score:
            best_key, best_score, best_dedicated = key, score, False
    return (best_key, best_dedicated) if best_key else None

MAX_RESULTS_PER_MODULE = 15

# Fuzzy matching (rapidfuzz — already a dependency, used elsewhere for STT
# scoring) instead of plain substring search: Grammar/Phrasebook topic names
# and example sentences are translated per-language, and morphologically
# rich languages (Ukrainian, Russian, Polish...) inflect the very words a
# learner would search for — "прошедшее" (a query) vs "Прошедшие действия"
# (a real lesson topic) differ only in a grammatical-case ending, so an exact
# `.str.contains()` misses it even though it's obviously the right lesson.
# rapidfuzz.fuzz.partial_ratio tolerates that. Short queries (<5 chars) are
# still held to an exact-substring match (partial_ratio naturally returns
# 100 for those) — letting fuzzy slop apply to a 2-3 letter query would match
# almost any row and swamp results with noise.
FUZZY_THRESHOLD  = 80
EXACT_ONLY_BELOW = 5


def _match_score(query: str, *fields) -> int:
    """Best fuzzy score (0-100) of `query` against any of `fields`, or 0 if
    none clears the bar for this query's length."""
    q = query.lower()
    best = 0
    for f in fields:
        if not f:
            continue
        score = fuzz.partial_ratio(q, str(f).lower())
        if score > best:
            best = score
    if len(query) < EXACT_ONLY_BELOW:
        return best if best >= 100 else 0
    return best if best >= FUZZY_THRESHOLD else 0

_MODULE_META = {
    "grammar":    ("🗣️", "Grammar"),
    "vocab":      ("📖", "Vocabulary"),
    "phrasebook": ("💬", "Phrasebook"),
    "reading":    ("🔤", "Reading"),
}


def _clear_and_home() -> None:
    """Same wipe-and-return-to-launcher pattern as reading_app.clear_all() /
    grammar.py's _clear_all() — duplicated locally per this codebase's own
    convention (each module file keeps its own copy rather than importing
    one another, since app.py already imports every module for its router)."""
    _keep = {k: st.session_state[k] for k in
             ("launcher_user", "launcher_native", "launcher_target")
             if k in st.session_state}
    for k in list(st.session_state):
        del st.session_state[k]
    st.session_state.update(_keep)
    st.query_params.clear()


def _topic_columns(native: str, df) -> list[str]:
    """Topic columns worth matching against: the user's own native-language
    title (what they'd naturally search in) plus topic_en as a universal
    fallback (the "language path" synthetic lessons — Ukrainian aspect,
    Spanish subjunctive... — only ever get a title in the target language
    + an English gloss stuffed into topic_en, never a native-language
    translation, see engine/target_grammar_loader.py)."""
    cols = [f"topic_{LANG_TO_CODE.get(native, 'en')}", "topic_en"]
    return [c for c in dict.fromkeys(cols) if c in df.columns]


def _search_grammar(native: str, target: str, query: str) -> tuple[list[dict], str | None]:
    df = _grammar._load_grammar(_grammar.DB_PATH, native, target)
    topic_cols = _topic_columns(native, df)

    # Curated grammar-terminology match takes priority over the generic
    # fuzzy scan: a query like "present continuous" is a formal grammar
    # term, not text that would ever literally appear inside an example
    # sentence ("I am eating") or even most topic names — see
    # engine/grammar_search_synonyms.py for why this needs its own registry
    # rather than relying on fuzzy topic matching alone.
    term_match = _match_grammar_term(native, query)
    if term_match:
        term_key, has_dedicated = term_match
        if not has_dedicated:
            return [], i18n.get(native, "search_no_dedicated_lesson")
        out = []
        for lid in GRAMMAR_TERMS[term_key]["lesson_ids"][:MAX_RESULTS_PER_MODULE]:
            sub = df[df["lesson_id"] == lid]
            if sub.empty:
                continue
            row = sub.iloc[0]
            topic_native = next((row[c] for c in topic_cols if row[c]), row["target"])
            out.append({
                "unit_id":   unit_id_for("grammar", lid),
                "primary":   topic_native,
                "secondary": row["target"],
            })
        return out, None

    scores = df.apply(
        lambda r: _match_score(query, r["native"], r["target"],
                                *(r[c] for c in topic_cols)),
        axis=1,
    )
    hits = df[scores > 0].assign(_score=scores[scores > 0]) \
             .sort_values("_score", ascending=False)
    out = []
    for _, row in hits.head(MAX_RESULTS_PER_MODULE).iterrows():
        out.append({
            "unit_id":   unit_id_for("grammar", int(row["lesson_id"])),
            "primary":   row["target"],
            "secondary": row["native"],
        })
    return out, None


def _search_vocab(native: str, target: str, query: str) -> tuple[list[dict], str | None]:
    df = _grammar._load_vocabulary(_grammar.DB_PATH, native, target)
    # native/target are only filled in when that language is English (see
    # module docstring) — headword/source_en are the only columns every row
    # actually has, so search those instead of silently missing every
    # non-English pair. Shown in English regardless of target_lang (main()
    # adds a one-line note for that case) — the real translation is lazy,
    # loaded only once the lesson itself is opened.
    scores = df.apply(lambda r: _match_score(query, r["headword"], r["source_en"]), axis=1)
    hits = df[scores > 0].assign(_score=scores[scores > 0]) \
             .sort_values("_score", ascending=False)
    out = []
    for _, row in hits.head(MAX_RESULTS_PER_MODULE).iterrows():
        out.append({
            "unit_id":   unit_id_for("vocab", int(row["lesson_id"]), row["topic"]),
            "primary":   row["headword"],
            "secondary": row["source_en"],
        })
    return out, None


def _search_phrasebook(native: str, target: str, query: str) -> tuple[list[dict], str | None]:
    df = _grammar._load_phrasebook(_grammar.VOCAB_DB_PATH, native, target)
    # `topic` here is the real sheet name (e.g. "Greetings, Basics &
    # Courtesy") — a genuine, searchable theme, unlike Vocabulary's CEFR
    # level, so it's included directly (no per-language variant exists).
    scores = df.apply(lambda r: _match_score(query, r["native"], r["target"], r["topic"]), axis=1)
    hits = df[scores > 0].assign(_score=scores[scores > 0]) \
             .sort_values("_score", ascending=False)
    out = []
    for _, row in hits.head(MAX_RESULTS_PER_MODULE).iterrows():
        out.append({
            "unit_id":   unit_id_for("phrasebook", int(row["lesson_id"]), row["topic"]),
            "primary":   row["target"],
            "secondary": row["native"],
        })
    return out, None


def _search_reading(native: str, target: str, query: str) -> tuple[list[dict], str | None]:
    lang_code = LANG_TO_CODE.get(target)
    if not lang_code or lang_code not in _reading.TTS_CONFIG:
        return [], None
    df = _reading.load(str(_reading.DB_PATH), lang=lang_code, native_lang=native)
    # `rule` (e.g. "H is always silent") is included so a query like "silent"
    # surfaces the right phonics lesson, not just literal target-word matches.
    scores = df.apply(lambda r: _match_score(query, r["word"], r["rule"]), axis=1)
    hits = df[scores > 0].assign(_score=scores[scores > 0]) \
             .sort_values("_score", ascending=False)
    out = []
    for _, row in hits.head(MAX_RESULTS_PER_MODULE).iterrows():
        out.append({
            "unit_id":   f"reading:{lang_code}:{int(row['lesson_id'])}",
            "primary":   row["word"],
            "secondary": row["transcription"],
        })
    return out, None


_SEARCHERS = {
    "grammar":    _search_grammar,
    "vocab":      _search_vocab,
    "phrasebook": _search_phrasebook,
    "reading":    _search_reading,
}


def main() -> None:
    user   = st.session_state.get("launcher_user",   "student1")
    native = st.session_state.get("launcher_native", "Ukrainian")
    target = st.session_state.get("launcher_target", "English")

    with st.sidebar:
        _gami_sidebar(user)

        _SIDEBAR_MODULES = [
            ("grammar",    "🗣️", "Grammar"),
            ("vocab",      "📖", "Vocabulary"),
            ("phrasebook", "💬", "Phrasebook"),
            ("reading",    "🔤", "Reading"),
            ("custom",     "📝", "My Phrases"),
            ("search",     "🔍", "Search"),
        ]
        st.markdown(
            '<div style="font-size:.7rem;color:var(--mova-ink-3);'
            'text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">'
            'Module</div>',
            unsafe_allow_html=True,
        )
        for _mk, _mi, _mn in _SIDEBAR_MODULES:
            _is_current = (_mk == "search")
            if st.button(f"{_mi} {_mn}", key=f"sb_mod_{_mk}",
                         use_container_width=True,
                         type="primary" if _is_current else "secondary",
                         disabled=_is_current):
                for _k in list(st.session_state):
                    del st.session_state[_k]
                st.session_state["active_module"]   = _mk
                st.session_state["launcher_user"]   = user
                st.session_state["launcher_native"] = native
                st.session_state["launcher_target"] = target
                st.query_params["module"] = _mk
                st.rerun()

        if st.button(i18n.get(native, "main_menu"), use_container_width=True, key="search_home"):
            _clear_and_home()
            st.rerun()

    st.title(f"🔍 {i18n.get(native, 'search_title')}")
    st.caption(f"{native} → {target}")

    query = st.text_input(
        i18n.get(native, "search_title"),
        key="search_query",
        label_visibility="collapsed",
        placeholder=i18n.get(native, "search_placeholder"),
    )
    query = (query or "").strip()

    if len(query) < 2:
        st.info(i18n.get(native, "search_hint"))
        return

    any_hits = False
    for mkey, searcher in _SEARCHERS.items():
        icon, label = _MODULE_META[mkey]
        try:
            hits, note = searcher(native, target, query)
        except Exception as e:
            hits, note = [], None
            print(f"[search_app] {mkey} search failed: {e}")
        if note:
            any_hits = True
            st.markdown(f"#### {icon} {label}")
            st.info(note)
            st.markdown("---")
        if not hits:
            continue
        any_hits = True
        st.markdown(f"#### {icon} {label} · {len(hits)}")
        if mkey == "vocab" and target != "English":
            st.caption(i18n.get(native, "search_vocab_english_note"))
        for i, hit in enumerate(hits):
            c1, c2 = st.columns([6, 1])
            with c1:
                st.markdown(
                    f"**{hit['primary']}**  \n"
                    f"<span style='color:var(--mova-ink-3)'>{hit['secondary']}</span>",
                    unsafe_allow_html=True,
                )
            with c2:
                if hit["unit_id"] and st.button("→", key=f"go_{mkey}_{i}",
                                                use_container_width=True):
                    # return_module="search" -- without it this defaults to
                    # "path", so finishing/exiting the lesson would silently
                    # land the user on My Path instead of back on their
                    # search results.
                    _launch_unit({"unit_id": hit["unit_id"]}, user, native, target,
                                  return_module="search")
        st.markdown("---")

    if not any_hits:
        st.info(f"{i18n.get(native, 'search_no_results')} “{query}”")


if __name__ == "__main__":
    main()
