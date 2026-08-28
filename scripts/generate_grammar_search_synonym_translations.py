"""
scripts/generate_grammar_search_synonym_translations.py — one-time
(resumable) translation of engine.grammar_search_synonyms.GRAMMAR_TERMS'
primary English alias (plus NO_DEDICATED_LESSON's terms) into every
non-English language in grammar.py's LANGUAGES list.

Only the FIRST alias per term is translated (not every alias in the list) —
search_app.py fuzzy-matches the query against the translated phrase, which
already tolerates word-form variation (see engine/grammar_search_synonyms.py's
docstring for why that's needed), so one solid native phrasing per term is
enough; translating every alias would multiply API cost for no real benefit.

lesson_id mappings are NOT generated here and never will be — they're
hand-curated in engine/grammar_search_synonyms.py by inspecting the real
topic_en list (see that file's docstring). This script only produces text.

Output: data/grammar_search_synonyms_translated.json --
{lang_code: {term_key: translated_phrase}}.
search_app.py loads this (falling back to the English alias for any
language/term not yet generated) at import time.

Usage:
    python scripts/generate_grammar_search_synonym_translations.py --limit 5 --lang Spanish
        Small test batch on one language — sanity-check quality first.

    python scripts/generate_grammar_search_synonym_translations.py
        Full run, every language missing terms. Resumable: skips (lang, term)
        pairs already present in the output JSON.
        Pass --overwrite to force-regenerate everything instead.

Requires GEMINI_API_KEY (one-time cost — ~24 terms x 13 languages = ~312
calls max, not recurring).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine import gemini
from engine.grammar_search_synonyms import GRAMMAR_TERMS, NO_DEDICATED_LESSON
from engine.loader import LANG_COLUMNS

OUT_PATH = ROOT / "data" / "grammar_search_synonyms_translated.json"

_SKIP_LANGS = {"English"}  # source language, nothing to translate


def _primary_terms() -> list[tuple[str, str]]:
    """[(term_key, primary_english_alias), ...] for every term, mapped or not."""
    out = [(key, entry["en"][0]) for key, entry in GRAMMAR_TERMS.items()]
    out += [(key, aliases[0]) for key, aliases in NO_DEDICATED_LESSON.items()]
    return out


def translate_term(phrase: str, target_lang: str) -> str:
    prompt = (
        f"Translate this English grammar-terminology phrase into "
        f"{target_lang}, the way a language learner in that language would "
        f"naturally search for or refer to this grammatical concept (not a "
        f"literal word-for-word translation if a different phrasing is more "
        f"natural for a student of that language). Return ONLY the "
        f"translated phrase, nothing else, no quotes.\n\nPhrase: {phrase}"
    )
    return gemini._model(gemini._LITE).generate_content(prompt).text.strip().strip('"')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Max terms to generate this run (across all languages).")
    parser.add_argument("--lang", default=None,
                         help="Only this language (full name, e.g. 'Spanish').")
    parser.add_argument("--overwrite", action="store_true",
                         help="Regenerate every term even if already present.")
    args = parser.parse_args()

    generated: dict = {}
    if OUT_PATH.exists():
        generated = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    terms = _primary_terms()
    target_names = [args.lang] if args.lang else [
        name for name in LANG_COLUMNS if name not in _SKIP_LANGS
    ]

    done = 0
    for name in target_names:
        code = LANG_COLUMNS[name]
        bucket = generated.setdefault(code, {})

        for term_key, en_phrase in terms:
            if not args.overwrite and term_key in bucket:
                continue

            try:
                translated = translate_term(en_phrase, name)
            except Exception as e:
                print(f"  FAILED {code}:{term_key} ({e.__class__.__name__}: {e})")
                continue
            bucket[term_key] = translated
            done += 1
            print(f"  {code}:{term_key} -> {translated!r}")

            OUT_PATH.write_text(
                json.dumps(generated, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            if args.limit and done >= args.limit:
                print(f"Hit --limit {args.limit}, stopping.")
                return

    print(f"Done. Generated {done} new terms -> {OUT_PATH}")


if __name__ == "__main__":
    main()
