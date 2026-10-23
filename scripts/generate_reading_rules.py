"""
scripts/generate_reading_rules.py — one-time (resumable) translation of the
English reading-pronunciation rules (sheet «Правила» in reading_lessons.xlsx,
which only has ru/en/es/uk columns) into every other native language.

Without this, English-target Reading showed the rule in English to anyone
whose native language isn't ru/en/es/uk (found 2026-10-23 on a Catalan UI).

Output: data/reading_rules_generated.json  {"Catalan": {"1": "...", ...}, ...}
Read by reading_app.load() for natives without a sheet column.

Usage:
    python scripts/generate_reading_rules.py            # missing languages only
    python scripts/generate_reading_rules.py --langs ca,fr
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import gemini
from engine.loader import LANG_COLUMNS

SRC = ROOT / "data" / "reading_lessons.xlsx"
OUT = ROOT / "data" / "reading_rules_generated.json"
SHEET_LANGS = {"Ukrainian", "Russian", "English", "Spanish"}


def _rules_en() -> dict[str, str]:
    df = pd.read_excel(SRC, engine="openpyxl", sheet_name="Правила")
    df.columns = ["lesson_id", "ru", "en", "es", "uk"]
    return {str(int(r.lesson_id)): str(r.en).strip()
            for r in df.itertuples() if pd.notna(r.en) and str(r.en).strip()}


def _translate(rules: dict[str, str], lang: str) -> dict[str, str]:
    prompt = (
        f"Translate these English pronunciation rules for learners of English into {lang}.\n"
        "They are shown to a student whose native language is "
        f"{lang}, explaining how English letters are pronounced.\n"
        "Rules:\n"
        "- Keep every English example word, letter name, IPA transcription in [ ] "
        "and stress mark (') exactly as written — do not translate or change them, and do not add any new square brackets or quotes around words.\n"
        "- Translate only the explanation text, naturally, in standard written "
        f"{lang}.\n"
        "- Return ONLY a JSON object with the same keys and the translated strings.\n\n"
        + json.dumps(rules, ensure_ascii=False, indent=1)
    )
    resp = gemini._model(gemini._FLASH).generate_content(prompt)
    data = gemini._parse_json(resp.text, {})
    if not isinstance(data, dict) or set(data) != set(rules):
        raise ValueError(f"{lang}: bad keys in response")
    return {k: str(v).strip() for k, v in data.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="", help="comma-separated codes to (re)generate")
    args = ap.parse_args()

    rules = _rules_en()
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    wanted = {c.strip() for c in args.langs.split(",") if c.strip()}

    for lang, code in LANG_COLUMNS.items():
        if lang in SHEET_LANGS:
            continue
        if wanted and code not in wanted:
            continue
        if not wanted and lang in out:
            continue
        try:
            out[lang] = _translate(rules, lang)
            print(f"{lang}: {len(out[lang])} rules")
        except Exception as e:  # keep going; rerun picks it up
            print(f"{lang}: FAILED {e}")
            continue
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
