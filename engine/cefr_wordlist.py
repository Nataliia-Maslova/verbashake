"""
engine/cefr_wordlist.py — CEFR-level + part-of-speech word pool for the
"construction + level-appropriate vocabulary" drill engine (CLAUDE.md,
2026-08-21 discussion).

Backed by the CEFR-J English Vocabulary Profile + Octanove C1/C2 supplement
(see data/cefr_j/README.md for source/license). English-only pilot — no
equivalent CEFR+POS-tagged open source was found for uk/es/ko.
"""
from __future__ import annotations

import os
import random
from functools import lru_cache

import pandas as pd

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cefr_j"
)

CEFR_RANK: dict[str, int] = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}


@lru_cache(maxsize=1)
def _load() -> pd.DataFrame:
    core = pd.read_csv(os.path.join(_DATA_DIR, "cefrj-vocabulary-profile-1.5.csv"))
    core = core[["headword", "pos", "CEFR"]].rename(columns={"CEFR": "level"})

    c1c2_path = os.path.join(_DATA_DIR, "octanove-vocabulary-profile-c1c2-1.0.csv")
    if os.path.exists(c1c2_path):
        extra = pd.read_csv(c1c2_path)
        extra = extra[["headword", "pos", "CEFR"]].rename(columns={"CEFR": "level"})
        core = pd.concat([core, extra], ignore_index=True)

    core = core.dropna(subset=["headword", "pos", "level"])
    core["level"] = core["level"].str.strip().str.upper()
    core = core[core["level"].isin(CEFR_RANK)]
    return core.drop_duplicates(subset=["headword", "pos", "level"])


def words_for_level(
    level: str,
    pos: str | None = None,
    at_or_below: bool = True,
    limit: int | None = None,
) -> list[str]:
    """
    Word pool for a CEFR level, optionally filtered to one part of speech.

    pos values match the CEFR-J file's own column, e.g. "noun", "verb",
    "adjective", "adverb", "preposition", "determiner".
    at_or_below=True (default) includes everything up to and including
    `level`, so a B1 construction drill isn't starved of the A1/A2 words a
    B1 student already knows — set False to sample only that exact level.
    """
    df = _load()
    if pos:
        df = df[df["pos"] == pos]
    if at_or_below:
        max_rank = CEFR_RANK.get(level.upper(), max(CEFR_RANK.values()))
        df = df[df["level"].map(CEFR_RANK).le(max_rank)]
    else:
        df = df[df["level"] == level.upper()]

    words = df["headword"].drop_duplicates().tolist()
    if limit and len(words) > limit:
        words = random.sample(words, limit)
    return words


def all_entries(level: str | None = None) -> list[dict]:
    """
    Every (headword, pos, level) entry in the CEFR-J profile, one row per
    (headword, pos) pair — takes the LOWEST level if the source data has the
    same word+pos at more than one level (same policy as words_for_level's
    per-word minimum). This is the full vocabulary list itself (for building
    Vocabulary-module lessons), as opposed to words_for_level's flat name
    list (for filling OTHER content's vocabulary slots).

    level: restrict to entries tagged exactly at this CEFR level; None = all.
    """
    df = _load().copy()
    df["_rank"] = df["level"].map(CEFR_RANK)
    df = df.sort_values("_rank").drop_duplicates(subset=["headword", "pos"], keep="first")
    if level:
        df = df[df["level"] == level.upper()]
    return df[["headword", "pos", "level"]].to_dict("records")
