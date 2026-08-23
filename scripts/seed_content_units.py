"""
scripts/seed_content_units.py — one-time (re-runnable) population of content_units.

Usage:
    python scripts/seed_content_units.py --generate-templates
        Writes data/vocab_tags_template.csv and data/reading_tags_template.csv
        for manual tagging (level + topic) — vocab has no level today, reading
        has neither level nor topic. Fill these in, then run again without the
        flag.

    python scripts/seed_content_units.py
        Seeds content_units from the source Excel files:
          - grammar: auto-tagged from imlls_database_with_titles.xlsx
            ("lessons" sheet: topic_en + difficulty, mapped onto a CEFR scale).
          - vocab / reading: level+topic pulled from the *_tags_template.csv
            files if present (untagged rows are seeded with level=NULL,
            topic=<sheet name> for vocab / topic=NULL for reading — the
            recommender treats a missing level as mid-scale, so nothing
            breaks before tagging, candidates are just less well-targeted).

    Requires DATABASE_URL in .streamlit/secrets.toml or env (see engine/db.py)
    and schema.sql already applied to the database.

Reading is scoped to the 4 languages the app actively supports (English,
Ukrainian, Spanish, Korean) — extend READING_LANGS below if more are needed.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine import db
from engine.recommender import DIFFICULTY_TO_CEFR

DATA_DIR = Path(__file__).parent.parent / "data"

READING_LANGS = ["en", "uk", "es", "ko"]


def _load_tags_template(path: Path, key_cols: list[str]) -> dict[tuple, dict]:
    """Read a filled-in template CSV into {key_tuple: {"level": ..., "topic": ...}}."""
    if not path.exists():
        return {}
    out: dict[tuple, dict] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = tuple(row[c] for c in key_cols)
            out[key] = {"level": row.get("level") or None, "topic": row.get("topic") or None}
    return out


# ── Template generation ─────────────────────────────────────────────────────

def generate_vocab_template() -> None:
    xl = pd.ExcelFile(DATA_DIR / "vocabulary_translated.xlsx", engine="openpyxl")
    rows = [{"sheet": sheet, "level": "", "topic": sheet} for sheet in xl.sheet_names]
    out = DATA_DIR / "vocab_tags_template.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sheet", "level", "topic"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out} ({len(rows)} topic sheets). Fill in 'level' (A1..C2) per row; "
          f"'topic' defaults to the sheet name, edit if you want a cleaner label.")


def generate_reading_template() -> None:
    xl = pd.ExcelFile(DATA_DIR / "reading_lessons.xlsx", engine="openpyxl")
    rows = []
    for lang in READING_LANGS:
        if lang not in xl.sheet_names:
            continue
        df = xl.parse(lang)
        for n in sorted(df["#"].dropna().unique().tolist()):
            rows.append({"lang_code": lang, "lesson_number": int(n), "level": "", "topic": ""})
    out = DATA_DIR / "reading_tags_template.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lang_code", "lesson_number", "level", "topic"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out} ({len(rows)} lessons across {READING_LANGS}). "
          f"Fill in 'level' (A1..C2) and 'topic' per row.")


# ── Seeding ──────────────────────────────────────────────────────────────────

def seed_grammar() -> list[dict]:
    df = pd.read_excel(DATA_DIR / "imlls_database_with_titles.xlsx", sheet_name="lessons", engine="openpyxl")
    units = []
    for _, row in df.iterrows():
        lid = row.get("lesson_id")
        if pd.isna(lid):
            continue
        lid = int(lid)
        difficulty = int(row.get("difficulty", 1))
        units.append({
            "unit_id":       f"grammar:{lid}",
            "module":        "grammar",
            "source_lesson": str(lid),
            "source_item":   None,
            "level":         DIFFICULTY_TO_CEFR.get(difficulty),
            "topic":         str(row.get("topic_en", "")) or None,
        })
    return units


def seed_vocab() -> list[dict]:
    """
    IMPORTANT: vocab lessons are keyed by a *global* lesson_id assigned by
    engine.vocab_loader._build_global_index() (workbook sheet order, then
    local lesson_id within each sheet) — NOT the raw per-sheet lesson_id
    column in the Excel file. grammar.py/picker.py address vocab lessons by
    this global id (get_topic_for_lesson, get_lesson, next_id=...), so unit_id
    must be built from the same index or it won't line up with what the app
    actually launches.
    """
    """
    Splits into two modules by sheet (CLAUDE.md, 2026-08-21): the "Word
    Bank" sheets (engine.vocab_loader.WORD_BANK_SHEETS -- Basic/Verbs/Food/
    City, alphabetically-bucketed raw word lists, being replaced by a
    CEFR-J-based Vocabulary module) keep unit_id prefix/module "vocab";
    everything else (thematic collocations + example sentences) becomes
    module "phrasebook" with its own unit_id prefix -- NOT aliased to
    "vocab:..." even though it's the same workbook/gids, because
    engine.recommender.parse_unit_id() treats the unit_id's own prefix as
    the authoritative module, so the two must actually match.
    """
    tags = _load_tags_template(DATA_DIR / "vocab_tags_template.csv", ["sheet"])
    from engine.vocab_loader import _build_global_index, WORD_BANK_SHEETS
    gid_to_meta, _ = _build_global_index(str(DATA_DIR / "vocabulary_translated.xlsx"))
    units = []
    for gid, meta in gid_to_meta.items():
        sheet = meta["topic"]
        tag = tags.get((sheet,), {})
        module = "vocab" if sheet in WORD_BANK_SHEETS else "phrasebook"
        units.append({
            "unit_id":       f"{module}:{sheet}:{gid}",
            "module":        module,
            "source_lesson": sheet,
            "source_item":   str(meta["local_lesson"]),
            "level":         tag.get("level"),
            "topic":         tag.get("topic") or sheet,
        })
    return units


def seed_cefrj_vocab() -> list[dict]:
    """
    CEFR-J Vocabulary content (CLAUDE.md, 2026-08-21/22, extended
    2026-08-22 — replaces the old Word Bank sheets as the "Vocabulary"
    source for every target_lang, not just English; see
    engine.cefr_j_vocab_loader / engine.session._fill_missing_translations
    for the on-demand per-lesson translation). Shares module='vocab' with
    the Word Bank rows from seed_vocab() -- unit_id's "A1".."C2" segment
    can never collide with a Word Bank sheet name, so both coexist fine
    under the same module (engine.recommender._candidates() excludes the
    Word Bank ones unconditionally now that CEFR-J covers every language).

    source_lesson='cefrj' -- deliberately NOT a real language code, so
    engine.recommender._candidates()'s target_lang filter treats these
    rows as language-agnostic (same "NOT IN real_codes" branch
    grammar/phrasebook rows already use), unlike "reading" which stays
    locked to one real language per row since the passages themselves
    differ per language.

    topic=level (e.g. "A1") rather than a real theme: CEFR-J has no
    thematic grouping, level is the only real category, and using it as the
    topic keeps mastery scored per-level like every other module's topic
    scoring, not lumped into one giant "vocabulary" bucket.
    """
    from engine.cefr_j_vocab_loader import _build_index, CSV_PATH

    df = _build_index(str(CSV_PATH))
    lessons = df.drop_duplicates("lesson_id")[["lesson_id", "level", "local_lesson"]]
    units = []
    for _, row in lessons.iterrows():
        lid = int(row["lesson_id"])
        units.append({
            "unit_id":       f"vocab:{row['level']}:{lid}",
            "module":        "vocab",
            "source_lesson": "cefrj",
            "source_item":   str(int(row["local_lesson"])),
            "level":         row["level"],
            "topic":         row["level"],
        })
    return units


def seed_reading() -> list[dict]:
    tags = _load_tags_template(DATA_DIR / "reading_tags_template.csv", ["lang_code", "lesson_number"])
    xl = pd.ExcelFile(DATA_DIR / "reading_lessons.xlsx", engine="openpyxl")
    units = []
    for lang in READING_LANGS:
        if lang not in xl.sheet_names:
            continue
        df = xl.parse(lang)
        for n in sorted(df["#"].dropna().unique().tolist()):
            n = int(n)
            tag = tags.get((lang, str(n)), {})
            units.append({
                "unit_id":       f"reading:{lang}:{n}",
                "module":        "reading",
                "source_lesson": lang,
                "source_item":   None,
                "level":         tag.get("level"),
                "topic":         tag.get("topic"),
            })
    return units


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-templates", action="store_true")
    args = parser.parse_args()

    if args.generate_templates:
        generate_vocab_template()
        generate_reading_template()
        return

    all_units = seed_grammar() + seed_vocab() + seed_cefrj_vocab() + seed_reading()

    # 2026-08-21: the vocab/phrasebook split changed unit_id prefixes for the
    # 25 non-Word-Bank sheets ("vocab:Hobbies:474" -> "phrasebook:Hobbies:474")
    # -- upsert alone would leave the old "vocab:..." rows for those sheets
    # behind as orphans. content_units is a content catalog, not user state
    # (mastery/srs_state/lesson_pointer are separate tables), so a full clear
    # + reseed is safe and simplest.
    db.execute("DELETE FROM content_units")

    # Batched, chunked upsert. The original per-row db.upsert() loop opened a
    # fresh connection per row (~1700 units) and reliably got killed by
    # Supabase's pooler partway through (died at unit ~163, then ~28 on
    # retry). A single execute_many() over one connection for ALL units also
    # got its connection closed mid-statement -- so the constraint seems to
    # be duration/size of one round trip, not connection count. Chunking to
    # 100 rows/call (each fast enough to finish) + a couple of retries on
    # transient OperationalError is the pragmatic fix -- upsert is naturally
    # idempotent, so a retried chunk just re-applies the same rows.
    import time
    from sqlalchemy.exc import OperationalError

    cols = list(all_units[0].keys())
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "unit_id")
    sql = (
        f"INSERT INTO content_units ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (unit_id) DO UPDATE SET {update_set}, updated_at = now()"
    )

    CHUNK = 50
    failed_chunks = []
    for i in range(0, len(all_units), CHUNK):
        chunk = all_units[i:i + CHUNK]
        for attempt in range(5):
            try:
                db.execute_many(sql, chunk)
                break
            except OperationalError as e:
                if attempt == 4:
                    print(f"  chunk {i}-{i+len(chunk)} FAILED after 5 attempts ({e.__class__.__name__}) -- will retry at the end")
                    failed_chunks.append((i, chunk))
                    break
                time.sleep(2 * (attempt + 1))
        print(f"  seeded {min(i + CHUNK, len(all_units))}/{len(all_units)}")

    # Second pass over anything that never made it through, now that whatever
    # transient network issue was happening has had more time to settle.
    if failed_chunks:
        print(f"Retrying {len(failed_chunks)} failed chunk(s)...")
        still_failed = []
        for i, chunk in failed_chunks:
            for attempt in range(5):
                try:
                    db.execute_many(sql, chunk)
                    print(f"  chunk {i}-{i+len(chunk)} succeeded on retry")
                    break
                except OperationalError:
                    if attempt == 4:
                        still_failed.append((i, chunk))
                    time.sleep(3 * (attempt + 1))
        if still_failed:
            missing = sum(len(c) for _, c in still_failed)
            print(f"WARNING: {missing} units still not seeded after all retries "
                  f"(chunks starting at: {[i for i, _ in still_failed]}) -- "
                  f"re-run this script (upsert is idempotent, safe to repeat).")

    print(f"Seeded {len(all_units)} content_units "
          f"(grammar={sum(1 for u in all_units if u['module']=='grammar')}, "
          f"vocab={sum(1 for u in all_units if u['module']=='vocab')}, "
          f"phrasebook={sum(1 for u in all_units if u['module']=='phrasebook')}, "
          f"reading={sum(1 for u in all_units if u['module']=='reading')}).")


if __name__ == "__main__":
    main()
