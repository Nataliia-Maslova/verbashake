"""Read-only integrity checks for data/vocabulary_cefrj.csv and data/reading_lessons.xlsx.

Usage: python scripts/check_vocab_reading_integrity.py
Prints findings grouped by check; changes nothing.
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "data" / "vocabulary_cefrj.csv"
READING = ROOT / "data" / "reading_lessons.xlsx"

sys.path.insert(0, str(ROOT))
from scripts.generate_vocab_from_cefrj import contains_word, is_fragment  # noqa: E402

VALID_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
META = re.compile(
    r"(\bhere is the\b|\bhere's the\b|\btranslation\b|\btranslated\b|\bnote:|"
    r"\bas an ai\b|^sure[,!]|```|\*\*)", re.I)

CYR = re.compile(r"[Ѐ-ӿ]")
HAN = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

READING_LANGS = ["en", "uk", "es", "ca", "ko", "fr", "de", "nl", "pt", "it",
                  "pl", "ru", "ja", "zh", "ro", "cs", "tr", "sv", "bg"]


def script_ok(lang: str, s: str) -> str | None:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return None
    n = len(letters)
    if lang in ("uk", "ru", "bg"):
        if len(CYR.findall(s)) / n < 0.5:
            return "expected mostly Cyrillic"
    elif lang == "ko":
        if len(HANGUL.findall(s)) / n < 0.5:
            return "expected mostly Hangul"
    elif lang == "ja":
        if (len(HAN.findall(s)) + len(KANA.findall(s))) / n < 0.5:
            return "expected mostly kana/kanji"
    elif lang == "zh":
        if len(HAN.findall(s)) / n < 0.5:
            return "expected mostly Han"
    return None


def main() -> int:
    findings: dict[str, list[str]] = defaultdict(list)

    def add(check: str, msg: str):
        findings[check].append(msg)

    # ==================== vocabulary_cefrj.csv ====================
    v = pd.read_csv(VOCAB)
    dup = v[v.duplicated(subset=["headword", "pos", "level"], keep=False)]
    if not dup.empty:
        for (hw, pos, lvl), g in dup.groupby(["headword", "pos", "level"]):
            add("vocab-duplicate", f"{hw}/{pos}/{lvl}: {len(g)} rows")

    bad_levels = v[~v.level.isin(VALID_LEVELS)]
    for _, r in bad_levels.iterrows():
        add("vocab-bad-level", f"{r.headword}: level={r.level!r}")

    for _, r in v.iterrows():
        hw, sent = r.headword, r.sentence
        tag = f"{hw}/{r.pos}/{r.level}"
        if not isinstance(sent, str) or not sent.strip():
            add("vocab-empty-sentence", tag)
            continue
        if sent != sent.strip() or "  " in sent:
            add("vocab-whitespace", f"{tag}: {sent!r}")
        if META.search(sent):
            add("vocab-meta-text", f"{tag}: {sent!r}")
        if not contains_word(sent, str(hw)):
            add("vocab-word-missing", f"{tag}: {sent!r}")
        if is_fragment(sent):
            add("vocab-fragment", f"{tag}: {sent!r}")
        if sent.strip()[-1:] not in ".?!\"'" and not sent.strip().endswith(("...", "…")):
            add("vocab-no-end-punct", f"{tag}: {sent!r}")

    dup_sent = v[v.duplicated(subset=["sentence"], keep=False) & v.sentence.notna()]
    if len(dup_sent) > 0:
        for sent, g in dup_sent.groupby("sentence"):
            if len(g) > 2:  # a couple of short natural sentences repeating is expected noise
                add("vocab-repeated-sentence", f"{sent!r}: used for {len(g)} headwords "
                                                 f"({', '.join(g.headword.head(5))}...)")

    # ==================== reading_lessons.xlsx ====================
    xl = pd.ExcelFile(READING)
    for lang in READING_LANGS:
        if lang not in xl.sheet_names:
            add("reading-missing-sheet", lang)
            continue
        df = xl.parse(lang)
        ncols = df.shape[1]
        if ncols == 5:
            df = df.iloc[:, :5]
            df.columns = ["lesson_id", "row_id", "word", "transcription", "rule"]
        elif ncols == 4:
            df = df.iloc[:, :4]
            df.columns = ["lesson_id", "row_id", "word", "transcription"]
            df["rule"] = ""
        else:
            add("reading-shape", f"{lang}: unexpected {ncols} columns")
            continue

        dup = df[df.duplicated(subset=["lesson_id", "row_id"], keep=False)]
        for (lid, rid), g in dup.groupby(["lesson_id", "row_id"]):
            add("reading-duplicate-row", f"{lang} lesson {lid} row {rid}: {len(g)}x")

        dup_word = df[df.duplicated(subset=["lesson_id", "word"], keep=False)
                      & df.word.notna() & (df.word.astype(str).str.strip() != "")]
        for (lid, w), g in dup_word.groupby(["lesson_id", "word"]):
            # same spelling + same transcription within a lesson is the suspicious case;
            # differing transcription (stress homographs, grapheme-as-word) is legitimate.
            if len(g) > 1 and g["transcription"].nunique() == 1:
                add("reading-duplicate-word-in-lesson", f"{lang} lesson {lid}: {w!r} x{len(g)}")

        for _, r in df.iterrows():
            tag = f"{lang} L{r.lesson_id}/row{r.row_id}"
            w = r.word
            if not isinstance(w, str) or not w.strip() or w.strip().lower() == "nan":
                add("reading-empty-word", tag)
                continue
            if w != w.strip():
                add("reading-whitespace", f"{tag}: word {w!r}")
            tr = r.transcription
            if isinstance(tr, str) and tr.strip() and tr.strip().lower() != "nan":
                if tr != tr.strip():
                    add("reading-whitespace", f"{tag}: transcription {tr!r}")
            rule = r.get("rule")
            if isinstance(rule, str) and rule.strip() and rule.strip().lower() != "nan":
                if META.search(rule):
                    add("reading-meta-text", f"{tag}: rule {rule!r}")
                if lang != "en" and META.search(rule) is None and re.search(r"[a-zA-Z]{15,}", rule) and lang in ("ja", "zh", "ko"):
                    pass  # rule explanations are in English by design for all languages; skip
            core = re.sub(r"\([^)]*\)", "", w).strip()  # strip English annotations like "(before K)"
            if lang not in ("en",) and len(core) >= 3:
                bad = script_ok(lang, core)
                if bad:
                    add("reading-script", f"{tag}: {bad}: {w!r}")

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
