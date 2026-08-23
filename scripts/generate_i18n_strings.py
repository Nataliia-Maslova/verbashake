"""
scripts/generate_i18n_strings.py — one-time (resumable) translation of the
8-step UI strings (engine/i18n.py's STRINGS["en"]) into every language in
grammar.py's LANGUAGES list.

CLAUDE.md 2026-08-22: i18n only ever had en/uk fully hand-written, plus a
partial es/ko (just step_label/required/try_first/main_menu/titles/hints,
~13 of ~68 leaf keys) — the other 10 languages fell all the way back to
English (engine/i18n.py::_code() had no LANG_TO_CODE entry for them at all).
Unlike CEFR-J Vocabulary (9.8k words -> lazy per-lesson translation, too
expensive to pre-generate per language), the UI string set is small and
fixed (~68 leaf keys) and renders on every page load, so lazy/live
translation would stall first-load latency for no real cost benefit here —
batch-generating once and shipping a static file is the better fit.

English and Ukrainian are treated as authoritative and never touched. Every
other language only gets the keys IT is missing (so es/ko's existing 13
hand-written keys are left alone, only their other ~55 keys get generated).

Output: data/i18n_generated.json -- {lang_code: {key: str, "titles": {"1".."8": str}, "hints": {"1".."8": str}}}.
engine/i18n.py loads and merges this on top of its hand-written STRINGS at
import time (hand-written always wins).

Usage:
    python scripts/generate_i18n_strings.py --limit 5 --lang Spanish
        Small test batch on one language — sanity-check quality first.

    python scripts/generate_i18n_strings.py
        Full run, every language missing keys. Resumable: skips (lang, key)
        pairs already present in the output JSON, so an interrupted run can
        just be restarted without re-paying for completed entries.
        Pass --overwrite to force-regenerate everything instead.

Requires GEMINI_API_KEY (real, one-time API cost — roughly
<missing keys> x <languages missing them> calls, a few hundred total, not
recurring).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine import gemini
from engine import i18n
from engine.loader import LANG_COLUMNS

OUT_PATH = ROOT / "data" / "i18n_generated.json"

# en is the source, uk is already fully hand-written -- never touch either.
_SKIP_LANGS = {"English", "Ukrainian"}


def _flatten_en() -> list[tuple]:
    """[(path, english_text), ...] for every leaf string in STRINGS['en'].
    path is a bare key ("step_label") or a (dict_key, step) tuple for the
    per-step "titles"/"hints" sub-dicts."""
    out = []
    for k, v in i18n.STRINGS["en"].items():
        if isinstance(v, dict):
            for step, text in v.items():
                out.append(((k, step), text))
        else:
            out.append((k, v))
    return out


def _get(bucket: dict, path) -> str | None:
    if bucket is None:
        return None
    if isinstance(path, tuple):
        key, step = path
        return bucket.get(key, {}).get(str(step))
    return bucket.get(path)


def _set(bucket: dict, path, value: str) -> None:
    if isinstance(path, tuple):
        key, step = path
        bucket.setdefault(key, {})[str(step)] = value
    else:
        bucket[path] = value


def translate_ui_string(text: str, target_lang: str) -> str:
    prompt = (
        f"Translate this UI string from English to {target_lang} for a "
        f"language-learning app's practice screen. Keep every emoji, arrow "
        f"(→), and checkmark/cross (✅ ❌) exactly where they are -- only "
        f"translate the words. Return ONLY the translation, nothing else, "
        f"no quotes.\n\nText: {text}"
    )
    return gemini._model(gemini._LITE).generate_content(prompt).text.strip().strip('"')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Max strings to generate this run (across all languages).")
    parser.add_argument("--lang", default=None,
                         help="Only this language (full name, e.g. 'Spanish').")
    parser.add_argument("--overwrite", action="store_true",
                         help="Regenerate every key even if already present.")
    args = parser.parse_args()

    generated: dict = {}
    if OUT_PATH.exists():
        generated = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    all_leaf = _flatten_en()
    target_names = [args.lang] if args.lang else [
        name for name in LANG_COLUMNS if name not in _SKIP_LANGS
    ]

    done = 0
    for name in target_names:
        code = LANG_COLUMNS[name]
        hand_written = i18n.STRINGS.get(code)
        bucket = generated.setdefault(code, {})

        for path, en_text in all_leaf:
            if not args.overwrite:
                if _get(hand_written, path) or _get(bucket, path):
                    continue
            elif _get(hand_written, path):
                continue  # never overwrite hand-written en/uk-quality entries

            try:
                translated = translate_ui_string(en_text, name)
            except Exception as e:
                print(f"  FAILED {code}:{path} ({e.__class__.__name__}: {e})")
                continue
            _set(bucket, path, translated)
            done += 1
            print(f"  {code}:{path} -> {translated!r}")

            OUT_PATH.write_text(
                json.dumps(generated, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            if args.limit and done >= args.limit:
                print(f"Hit --limit {args.limit}, stopping.")
                return

    print(f"Done. Generated {done} new strings -> {OUT_PATH}")


if __name__ == "__main__":
    main()
