"""
scripts/generate_vocab_from_cefrj.py — one-time (resumable) content generation
for the new CEFR-J-based Vocabulary module (CLAUDE.md, 2026-08-21: replaces
the old "Word Bank" sheets — Basic/Verbs/Food/City in vocabulary_translated.xlsx
— which were alphabetically bucketed and, before today's fix, mistagged C2).

For every (headword, part of speech, CEFR level) entry in the CEFR-J profile
(engine.cefr_wordlist.all_entries() — 9779 entries, A1..C2, English-only —
see data/cefr_j/README.md), generates ONE example sentence via Gemini. Per
Natalia's decision (2026-08-21): generation is English-only (no per-word
translation batch — the existing engine.gemini.translate_phrase() already
handles native-language display on demand, cached, at read time — no need to
pre-translate 9779 words into uk/es/ko upfront), and the example sentence is
built from a GRAMMAR construction at the word's own CEFR level (imlls_database
lesson pool, same DIFFICULTY_TO_CEFR mapping as scripts/seed_content_units.py)
— not a generic sentence. This recycles grammar the student has already met
at that level instead of introducing new sentence patterns alongside new
words, and reuses the exact same "construction + level vocabulary" idea
already prototyped in engine/gemini.py::generate_lesson_construction_drill
(just inverted: there the construction is fixed and vocabulary varies; here
the word is fixed and the construction is picked to match its level).

Construction pool is CUMULATIVE, not single-level (CLAUDE.md, 2026-08-22):
a word at level X can be illustrated using any grammar construction at or
below X (a C1 learner already knows A1..B1 grammar too), picked at random
from that whole range each time. This does double duty: it gives each level
many more candidate sentence patterns instead of being stuck reusing the
same handful (C1 used to always land on lesson 176, "Third conditional" —
now it's one of ~180 candidates), and it naturally covers C2 (still no C2
grammar lessons exist) by falling through to A1..C1 without a separate
special-cased fallback table.

Usage:
    python scripts/generate_vocab_from_cefrj.py --limit 20 --level A1
        Small test batch — use this first to sanity-check output quality
        before committing the full run (9779 Gemini calls, real API cost).

    python scripts/generate_vocab_from_cefrj.py
        Full run, all levels. Resumable: skips headword+pos pairs already
        present in the output CSV, so an interrupted run can just be
        restarted. Pass --overwrite to regenerate everything from scratch.

Requires GEMINI_API_KEY (env or .streamlit/secrets.toml) and a paid Gemini
account for this volume — see engine/gemini.py's cost notes.
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

from engine import cefr_wordlist, loader
from engine.recommender import CEFR_RANK, DIFFICULTY_TO_CEFR

GRAMMAR_DB_PATH = ROOT / "data" / "imlls_database_with_titles.xlsx"
OUTPUT_PATH = ROOT / "data" / "vocabulary_cefrj.csv"
OUTPUT_FIELDS = ["headword", "pos", "level", "sentence", "source_grammar_lesson_id"]


def build_grammar_pool() -> dict[str, list[dict]]:
    """
    {CEFR level: [{"lesson_id": int, "topic": str, "phrases": [str, ...]}, ...]}
    from imlls_database_with_titles.xlsx — same difficulty->CEFR mapping used
    everywhere else in this project (engine.recommender.DIFFICULTY_TO_CEFR).
    """
    import pandas as pd

    lessons_df = pd.read_excel(GRAMMAR_DB_PATH, sheet_name="lessons", engine="openpyxl")
    phrases_df = pd.read_excel(GRAMMAR_DB_PATH, sheet_name="phrases", engine="openpyxl")

    pool: dict[str, list[dict]] = {}
    for _, row in lessons_df.iterrows():
        lid = row.get("lesson_id")
        if pd.isna(lid):
            continue
        lid = int(lid)
        level = DIFFICULTY_TO_CEFR.get(int(row.get("difficulty", 1)))
        if not level:
            continue
        phrases = phrases_df[phrases_df["lesson_id"] == lid]["en"].dropna().tolist()
        pool.setdefault(level, []).append({
            "lesson_id": lid,
            "topic": str(row.get("topic_en", "")),
            "phrases": phrases,
        })
    return pool


def pick_construction(pool: dict[str, list[dict]], level: str) -> dict | None:
    """
    Random construction from every level at or below `level` (cumulative,
    not just the exact-level bucket) -- see module docstring.
    """
    max_rank = CEFR_RANK.get(level, 0)
    candidates = [
        c for lvl, bucket in pool.items()
        if CEFR_RANK.get(lvl, 99) <= max_rank
        for c in bucket
    ]
    if not candidates:
        return None
    return random.choice(candidates)


def build_prompt(entry: dict, construction: dict, *,
                  retry_missing: bool = False, retry_fragment: bool = False) -> str:
    example_block = "\n".join(f"  - {p}" for p in construction["phrases"][:3])
    retry_bits = []
    if retry_missing:
        retry_bits.append(
            f'Your previous attempt did not actually contain the word '
            f'"{entry["headword"]}" -- make sure it appears in the sentence this time.'
        )
    if retry_fragment:
        retry_bits.append(
            "Your previous attempt was a bare word or phrase, not a full sentence -- "
            "this time write a complete sentence with a subject and a verb."
        )
    retry_note = ("\n" + " ".join(retry_bits) + "\n") if retry_bits else ""
    return (
        f"Write ONE natural {entry['level']} CEFR-level English sentence that uses the "
        f"word \"{entry['headword']}\" as a {entry['pos']}.\n"
        f"The sentence should follow this grammar pattern (topic: {construction['topic']}), "
        f"illustrated by these examples (do not reuse them verbatim):\n{example_block}\n\n"
        "Rules:\n"
        f"- The sentence MUST contain the exact word \"{entry['headword']}\".\n"
        "- Output exactly ONE sentence. If the examples above are questions, write only a "
        "question (do not add an answer). If they are statements, write only a statement. "
        "Never output a question followed by its answer.\n"
        "- Write a COMPLETE sentence with a subject and a verb -- never an isolated word, "
        "noun phrase, or fragment (e.g. \"Eating an apple\" or \"a used microscope\" are NOT "
        "acceptable, even if the examples above happen to be phrases rather than full "
        "sentences -- fix that when adapting the pattern, don't copy the fragment).\n"
        "- If this exact grammar pattern doesn't fit naturally with this word, adapt it "
        "slightly while keeping the same core structure -- a natural, sensible sentence "
        "matters more than a rigid pattern match.\n"
        f"{retry_note}"
        "Return ONLY the sentence, nothing else -- no quotes, no explanation."
    )


def contains_word(sentence: str, headword: str) -> bool:
    """
    Loose containment check -- case-insensitive, ignores surrounding
    punctuation. CEFR-J headwords are sometimes several alternate spellings
    joined with "/" (e.g. "a.m./A.M./am/AM", "airplane/aeroplane") -- a
    sentence only ever uses ONE of those, so check each alternative
    separately rather than the joined string (which would never match).
    """
    import re
    sentence_lower = sentence.lower()
    for alt in headword.lower().split("/"):
        alt = alt.strip()
        if not alt:
            continue
        pattern = r"\b" + re.escape(alt) + r"\w*"
        if re.search(pattern, sentence_lower):
            return True
    return False


def is_fragment(sentence: str) -> bool:
    """
    Heuristic: a bare word/noun-phrase, not a full sentence -- e.g. "Eating
    an apple" or "a used microscope" (found via a length-based audit after
    the first full CEFR-J generation run, CLAUDE.md 2026-08-22). 3 words is
    a deliberately loose floor -- short but genuinely complete sentences
    exist ("He is rich.", "You are hot."), this only catches the clearly
    fragmentary ones without flagging those as false positives.
    """
    return len(sentence.split()) <= 3


def generate_sentence(entry: dict, construction: dict) -> str:
    """Generates a sentence, retrying once if the target word didn't actually
    appear or the result was a bare fragment instead of a full sentence."""
    from engine import gemini

    prompt = build_prompt(entry, construction)
    result = gemini._model(gemini._LITE).generate_content(prompt).text.strip().strip('"')
    missing  = not contains_word(result, entry["headword"])
    fragment = is_fragment(result)
    if not missing and not fragment:
        return result

    retry_prompt = build_prompt(entry, construction, retry_missing=missing, retry_fragment=fragment)
    retried = gemini._model(gemini._LITE).generate_content(retry_prompt).text.strip().strip('"')
    if not contains_word(retried, entry["headword"]):
        print(f"  WARNING: \"{entry['headword']}\" still missing after retry -- keeping anyway for manual review")
    elif is_fragment(retried):
        print(f"  WARNING: \"{entry['headword']}\" still a fragment after retry -- keeping anyway for manual review")
    return retried


def load_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as f:
        return {(row["headword"], row["pos"]) for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap number of words (testing)")
    parser.add_argument("--level", default=None, help="Restrict to one CEFR level (testing)")
    parser.add_argument("--overwrite", action="store_true", help="Ignore existing output, regenerate all")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between Gemini calls")
    args = parser.parse_args()

    entries = cefr_wordlist.all_entries(level=args.level)
    random.shuffle(entries)
    if args.limit:
        entries = entries[: args.limit]

    done = set() if args.overwrite else load_done(OUTPUT_PATH)
    pool = build_grammar_pool()

    mode = "w" if args.overwrite or not OUTPUT_PATH.exists() else "a"
    with open(OUTPUT_PATH, mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if mode == "w":
            writer.writeheader()

        generated = 0
        for entry in entries:
            key = (entry["headword"], entry["pos"])
            if key in done:
                continue
            construction = pick_construction(pool, entry["level"])
            if construction is None:
                print(f"SKIP {entry['headword']} ({entry['pos']}, {entry['level']}): no grammar pool")
                continue
            sentence = generate_sentence(entry, construction)
            writer.writerow({
                "headword": entry["headword"],
                "pos": entry["pos"],
                "level": entry["level"],
                "sentence": sentence,
                "source_grammar_lesson_id": construction["lesson_id"],
            })
            f.flush()
            generated += 1
            print(f"[{generated}] {entry['headword']} ({entry['pos']}, {entry['level']}) -> {sentence}")
            if args.sleep:
                time.sleep(args.sleep)

    print(f"Done. Wrote {generated} new rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
