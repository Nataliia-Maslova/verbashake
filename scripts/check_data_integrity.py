"""Read-only integrity checks for the grammar phrase database and target-grammar drills.

Usage: python scripts/check_data_integrity.py
Prints findings grouped by check; changes nothing.
"""
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "imlls_database_with_titles.xlsx"
DRILLS = ROOT / "data" / "target_grammar_drills.csv"

LANGS = ["en", "uk", "es", "ko", "fr", "de", "ja", "zh", "pt", "it", "pl", "ru",
         "ca", "nl", "ro", "bg", "cs", "tr", "sv"]

CYR = re.compile(r"[Ѐ-ӿ]")
HAN = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
UK_ONLY = set("іїєґІЇЄҐ")
RU_ONLY = set("ыэъёЫЭЪЁ")
BG_HINT = set("ъЪ")

META = re.compile(
    r"(here is|here's|translation|translated|note:|\bnote\b\s*[:(]|as an ai|sure[,!]|"
    r"certainly|of course|```|\*\*|\bexplanation\b|перевод:|переклад:|\[|\]|\{|\})", re.I)


def script_ok(lang: str, s: str) -> str | None:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return None
    n = len(letters)
    cyr = len(CYR.findall(s)) / n
    lat = len(LATIN.findall(s)) / n
    if lang in ("uk", "ru", "bg"):
        if cyr < 0.8:
            return f"expected Cyrillic, got {cyr:.0%}"
        if lang == "uk" and any(c in RU_ONLY for c in s):
            return "Russian-only letters in uk"
        if lang == "ru" and any(c in UK_ONLY for c in s):
            return "Ukrainian-only letters in ru"
        if lang == "bg" and any(c in RU_ONLY - BG_HINT for c in s):
            return "ы/э/ё in bg"
        if lang == "bg" and any(c in UK_ONLY for c in s):
            return "Ukrainian-only letters in bg"
    elif lang == "ko":
        if len(HANGUL.findall(s)) / n < 0.7:
            return "expected Hangul"
    elif lang == "ja":
        if (len(HAN.findall(s)) + len(KANA.findall(s))) / n < 0.7:
            return "expected kana/kanji"
    elif lang == "zh":
        if len(HAN.findall(s)) / n < 0.8:
            return "expected Han"
        if KANA.search(s):
            return "kana in zh"
    else:
        if lat < 0.8:
            return f"expected Latin, got {lat:.0%}"
    return None


def main() -> int:
    findings: dict[str, list[str]] = defaultdict(list)

    def add(check: str, msg: str):
        findings[check].append(msg)

    ph = pd.read_excel(DB, sheet_name="phrases")
    ls = pd.read_excel(DB, sheet_name="lessons")

    # --- structure
    if ph["phrase_id"].duplicated().any():
        add("ids", f"duplicate phrase_id: {ph.loc[ph['phrase_id'].duplicated(), 'phrase_id'].tolist()[:10]}")
    counts = ph.groupby("lesson_id").size()
    for lid, n in counts.items():
        if n != 8:
            add("phrases-per-lesson", f"lesson {lid} has {n} phrases")
    declared = dict(zip(ls["lesson_id"], ls["phrases"]))
    for lid, n in counts.items():
        if declared.get(lid) != n:
            add("lessons-sheet-mismatch", f"lesson {lid}: lessons sheet says {declared.get(lid)}, phrases has {n}")
    missing = set(ls["lesson_id"]) - set(counts.index)
    if missing:
        add("lessons-sheet-mismatch", f"lessons without phrases: {sorted(missing)}")

    # --- per-cell checks
    ratios: dict[str, list[float]] = defaultdict(list)
    for lang in LANGS:
        if lang not in ph.columns:
            add("structure", f"column {lang} missing")
            continue
        for _, row in ph.iterrows():
            s = row[lang]
            ref = row["en"]
            tag = f"{lang} L{row['lesson_id']}/P{row['phrase_id']}"
            if not isinstance(s, str) or not s.strip():
                add("empty", tag)
                continue
            if s != s.strip():
                add("whitespace", f"{tag}: leading/trailing space {s!r}")
            if "  " in s:
                add("whitespace", f"{tag}: double space {s!r}")
            if "\n" in s:
                add("whitespace", f"{tag}: newline {s!r}")
            if lang != "en" and META.search(s):
                add("meta-text", f"{tag}: {s!r}")
            if lang != "en":
                bad = script_ok(lang, s)
                if bad:
                    add("script", f"{tag}: {bad}: {s!r}")
                if s.strip().lower() == str(ref).strip().lower() and lang not in ("nl", "ca"):
                    if len(s) > 3:
                        add("untranslated", f"{tag}: identical to en {s!r}")
                if re.search(r"[A-Za-z]{4,}", s) and lang in ("uk", "ru", "bg", "ko", "ja", "zh"):
                    add("latin-in-nonlatin", f"{tag}: {s!r}")
                ratios[lang].append(len(s) / max(len(str(ref)), 1))
                r_end = str(ref).strip()[-1:] in ".?!"
                s_end = s.strip()[-1:] in ".?!。？！"
                if r_end != s_end:
                    add("end-punct", f"{tag}: en={str(ref)!r} {lang}={s!r}")
                if str(ref).strip().endswith("?") and not s.strip().endswith(("?", "？")):
                    add("question-mark", f"{tag}: en={str(ref)!r} {lang}={s!r}")

    # --- length outliers vs per-language median ratio
    for lang, rs in ratios.items():
        med = statistics.median(rs)
        if med == 0:
            continue
        idx = 0
        for _, row in ph.iterrows():
            s = row[lang]
            if not isinstance(s, str):
                continue
            r = len(s) / max(len(str(row["en"])), 1)
            if r > med * 3 and len(s) > 25:
                add("length-outlier", f"{lang} L{row['lesson_id']}/P{row['phrase_id']}: ratio {r:.1f} (median {med:.1f}) {s!r}")
            elif r < med / 3 and len(str(row["en"])) > 20:
                add("length-outlier", f"{lang} L{row['lesson_id']}/P{row['phrase_id']}: ratio {r:.1f} (median {med:.1f}) {s!r} vs en {row['en']!r}")

    # --- duplicates within a lesson per language
    for lang in LANGS:
        if lang not in ph.columns:
            continue
        for lid, g in ph.groupby("lesson_id"):
            vals = g[lang].dropna().astype(str).str.strip().str.lower()
            dup = vals[vals.duplicated()].tolist()
            if dup:
                add("duplicate-in-lesson", f"{lang} L{lid}: {dup}")

    # --- topics
    for lang in LANGS:
        col = f"topic_{lang}"
        if col not in ph.columns:
            continue
        for lid, g in ph.groupby("lesson_id"):
            vals = g[col].dropna().astype(str).str.strip().unique().tolist()
            if len(vals) != 1:
                add("topic", f"{col} L{lid}: {len(vals)} distinct values {vals[:3]}")
            elif not vals[0] or (lang not in ("en", "nl", "ca") and vals[0].lower() == str(g['topic_en'].iloc[0]).lower() and len(vals[0]) > 4):
                add("topic-untranslated", f"{col} L{lid}: {vals[0]!r}")

    # --- drills
    if DRILLS.exists():
        dr = pd.read_csv(DRILLS)
        for i, r in dr.iterrows():
            tag = f"drill row {i + 2} {r['lang']}/{r['topic_key']}"
            s = r["sentence"]
            if not isinstance(s, str) or not s.strip():
                add("drill-empty", tag)
                continue
            if META.search(s):
                add("drill-meta", f"{tag}: {s!r}")
            if s != s.strip() or "  " in s:
                add("drill-whitespace", f"{tag}: {s!r}")
        for (lang, key), g in dr.groupby(["lang", "topic_key"]):
            if len(g) != g["sentence"].nunique():
                add("drill-duplicate", f"{lang}/{key}: duplicate sentences")
            if len(g) < 6:
                add("drill-count", f"{lang}/{key}: only {len(g)} sentences")

    total = 0
    for check, msgs in sorted(findings.items()):
        print(f"\n## {check} ({len(msgs)})")
        for m in msgs[:40]:
            print("  ", m)
        if len(msgs) > 40:
            print(f"   ... +{len(msgs) - 40} more")
        total += len(msgs)
    print(f"\nTOTAL findings: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
