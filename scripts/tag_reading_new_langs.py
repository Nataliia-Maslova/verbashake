"""
scripts/tag_reading_new_langs.py — one-time, additive extension of
data/reading_tags_template.csv to the 8 languages that already have real
content in data/reading_lessons.xlsx (fr/de/pt/it/pl/ru/ja/zh) but were never
tagged -- scripts/seed_content_units.py::READING_LANGS only covered
en/uk/es/ko, so content_units had zero reading rows for the other 8 (2026-08-27,
Natalia noticed "Reading 0/0" for French in My Path -- the lessons exist,
they were just never wired up).

Does NOT touch the 273 existing rows (en/uk/es/ko) -- appends only.

Method mirrors exactly how those 273 rows were tagged (CLAUDE.md, Phase C,
2026-08-16 "продовження"), so the two batches aren't tagged by different
rules:
  - level: positional bucket -- each language's N lessons split into 6 equal
    segments (A1..C2) by lesson number, boundary_i = ceil(i*N/6)+1. Verified
    against the 4 existing languages' real boundaries (en 1/15/28/41/55/68,
    ko 1/14/26/39/51/64, es 1/10/19/28/37/46, uk 1/12/23/34/45/56) -- exact
    match, not a guess at the method.
  - topic: first non-null "Правило читання" cell for that lesson number, else
    empty (same as en/ko -- topic is only ever real data pulled from that
    column, never invented from the "Слово" content itself).
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
TEMPLATE = DATA_DIR / "reading_tags_template.csv"

NEW_LANGS = ["fr", "de", "pt", "it", "pl", "ru", "ja", "zh"]
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _level_for(n: int, total: int) -> str:
    boundaries = [1] + [math.ceil(i * total / 6) + 1 for i in range(1, 6)]
    idx = 0
    for i, b in enumerate(boundaries):
        if n >= b:
            idx = i
    return LEVELS[idx]


def main() -> None:
    existing_rows = []
    existing_keys = set()
    if TEMPLATE.exists():
        with open(TEMPLATE, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                existing_rows.append(row)
                existing_keys.add((row["lang_code"], row["lesson_number"]))

    xl = pd.ExcelFile(DATA_DIR / "reading_lessons.xlsx", engine="openpyxl")
    new_rows = []
    for lang in NEW_LANGS:
        if lang not in xl.sheet_names:
            print(f"  skip {lang}: no sheet")
            continue
        df = xl.parse(lang)
        lesson_numbers = sorted(int(n) for n in df["#"].dropna().unique().tolist())
        total = len(lesson_numbers)
        rule_col = "Правило читання"
        for n in lesson_numbers:
            key = (lang, str(n))
            if key in existing_keys:
                continue
            sub = df[df["#"] == n]
            topic = ""
            if rule_col in df.columns:
                rules = sub[rule_col].dropna()
                if len(rules):
                    topic = str(rules.iloc[0])
            new_rows.append({
                "lang_code": lang,
                "lesson_number": n,
                "level": _level_for(n, total),
                "topic": topic,
            })
        print(f"  {lang}: {total} lessons tagged")

    all_rows = existing_rows + new_rows
    with open(TEMPLATE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lang_code", "lesson_number", "level", "topic"])
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {TEMPLATE}: {len(existing_rows)} existing + {len(new_rows)} new = {len(all_rows)} rows")


if __name__ == "__main__":
    main()
