"""Read-only integrity checks for data/vocabulary_translated.xlsx (Phrasebook sheets + Word Bank).

Usage: python scripts/check_phrasebook_integrity.py
Reuses the script/meta-text heuristics of check_data_integrity.py.
"""
import re, sys
from collections import defaultdict
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.check_data_integrity import script_ok, META  # noqa: E402

LANGS = ["en","uk","es","ko","fr","de","ja","zh","pt","it","pl","ru","ca","nl","ro","bg","cs","tr","sv"]
WORD_BANK = {"Basic", "Verbs", "Food", "City"}


def main() -> int:
    f = defaultdict(list)
    xl = pd.ExcelFile(ROOT / "data" / "vocabulary_translated.xlsx")
    for sheet in xl.sheet_names:
        if sheet in WORD_BANK:
            continue  # legacy Word Bank, replaced by CEFR-J, not loaded by Phrasebook
        d = xl.parse(sheet)
        for lang in LANGS:
            if lang not in d.columns:
                f["missing-column"].append(f"{sheet}: {lang}")
        if d["phrase_id"].duplicated().any():
            f["dup-phrase-id"].append(sheet)
        for _, r in d.iterrows():
            en = r.get("en")
            if not isinstance(en, str) or not en.strip():
                if any(isinstance(r.get(l), str) and r.get(l).strip() for l in LANGS):
                    f["empty-en-but-others-filled"].append(f"{sheet} p{r.get('phrase_id')}")
                continue
            for lang in LANGS:
                if lang not in d.columns:
                    continue
                s = r[lang]
                tag = f"{sheet} p{r.get('phrase_id')} {lang}"
                if not isinstance(s, str) or not s.strip():
                    f["empty"].append(tag); continue
                if s != s.strip() or "  " in s:
                    f["whitespace"].append(f"{tag}: {s!r}")
                if lang == "en":
                    continue
                if META.search(s):
                    f["meta-text"].append(f"{tag}: {s!r}")
                bad = script_ok(lang, s)
                if bad:
                    f["script"].append(f"{tag}: {bad}: {s!r}")
                if s.strip().lower() == en.strip().lower() and len(en) > 4 and lang not in ("nl","ca"):
                    f["untranslated"].append(f"{tag}: {s!r}")
                if re.search(r"[A-Za-z]{4,}", s) and lang in ("uk","ru","bg","ko","ja","zh"):
                    f["latin-in-nonlatin"].append(f"{tag}: {s!r}")
                ratio = len(s) / max(len(en), 1)
                if len(en) > 15 and (ratio > 3.5 or ratio < 0.25) and lang not in ("ja","zh","ko"):
                    f["length-outlier"].append(f"{tag}: en={en!r} -> {s!r}")
    total = 0
    for k, v in sorted(f.items()):
        print(f"\n## {k} ({len(v)})")
        for m in v[:40]: print("  ", m)
        if len(v) > 40: print(f"   ... +{len(v)-40} more")
        total += len(v)
    print(f"\nTOTAL findings: {total}")
    return 1 if total else 0

if __name__ == "__main__":
    sys.exit(main())
