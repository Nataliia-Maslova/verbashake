"""
scripts/generate_reading_lessons.py -- one-time generator for a new language's
Reading track in data/reading_lessons.xlsx (a sheet keyed by the language's
2-letter code, same schema every existing language sheet already uses:
lesson_id ("#"), row_id ("№ строки"), word ("Слово"), IPA ("Транскрипція"),
optional rule text ("Правило читання")).

Unlike every other script added today, this one is NOT translating existing
content -- there is nothing to translate FROM. Reading teaches the target
language's own script/pronunciation from zero, so the content has to be
authored: a letter-by-letter phonics curriculum (vowels -> common consonants
-> real words -> spelling rules/digraphs -> vocabulary practice -> survival
phrases), the same shape every existing sheet already follows (confirmed by
inspecting de/uk/ja/zh's real rows before writing this).

Design: ONE Gemini call per language asks for the ENTIRE lesson-by-lesson
curriculum as structured JSON (not one call per lesson) -- the model needs
the full picture to do cumulative letter-introduction correctly (a lesson's
words may only use letters introduced in this lesson or earlier ones), which
would be lost if lessons were generated independently. The prompt is
explicit about that constraint plus the real pedagogical pattern observed in
the existing sheets.

Quality control this script performs itself (not just trusting the model):
`validate_curriculum()` recomputes, in Python, the cumulative letter set
lesson-by-lesson and flags any word using a letter that hasn't been
introduced yet -- catches "used a letter three lessons early" mistakes
without needing native-speaker review to see them. Rows that fail are
printed as warnings (not silently dropped) so a human can decide whether to
fix or accept them; nothing here is a hard gate that blocks writing the file
gate would be worse than known, visible imperfections.

Usage:
    python scripts/generate_reading_lessons.py --lang Romanian
        Writes 'ro' sheet into data/reading_lessons.xlsx.
    python scripts/generate_reading_lessons.py --lang Romanian --dry-run
        Generate + validate + print, don't write the file.

Requires GEMINI_API_KEY. Backs up the workbook once per day before writing.
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from engine import gemini
from engine.loader import LANG_COLUMNS

DB_PATH = ROOT / "data" / "reading_lessons.xlsx"

# Script-gated languages (engine/recommender.py::SCRIPT_GATE_LANGS) need the
# WHOLE alphabet taught (like uk/ru/ja/zh/ko) before anything else is
# readable -- longer curriculum, no rule column needed (uk's own sheet has
# none). Everything else follows the de/fr/pl-style ~30-lesson curriculum
# with an explicit rule column for genuine spelling rules.
SCRIPT_GATED = {"Bulgarian"}


def build_prompt(lang: str, gated: bool) -> str:
    if gated:
        shape = (
            "This language uses a script most learners don't already know "
            "(like Cyrillic for a Latin-alphabet speaker), so the WHOLE "
            "alphabet must be taught letter-by-letter before any real "
            "reading is possible. Structure: ~35-45 lessons. Early lessons "
            "introduce 1 vowel each or a small batch of the most common, "
            "phonetically simplest consonants (2-6 new letters per lesson); "
            "once ~6-10 letters are known, insert lessons of real, common, "
            "SHORT words built only from already-introduced letters. "
            "Alternate: a few more letters, then more words, until the "
            "full alphabet is covered. The final 8-10 lessons should be "
            "real everyday words (nouns/adjectives), then simple useful "
            "phrases (greetings, 'my name is', 'thank you'). Do NOT include "
            "a 'rule' field for any row in this mode -- leave it null "
            "everywhere; this language's sheet has no rule column content."
        )
    else:
        shape = (
            "Structure: ~28-30 lessons. Lesson 1-2: the core vowels and the "
            "most common, phonetically simple consonants (no digraphs), a "
            "handful of new letters each, one IPA symbol per letter. "
            "Lesson 3: real short common words built ONLY from those "
            "letters. Continue alternating a few more letters/lessons of "
            "words for the less common but still simple letters. Then "
            "several lessons covering the language's real spelling rules "
            "one at a time -- digraphs, diacritics, letters that change "
            "sound depending on context, vowel length, stress marks, "
            "whatever is actually true for this language -- each such "
            "lesson's FIRST row must have a concise 'rule' explanation "
            "(in English) of the pattern, with 1-2 real example words "
            "inline in the rule text itself, and the lesson's other rows "
            "are further real example words (rule field null on those). "
            "Rows that are plain letters or plain words (no new rule) "
            "always have rule = null. After all rules are covered, the "
            "final ~8-10 lessons are real everyday vocabulary (numbers, "
            "colors, common adjectives/nouns) with no new rule, then the "
            "very last 1-2 lessons are simple useful phrases (greetings, "
            "'my name is', 'thank you', 'I don't understand')."
        )

    return f"""You are designing a phonics/reading curriculum that teaches a complete
beginner to read and pronounce {lang}, for a language-learning app. Every
word must be REAL, common, and correctly spelled in {lang} -- never invent
words. Every IPA transcription must be phonetically accurate for standard
{lang}.

HARD CONSTRAINT, check it yourself before answering: every letter/digraph
that will ever appear inside a "word"/"phrase" row must FIRST appear on its
own dedicated row (word = just that letter or digraph) in an earlier lesson,
or earlier in the SAME lesson. This includes rare/loanword-only letters
(e.g. a Latin-script language's own q/w/x/y if it has them) -- give every
one of them its own introduction row somewhere, however late, before any
word uses it. Do not let a letter slip into a word silently. After drafting
the curriculum, re-check every word against the running set of
already-introduced letters and fix any row that jumped ahead.

{shape}

Return ONLY a JSON array, no markdown fences, no commentary. Each element is
one row:
{{"lesson": <int, 1-based, rows in the same lesson share this number>,
  "word": "<letter or word or phrase -- ALWAYS short, e.g. a single letter,
           a digraph, a pattern label like 'c + e/i', or a real word/phrase.
           NEVER put the rule explanation itself here, even on rule rows.>",
  "ipa": "<IPA transcription in [brackets] -- required on every row,
          including rule rows (the sound the pattern makes)>",
  "rule": "<English explanation, or null -- this is the ONLY field that
           holds the longer prose explanation>"}}

Order the array by lesson, then by natural order within the lesson. Every
row must have "word" and "ipa" filled; "rule" is null except on the one row
per rule-teaching lesson described above."""


def _letters_in(word: str) -> set[str]:
    """Lowercase, decompose accents off, return the set of base characters
    (letters only) used in `word` -- lets the validator compare 'ă' against
    itself while still catching genuinely new letters, independent of case."""
    out = set()
    for ch in unicodedata.normalize("NFC", word.lower()):
        if ch.isalpha():
            out.add(ch)
    return out


def validate_curriculum(rows: list[dict]) -> list[str]:
    """Recompute cumulative known-letters lesson by lesson; return a list of
    warning strings for any real practice word using a letter not yet
    introduced by its own lesson (inclusive -- new letters in a lesson count
    as known for words later in that SAME lesson).

    A row counts as a letter/digraph *introduction* (contributes to `known`
    without itself being checked) when its word is short (<=3 chars,
    covering digraphs like "ch"/"gh") OR it carries a rule explanation --
    both plain new-letter rows and "existing letter, new context" rule rows
    (e.g. "c + e/i") introduce something, they just aren't real practice
    words to hold to the cumulative-letters standard. Only rows with NO rule
    and >3 chars are treated as real words that must already be spellable.
    """
    warnings = []
    known: set[str] = set()
    by_lesson: dict[int, list[dict]] = {}
    for r in rows:
        by_lesson.setdefault(r["lesson"], []).append(r)
        # A "word" field this long is almost certainly the rule prose
        # leaking into the wrong column (real words/phrases are short).
        if len(r["word"]) > 40:
            warnings.append(
                f"lesson {r['lesson']}: suspiciously long 'word' field "
                f"(rule text leaked into word?): {r['word']!r}"
            )
        if not r.get("ipa"):
            warnings.append(f"lesson {r['lesson']}: {r['word']!r} has no ipa")

    for lesson_num in sorted(by_lesson):
        for r in by_lesson[lesson_num]:
            w = r["word"]
            letters = _letters_in(w)
            is_intro_row = len(w.strip()) <= 3 or bool(r.get("rule"))
            if is_intro_row:
                known |= letters
                continue
            unknown = letters - known
            if unknown:
                warnings.append(
                    f"lesson {lesson_num}: {w!r} uses not-yet-introduced "
                    f"letter(s) {sorted(unknown)}"
                )
            known |= letters

    # Separately: any letter that appears ONLY inside real words, never on
    # its own introduction row anywhere in the whole curriculum -- catches
    # "z was used in lesson 24 but never formally taught" even though the
    # per-lesson loop above only flags the FIRST offending lesson.
    intro_letters: set[str] = set()
    word_letters: set[str] = set()
    for r in rows:
        w = r["word"]
        letters = _letters_in(w)
        if len(w.strip()) <= 3 or r.get("rule"):
            intro_letters |= letters
        else:
            word_letters |= letters
    never_introduced = word_letters - intro_letters
    if never_introduced:
        warnings.append(
            f"letters used in words but NEVER given their own introduction "
            f"row anywhere: {sorted(never_introduced)}"
        )
    return warnings


def _ensure_sheet(wb, code: str):
    if code in wb.sheetnames:
        return wb[code]
    ws = wb.create_sheet(code)
    ws.append(["#", "№ строки", "Слово", "Транскрипція", "Правило читання"])
    return ws


def _backup_once() -> None:
    stamp = datetime.date.today().strftime("%Y%m%d")
    bak = DB_PATH.with_name(f"{DB_PATH.name}.bak_{stamp}")
    if not bak.exists():
        shutil.copy2(DB_PATH, bak)
        print(f"Backed up {DB_PATH.name} -> {bak.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, help="Full language name, e.g. 'Romanian'.")
    parser.add_argument("--dry-run", action="store_true", help="Generate + validate, don't write.")
    parser.add_argument("--attempts", type=int, default=5,
                         help="Regenerate up to N times, keep the cleanest result.")
    args = parser.parse_args()

    if args.lang not in LANG_COLUMNS:
        sys.exit(f"'{args.lang}' not in engine.loader.LANG_COLUMNS -- add it there first.")
    code = LANG_COLUMNS[args.lang]
    gated = args.lang in SCRIPT_GATED

    prompt = build_prompt(args.lang, gated)
    print(f"Requesting curriculum for {args.lang} ({'script-gated' if gated else 'standard'})...")

    best_rows, best_warnings = None, None
    for attempt in range(1, args.attempts + 1):
        result = gemini._model(gemini._FLASH).generate_content(prompt)
        rows = gemini._parse_json(gemini._safe_text(result), fallback=None)
        if not rows or not isinstance(rows, list):
            print(f"  attempt {attempt}: bad/empty response, retrying")
            continue
        warnings = validate_curriculum(rows)
        print(f"  attempt {attempt}: {len(rows)} rows, {len(warnings)} warning(s)")
        if best_warnings is None or len(warnings) < len(best_warnings):
            best_rows, best_warnings = rows, warnings
        if not warnings:
            break

    rows, warnings = best_rows, best_warnings
    if rows is None:
        sys.exit("All attempts failed to produce usable output.")

    print(f"\nUsing best attempt: {len(rows)} rows across {max(r['lesson'] for r in rows)} lessons.")
    if warnings:
        print(f"{len(warnings)} validation warning(s) remain:")
        for w in warnings[:30]:
            print(f"  ! {w}")
        if len(warnings) > 30:
            print(f"  ... and {len(warnings) - 30} more")
    else:
        print("Validation: no cumulative-letter violations found.")

    if args.dry_run:
        print("\n--dry-run: not writing to the workbook.")
        return

    _backup_once()
    wb = load_workbook(DB_PATH)
    ws = _ensure_sheet(wb, code)

    for i, r in enumerate(rows, start=1):
        ws.append([r["lesson"], i, r["word"], r["ipa"], r.get("rule")])

    wb.save(DB_PATH)
    print(f"Wrote {len(rows)} rows to sheet {code!r} in {DB_PATH}")


if __name__ == "__main__":
    main()
