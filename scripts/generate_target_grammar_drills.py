"""
scripts/generate_target_grammar_drills.py — one-time (resumable) content
generation for engine.target_grammar_paths's roadmap (LINGUISTIC_AUDIT.md
section 1 / CLAUDE.md 2026-08-23: grammar topics genuine to a target
language, e.g. Slavic verbal aspect, ser/estar, keigo, with no imlls_database
lesson at all and no English sentence to translate from).

For every topic in TARGET_GRAMMAR_PATHS, generates N example sentences in
that topic's OWN language (not English — that's the whole point) via
engine.gemini.generate_target_grammar_drill, called with native_lang set to
target_lang itself (the "native" field of the result is discarded here; a
real viewer's native-language translation is done lazily at read time by
engine.target_grammar_loader, via the same engine.gemini.translate_phrase +
phrase_translations cache the CEFR-J Vocabulary module already uses — no
point baking in a fixed English/whatever translation here that would only
ever match one specific viewer's native_lang).

Resumable per TOPIC (not per sentence, unlike generate_vocab_from_cefrj.py —
one Gemini call already returns a whole batch of N sentences for a topic, so
there's no finer unit worth resuming at): skips any (lang, topic_key) pair
whose sentences are already in the output CSV. Only 75 topics total (one
call each) — nowhere near generate_vocab_from_cefrj.py's ~9800-call scale.

Usage:
    python scripts/generate_target_grammar_drills.py --limit 3
        Small test batch first.

    python scripts/generate_target_grammar_drills.py
        Full run, all 75 topics across 13 languages. Resumable.

Requires GEMINI_API_KEY (env or .streamlit/secrets.toml).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine import target_grammar_paths as tgp

OUTPUT_PATH = ROOT / "data" / "target_grammar_drills.csv"
OUTPUT_FIELDS = ["lang", "topic_key", "level", "sentence"]

# engine.recommender.LANG_TO_CODE, duplicated here to avoid importing
# engine.recommender (which requires DATABASE_URL at import-adjacent use)
# into a script that only needs the name->code mapping.
LANG_TO_CODE = {
    "English": "en", "Ukrainian": "uk", "Spanish": "es", "Korean": "ko",
    "French": "fr", "German": "de", "Japanese": "ja", "Chinese": "zh",
    "Portuguese": "pt", "Italian": "it", "Polish": "pl", "Russian": "ru",
    "Catalan": "ca", "Dutch": "nl",
}


def load_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as f:
        return {(row["lang"], row["topic_key"]) for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap number of topics (testing)")
    parser.add_argument("--lang", default=None, help="Restrict to one target language (testing)")
    parser.add_argument("--n", type=int, default=8, help="Sentences per topic")
    parser.add_argument("--overwrite", action="store_true", help="Ignore existing output, regenerate all")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between Gemini calls")
    args = parser.parse_args()

    from engine import gemini

    jobs = [
        (lang, topic)
        for lang, topics in tgp.TARGET_GRAMMAR_PATHS.items()
        if args.lang is None or lang == args.lang
        for topic in topics
    ]
    if args.limit:
        jobs = jobs[: args.limit]

    done = set() if args.overwrite else load_done(OUTPUT_PATH)
    mode = "w" if args.overwrite or not OUTPUT_PATH.exists() else "a"

    with open(OUTPUT_PATH, mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if mode == "w":
            writer.writeheader()

        generated_topics = 0
        generated_rows = 0
        for lang, topic in jobs:
            key = (lang, topic["key"])
            if key in done:
                continue
            # native_lang=target_lang here is a don't-care placeholder — see
            # module docstring, only "target" is kept from the result.
            drill = gemini.generate_target_grammar_drill.__wrapped__(
                topic["title"], topic["description"], topic["level"],
                lang, lang, n=args.n,
            )
            items = drill.get("items", [])
            if not items:
                print(f"SKIP {lang}/{topic['key']}: empty result")
                continue
            for it in items:
                sentence = it.get("target", "").strip()
                if not sentence:
                    continue
                writer.writerow({
                    "lang": lang,
                    "topic_key": topic["key"],
                    "level": topic["level"],
                    "sentence": sentence,
                })
                generated_rows += 1
            f.flush()
            generated_topics += 1
            print(f"[{generated_topics}] {lang}/{topic['key']} ({topic['level']}) -> {len(items)} sentences")
            if args.sleep:
                time.sleep(args.sleep)

    print(f"Done. {generated_topics} topics, {generated_rows} rows written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
