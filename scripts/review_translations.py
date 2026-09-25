"""Second-model review of data/imlls_database_with_titles.xlsx translations.

For every (lesson, language) pair one Gemini call sees the 8 English phrases
plus that language's 8 translations and reports ONLY clear problems (wrong or
missing meaning, dropped answer half, untranslated words, grammar/gender/case
errors, unnatural phrasing). Read-only w.r.t. the workbook: findings go to
data/review/translation_review.jsonl (resumable -- pairs already present are
skipped) and are applied by hand/other script after human-style triage.

Usage: python scripts/review_translations.py [--langs de,fr] [--lessons 1-30] [--workers 8]
"""
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import gemini  # noqa: E402

DB = ROOT / "data" / "imlls_database_with_titles.xlsx"
OUT = ROOT / "data" / "review" / "translation_review.jsonl"
LANGS = ["uk","es","ko","fr","de","ja","zh","pt","it","pl","ru","ca","nl","ro","bg","cs","tr","sv"]
NAMES = {"uk":"Ukrainian","es":"Spanish","ko":"Korean","fr":"French","de":"German","ja":"Japanese","zh":"Chinese (Simplified)",
         "pt":"Portuguese (Brazil)","it":"Italian","pl":"Polish","ru":"Russian","ca":"Catalan","nl":"Dutch","ro":"Romanian",
         "bg":"Bulgarian","cs":"Czech","tr":"Turkish","sv":"Swedish"}
# verb-form list lessons are being rebuilt per language (see CLAUDE.md), skip them here
SKIP_LESSONS = {114,116,118,120,122,124,126,128,130,143,148,149,150,151,152,153,154,155}


def prompt_for(lang, rows):
    lines = "\n".join(f"{i}. EN: {en}\n   {lang.upper()}: {tr}" for i, (en, tr) in enumerate(rows))
    return (
        f"You are a meticulous native-level reviewer of {NAMES[lang]} language-learning material. Below are English source "
        f"phrases and their {NAMES[lang]} translations, used as practice sentences for learners.\n"
        f"Report ONLY definite ERRORS. A translation that is grammatical, natural and conveys the English meaning is CORRECT and "
        f"must NOT be reported -- even if a longer, more formal or more literal wording exists. Short answers such as 'Ja.', "
        f"'Sí.', 'Nein.' after a question are fine. Never report style preferences, synonyms, or 'could be more complete'.\n"
        f"Definite errors are only: (a) meaning is wrong or changed; (b) a part of the English is missing or extra content was "
        f"added; (c) English words left untranslated (except brand names/loanwords normal in {NAMES[lang]}); (d) a real "
        f"grammar, gender, case, agreement, spelling or word-choice error; (e) sentence that a native speaker would call "
        f"wrong or clearly unnatural. When unsure, do NOT report.\n\n{lines}\n\n"
        "Return JSON only, no markdown: an array (usually empty) of objects "
        '{"i": <number>, "issue": "<one short sentence in English>", "fix": "<the corrected '
        f'{NAMES[lang]} translation, minimal change>", "confidence": <0.0-1.0>}}. Empty array [] if there are no definite errors.'
    )


def review(job):
    lid, lang, rows, pids = job
    try:
        h = gemini._model(gemini._FLASH)
        txt = h.generate_content(prompt_for(lang, rows)).text
        res = gemini._parse_json(txt, fallback=None)
        if not isinstance(res, list):
            return {"lesson": lid, "lang": lang, "error": "unparseable"}
        items = []
        for r in res:
            if isinstance(r, dict) and isinstance(r.get("i"), int) and 0 <= r["i"] < len(rows):
                items.append({"phrase_id": int(pids[r["i"]]), "en": rows[r["i"]][0], "current": rows[r["i"]][1],
                              "issue": r.get("issue", ""), "fix": r.get("fix", ""), "confidence": r.get("confidence")})
        return {"lesson": lid, "lang": lang, "findings": items}
    except Exception as e:  # noqa: BLE001
        return {"lesson": lid, "lang": lang, "error": repr(e)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default=",".join(LANGS)); ap.add_argument("--lessons", default="1-182")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.lessons.split("-"))
    df = pd.read_excel(DB, sheet_name="phrases")
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if "error" not in r: done.add((r["lesson"], r["lang"]))
    jobs = []
    for lid, g in df.groupby("lesson_id"):
        if not lo <= lid <= hi or lid in SKIP_LESSONS: continue
        for lang in a.langs.split(","):
            if (int(lid), lang) in done: continue
            rows = [(str(r["en"]), str(r[lang])) for _, r in g.iterrows()]
            jobs.append((int(lid), lang, rows, list(g["phrase_id"])))
    print(f"{len(jobs)} jobs", flush=True)
    OUT.parent.mkdir(exist_ok=True)
    n = bad = 0
    with ThreadPoolExecutor(a.workers) as ex, OUT.open("a", encoding="utf-8") as f:
        for res in ex.map(review, jobs):
            f.write(json.dumps(res, ensure_ascii=False) + "\n"); f.flush(); n += 1
            bad += len(res.get("findings", []))
            if n % 100 == 0: print(f"{n}/{len(jobs)} done, {bad} findings so far", flush=True)
    print(f"finished: {n} jobs, {bad} findings", flush=True)


if __name__ == "__main__":
    main()
