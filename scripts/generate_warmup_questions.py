"""
scripts/generate_warmup_questions.py — one-time (resumable) content
generation for engine.warmup_loader (CLAUDE.md 2026-09-16: Phase 1 warmup
fires on every single lesson start, the single most frequent live-Gemini
call in the app — worth pre-generating a pool of questions once instead of
paying for a fresh generation on every lesson).

For each (target_lang, CEFR level) pair, samples up to N topics from
engine.gemini's warmup topic lists (the same A1/A2-safe vs B1+-with-advanced
split engine.gemini.warmup_question() already uses) and generates ONE
question per topic via a live Gemini call — same prompt shape as the
now-retired live path (_warmup_question_cached), just called directly here
so this script isn't bottlenecked by @_gated's per-user daily quota.

Only the question TEXT in target_lang is stored — no native_lang
translation baked in (same reasoning as generate_target_grammar_drills.py:
a fixed translation would only ever match one specific viewer's
native_lang). engine.warmup_loader serves the text as-is; bilingual mode
translates lazily via the already-cached engine.gemini.translate_phrase.

Resumable per (lang, level, topic) triplet — skips anything already in the
output CSV.

Usage:
    python scripts/generate_warmup_questions.py --limit 5
        Small test batch first (5 (lang, level) jobs).

    python scripts/generate_warmup_questions.py
        Full run: 14 languages x 6 CEFR levels. Resumable.

Requires GEMINI_API_KEY (env or .streamlit/secrets.toml).
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT_PATH = ROOT / "data" / "warmup_questions.csv"
OUTPUT_FIELDS = ["lang", "level", "topic_en", "question"]

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# engine.recommender.LANG_TO_CODE's language names — duplicated here (as in
# generate_target_grammar_drills.py) to avoid importing engine.recommender
# (and its DATABASE_URL-requiring engine.db import) into a script that only
# needs the language name list. gemini.warmup_question() is called with the
# full name (e.g. "French"), not the 2-letter code, so that's what's stored.
LANGUAGES = [
    "English", "Ukrainian", "Spanish", "Korean", "French", "German",
    "Japanese", "Chinese", "Portuguese", "Italian", "Polish", "Russian",
    "Catalan", "Dutch",
]


def load_done(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as f:
        return {(row["lang"], row["level"], row["topic_en"]) for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap number of (lang, level) jobs (testing)")
    parser.add_argument("--lang", default=None, help="Restrict to one target language (testing)")
    parser.add_argument("--level", default=None, help="Restrict to one CEFR level (testing)")
    parser.add_argument("--n", type=int, default=12, help="Questions per (lang, level) pair")
    parser.add_argument("--overwrite", action="store_true", help="Ignore existing output, regenerate all")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between Gemini calls")
    args = parser.parse_args()

    from engine import gemini

    jobs = [
        (lang, level)
        for lang in LANGUAGES
        if args.lang is None or lang == args.lang
        for level in LEVELS
        if args.level is None or level == args.level
    ]
    if args.limit:
        jobs = jobs[: args.limit]

    done = set() if args.overwrite else load_done(OUTPUT_PATH)
    mode = "w" if args.overwrite or not OUTPUT_PATH.exists() else "a"

    with open(OUTPUT_PATH, mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if mode == "w":
            writer.writeheader()

        generated_jobs = 0
        generated_rows = 0
        for lang, level in jobs:
            from engine.recommender import CEFR_RANK
            pool = gemini._WARMUP_TOPICS
            if CEFR_RANK.get(level, CEFR_RANK["B1"]) >= CEFR_RANK["B1"]:
                pool = gemini._WARMUP_TOPICS + gemini._WARMUP_TOPICS_ADVANCED

            topics = [t for t in pool if (lang, level, t) not in done]
            random.shuffle(topics)
            topics = topics[: args.n]
            if not topics:
                continue

            rows_this_job = 0
            for topic in topics:
                try:
                    result = gemini._model(gemini._LITE).generate_content(
                        f"You are a {lang} language teacher. "
                        f"Ask ONE simple {level} CEFR level question in {lang} about: {topic}. "
                        f"One sentence only. No explanation, no translation."
                    )
                    question = gemini._safe_text(result).strip()
                except Exception as e:
                    print(f"SKIP {lang}/{level}/{topic}: {e}")
                    continue
                if not question:
                    continue
                writer.writerow({
                    "lang": lang, "level": level, "topic_en": topic, "question": question,
                })
                rows_this_job += 1
                generated_rows += 1
                if args.sleep:
                    time.sleep(args.sleep)
            f.flush()
            generated_jobs += 1
            print(f"[{generated_jobs}] {lang}/{level} -> {rows_this_job} questions")

    print(f"Done. {generated_jobs} (lang, level) jobs, {generated_rows} rows written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
