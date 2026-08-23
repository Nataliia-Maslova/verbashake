"""
engine/cefr_j_vocab_loader.py — loader for the CEFR-J-based Vocabulary
module (CLAUDE.md, 2026-08-21/22: replaces the old "Word Bank" sheets —
Basic/Verbs/Food/City in vocabulary_translated.xlsx, which were
alphabetically bucketed, C2-mistagged, and only ~1/5 of the CEFR-J word
count). data/vocabulary_cefrj.csv has one English example sentence per
(headword, pos, CEFR level) — see scripts/generate_vocab_from_cefrj.py
for how it was generated.

CLAUDE.md 2026-08-22: the same English (headword, sentence) list is
now used as the canonical Vocabulary source for every target_lang, not
just English — same words/situations transfer across languages, so
there's no need for a separate per-language wordlist. Unlike
vocabulary_translated.xlsx (parallel en/uk/es/ko columns baked into the
sheet), this CSV only ever stores the English sentence (`source_en`);
`native` and `target` are left empty whenever native_lang/target_lang
isn't English, and callers fill them in on demand via
engine.gemini.translate_phrase (cached, paid-gated) rather than
pre-translating all ~9.8k rows upfront per language.

The CSV has no lesson grouping (one row = one word) -- this module invents
one by chunking LESSON_SIZE consecutive words within each CEFR level (file
order, not curated). Global lesson_id is offset by GID_BASE so it can never
collide with vocabulary_translated.xlsx's own global lesson_id range (a few
hundred, per engine.vocab_loader._build_global_index) -- content_units rows
for both datasets coexist under the same `module='vocab'` value, and
engine.recommender.parse_unit_id only cares about the unit_id string shape,
not which loader produced it.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

LESSON_SIZE = 10
GID_BASE    = 100_000

CSV_PATH = Path(__file__).parent.parent / "data" / "vocabulary_cefrj.csv"

_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


@st.cache_data(show_spinner=False)
def _read_csv(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


@st.cache_data(show_spinner=False)
def _build_index(csv_path: str) -> pd.DataFrame:
    """
    Assign (lesson_id, phrase_id, local_lesson) to every CSV row: chunks of
    LESSON_SIZE consecutive words within each CEFR level, numbered globally
    across levels in A1..C2 order so lesson_id is stable across reruns
    (same csv -> same numbering, cached on the file path).
    """
    df = _read_csv(csv_path).reset_index(drop=True)
    df["_row"] = df.index

    lesson_id    = pd.Series(0, index=df.index, dtype="int64")
    phrase_id    = pd.Series(0, index=df.index, dtype="int64")
    local_lesson = pd.Series(0, index=df.index, dtype="int64")

    gid = GID_BASE
    for level in _LEVEL_ORDER:
        level_rows = df.index[df["level"] == level]
        for chunk_start in range(0, len(level_rows), LESSON_SIZE):
            gid += 1
            chunk_idx = level_rows[chunk_start: chunk_start + LESSON_SIZE]
            lesson_id.loc[chunk_idx]    = gid
            local_lesson.loc[chunk_idx] = (chunk_start // LESSON_SIZE) + 1
            phrase_id.loc[chunk_idx]    = range(1, len(chunk_idx) + 1)

    df["lesson_id"]    = lesson_id
    df["phrase_id"]    = phrase_id
    df["local_lesson"] = local_lesson
    return df


@st.cache_data(show_spinner=False)
def load_cefrj_vocab(csv_path: str, native_lang: str, target_lang: str) -> pd.DataFrame:
    """
    Returns a DataFrame with the same column shape engine.vocab_loader.load_vocab
    produces (lesson_id, phrase_id, topic, local_lesson, native, target) so it
    slots into the existing vocab module machinery (get_vocab_lesson,
    get_available_vocab_lessons, LessonSession) unchanged, plus one extra
    `source_en` column carrying the canonical English sentence.

    `topic` is the CEFR level ("A1".."C2") -- CEFR-J has no thematic grouping,
    level is the only real category. `native`/`target` are filled directly
    from the English sentence when native_lang/target_lang is English
    (no translation needed) and left empty otherwise; LessonSession fills
    the empty ones in lazily, per-lesson, when the lesson is actually opened.
    """
    df = _build_index(csv_path)
    en_sentence = df["sentence"]
    return pd.DataFrame({
        "lesson_id":    df["lesson_id"],
        "phrase_id":    df["phrase_id"],
        "topic":        df["level"],
        "local_lesson": df["local_lesson"],
        "native":       en_sentence if native_lang == "English" else "",
        "target":       en_sentence if target_lang == "English" else "",
        "source_en":    en_sentence,
        "headword":     df["headword"],
    }).sort_values(["lesson_id", "phrase_id"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def _lesson_level_index(csv_path: str) -> dict[int, str]:
    df = _build_index(csv_path)
    return dict(zip(df["lesson_id"], df["level"]))


def topic_for_lesson(lesson_id: int, csv_path: str | None = None) -> str | None:
    """CEFR level ('A1'..'C2') for a CEFR-J global lesson_id, or None if not
    one of ours (e.g. a Word Bank lesson_id was passed by mistake)."""
    return _lesson_level_index(str(csv_path or CSV_PATH)).get(lesson_id)
