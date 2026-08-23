"""
engine/placement_quiz.py — short optional placement quiz.

CLAUDE.md item 3 (decided 2026-08-21 in chat): a short quiz (not a full
adaptive test) that seeds initial mastery so a returning learner doesn't
start every topic at 0.0 ("knows nothing").

Zero live Gemini calls — grades answers locally via engine.scorer, so it
works for free users, not just Premium. Uses evaluate_flexible() (word-order
/synonym-tolerant), not the plain evaluate() used for fill-in-blank/reading
checks — a free-form translation answer here is graded against a single
reference phrase, so an equally valid paraphrase that just orders words
differently ("libro malo" vs "mal libro") must not be marked wrong.

Samples one existing lesson phrase per CEFR level already present in
content_units for the chosen module/language, asks the student to translate
native -> target, and feeds the highest level answered correctly (with
nothing missed below it) into recommender.seed_mastery_from_level().
"""
from __future__ import annotations

import random
from typing import Callable

from engine import db, recommender
from engine.scorer import evaluate_flexible as evaluate

_LEVELS_ORDER = ["A1", "A2", "B1", "B2", "C1"]  # C2 skipped — too sparse in the current catalog


def build_quiz(
    module: str,
    target_lang: str,
    df_all,
    get_lesson_fn: Callable,
) -> list[dict]:
    """
    One question per CEFR level that has content for this module/language.

    df_all / get_lesson_fn: the (loaded DataFrame, lesson-filter function)
    pair grammar.py's module loaders already produce (engine.loader /
    engine.vocab_loader) — passed in so this module stays free of any
    Streamlit/UI dependency.
    """
    lang_code  = recommender.LANG_TO_CODE.get(target_lang, "en")
    real_codes = tuple(recommender.LANG_TO_CODE.values())
    items = []
    for level in _LEVELS_ORDER:
        units = db.fetch_all(
            "SELECT * FROM content_units WHERE module=:m AND level=:lvl "
            "AND (source_lesson NOT IN :real_codes OR source_lesson = :lang_code)",
            {"m": module, "lvl": level, "lang_code": lang_code, "real_codes": real_codes},
        )
        if not units:
            continue
        # Try units in random order until one has a phrase with real,
        # pre-baked native+target text. This quiz must stay Gemini-free
        # (works for free users too), so it can't translate a phrase on the
        # spot -- for module="vocab" that means every unit is skipped now
        # (CEFR-J, CLAUDE.md 2026-08-22, is the only Vocabulary source
        # for every target_lang and only ever has real text on the English
        # side; a student's native_lang is never also English=target_lang),
        # so vocab always ends up with items=[] here -- see app.py's
        # "Vocabulary quiz isn't available yet" caption. Grammar units are
        # unaffected -- their native/target columns are always pre-baked.
        random.shuffle(units)
        for unit in units:
            try:
                lesson_id = recommender.parse_unit_id(unit["unit_id"])["lesson_id"]
                lesson_df = get_lesson_fn(df_all, lesson_id)
            except Exception:
                continue
            if lesson_df.empty:
                continue
            usable = lesson_df[
                lesson_df["native"].astype(str).str.strip().ne("") &
                lesson_df["target"].astype(str).str.strip().ne("")
            ]
            if usable.empty:
                continue
            phrase = usable.sample(1).iloc[0].to_dict()
            items.append({
                "level":   level,
                "unit_id": unit["unit_id"],
                "native":  phrase["native"],
                "target":  phrase["target"],
            })
            break
    return items


def score_quiz(
    user_id: str, target_lang: str, module: str,
    items: list[dict], answers: dict[int, str],
) -> dict:
    """
    Grade each answer locally, estimate a CEFR level, seed mastery from it.

    estimated_level = the highest level answered correctly, capped just below
    the lowest level missed (so a lucky guess on a harder item past a real
    gap doesn't inflate the estimate).
    """
    results = []
    highest_correct_rank = -1
    first_miss_rank = len(_LEVELS_ORDER)
    for i, item in enumerate(items):
        user_answer = answers.get(i, "")
        passed = evaluate(user_answer, item["target"])["passed"]
        results.append({**item, "user_answer": user_answer, "passed": passed})
        rank = _LEVELS_ORDER.index(item["level"])
        if passed:
            highest_correct_rank = max(highest_correct_rank, rank)
        else:
            first_miss_rank = min(first_miss_rank, rank)

    usable_rank = min(highest_correct_rank, first_miss_rank - 1)
    estimated_level = _LEVELS_ORDER[usable_rank] if usable_rank >= 0 else None

    if estimated_level:
        # Seed every module, not just the one quizzed (CLAUDE.md report,
        # 2026-08-23): "My Path" (path_app.py) picks its next lesson across
        # ALL modules via get_next(module=None) -- seeding only "module"
        # left every other module still at _UNSEEN_MASTERY, so it always
        # outscored the now-deprioritized quizzed module (an untouched A1
        # topic scores higher than a quiz-seeded "already knows this" A2
        # topic) and My Path kept recommending Phrasebook lesson 1 right
        # after a learner proved A2 grammar. seed_mastery_from_level()
        # already skips any topic with real recorded attempts, so this
        # can't clobber genuine progress in the other modules.
        for m in recommender.ALL_MODULES:
            recommender.seed_mastery_from_level(user_id, target_lang, m, estimated_level)

    return {"results": results, "estimated_level": estimated_level}
