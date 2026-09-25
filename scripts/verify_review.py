"""Second-stage filter for data/review/translation_review.jsonl.

1) drops no-op findings (fix == current). 2) asks an independent Gemini call, framed as an A/B judgement
(without showing the reviewer's reasoning), whether the CURRENT translation has a definite error and whether the
PROPOSED one is correct. Writes data/review/verified.jsonl with only findings both stages agree on.
"""
import json, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import gemini  # noqa: E402
from scripts.review_translations import NAMES  # noqa: E402

IN = ROOT / "data" / "review" / "translation_review.jsonl"
OUT = ROOT / "data" / "review" / "verified.jsonl"


def norm(s): return re.sub(r"\W+", "", unicodedata.normalize("NFC", s or "")).lower()


def judge(job):
    lang, items = job
    lines = "\n".join(f"{k}. EN: {f['en']}\n   A (current): {f['current']}\n   B (proposed): {f['fix']}" for k, f in enumerate(items))
    prompt = (f"You are a strict native {NAMES[lang]} linguist. For each item decide independently (ignore who proposed what):\n"
              f"- current_wrong: true ONLY if A contains a definite error (wrong/changed meaning, missing or extra content, grammar/"
              f"agreement/gender/spelling error, or unnatural {NAMES[lang]} a native would reject). A is fine if merely less formal, shorter, or different in style.\n"
              f"- proposed_ok: true if B is fully correct, natural {NAMES[lang]}, and keeps the meaning of the English.\n\n{lines}\n\n"
              'Return JSON only: an array of {"i": n, "current_wrong": bool, "proposed_ok": bool}.')
    try:
        res = gemini._parse_json(gemini._model(gemini._FLASH).generate_content(prompt).text, fallback=None)
    except Exception:
        return []
    out = []
    if isinstance(res, list):
        for r in res:
            if isinstance(r, dict) and isinstance(r.get("i"), int) and 0 <= r["i"] < len(items):
                out.append({**items[r["i"]], "current_wrong": bool(r.get("current_wrong")), "proposed_ok": bool(r.get("proposed_ok"))})
    return out


def main():
    F = []
    for line in IN.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for f in r.get("findings", []):
            if norm(f["fix"]) != norm(f["current"]) and (f.get("confidence") or 0) >= 0.8 and "(or:" not in f["fix"]:
                F.append({**f, "lang": r["lang"], "lesson": r["lesson"]})
    print("after no-op/confidence filter:", len(F), flush=True)
    jobs = []
    for lang in NAMES:
        items = [f for f in F if f["lang"] == lang]
        for i in range(0, len(items), 8): jobs.append((lang, items[i:i + 8]))
    with ThreadPoolExecutor(10) as ex: results = [x for res in ex.map(judge, jobs) for x in res]
    ok = [r for r in results if r["current_wrong"] and r["proposed_ok"]]
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ok), encoding="utf-8")
    print(f"judged {len(results)}, agreed {len(ok)}", flush=True)

if __name__ == "__main__":
    main()
