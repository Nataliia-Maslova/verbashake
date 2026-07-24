"""
engine/curriculum.py — Structured learning path for IMLLS.

Generates an ordered sequence of learning units (reading → grammar + vocabulary,
interleaved by stage) and persists per-user progress to a JSON file.

Unit structure:
    {
        "type":       "reading" | "grammar" | "vocabulary",
        "stage":      int,          # 0-6
        "lesson_id":  int,          # lesson number within the module
        "sheet":      str | None,   # vocab sheet name (type="vocabulary" only)
        "topic_en":   str,          # human-readable English label
        "difficulty": int | None,   # grammar difficulty
        "lang_code":  str | None,   # language code for reading lessons
    }

Progress file: logs/curriculum_{user_id}_{lang_code}.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Language mapping ─────────────────────────────────────────────────────────

LANG_TO_CODE: Dict[str, str] = {
    "English":    "en",
    "Ukrainian":  "uk",
    "Spanish":    "es",
    "Korean":     "ko",
    "French":     "fr",
    "German":     "de",
    "Japanese":   "ja",
    "Chinese":    "zh",
    "Portuguese": "pt",
    "Italian":    "it",
    "Polish":     "pl",
    "Russian":    "ru",
}

# Total reading lessons per language code
READING_TOTAL: Dict[str, int] = {
    "en": 80,
    "uk": 65,
    "es": 53,
    "ko": 75,
    "fr": 30,
    "de": 28,
    "pt": 30,
    "it": 30,
    "pl": 30,
    "ru": 30,
    "ja": 30,
    "zh": 30,
}

# ── Stage definitions ────────────────────────────────────────────────────────

# Grammar lesson ranges per stage (1-indexed, inclusive)
GRAMMAR_STAGES: Dict[int, Tuple[int, int]] = {
    1: (1,   10),
    2: (11,  35),
    3: (36,  69),
    4: (70,  113),
    5: (114, 138),
    6: (139, 173),
}

# Vocab modules per stage — (sheet_name, start_lesson_id, end_lesson_id)
# None means "all lessons in that sheet"
VOCAB_STAGES: Dict[int, List[Tuple[str, Optional[int], Optional[int]]]] = {
    1: [
        ("Greetings, Basics & Courtesy",     None, None),
        ("Questions, Directions & Emergen",   None, None),
        ("Daily Life, Routine & Feelings",    None, None),
        ("Basic",                             1,    28),    # beginner words 1
    ],
    2: [
        ("Daily Routine",                     None, None),
        ("Food and Drinks",                   None, None),
        ("Restaurant, Food & Shopping",       None, None),
        ("Transport",                         None, None),
        ("Basic",                             29,   56),    # beginner words 2
    ],
    3: [
        ("Shopping",                          None, None),
        ("Travel, Lodging & Weather",         None, None),
        ("Travel",                            None, None),
        ("Emotions",                          None, None),
        ("Clothes",                           None, None),
        ("Basic",                             57,   84),    # beginner words 3
    ],
    4: [
        ("Work",                              None, None),
        ("School",                            None, None),
        ("Friends and Relationships",         None, None),
        ("Family",                            None, None),
        ("House and Home",                    None, None),
        ("City and Directions",               None, None),
    ],
    5: [
        ("Technology",                        None, None),
        ("Holidays",                          None, None),
        ("Sports",                            None, None),
        ("At the Doctor",                     None, None),
        ("Weather",                           None, None),
    ],
    6: [
        ("Hobbies",                           None, None),
        ("Restaurant",                        None, None),
        ("City",                              None, None),
        ("Verbs",                             None, None),  # 116 lessons
        ("Food",                              None, None),  # 139 lessons
    ],
}

# After how many grammar lessons to insert a vocab module within a stage
_GRAMMAR_PER_VOCAB = 3

# ── Module-level caches ──────────────────────────────────────────────────────

_VOCAB_CACHE: Optional[Dict[str, List[int]]] = None
_GRAMMAR_CACHE: Optional[List[Dict[str, Any]]] = None


def _vocab_lesson_ids() -> Dict[str, List[int]]:
    """Load vocab lesson IDs from Excel, cached in module-level dict."""
    global _VOCAB_CACHE
    if _VOCAB_CACHE is not None:
        return _VOCAB_CACHE
    try:
        import pandas as pd
        db = Path(__file__).parent.parent / "data" / "vocabulary_translated.xlsx"
        xl = pd.ExcelFile(str(db), engine="openpyxl")
        cache: Dict[str, List[int]] = {}
        for sheet in xl.sheet_names:
            df = xl.parse(sheet, usecols=[0], header=0)
            ids = sorted(df.iloc[:, 0].dropna().astype(int).unique().tolist())
            cache[sheet] = ids
        _VOCAB_CACHE = cache
    except Exception:
        _VOCAB_CACHE = {}
    return _VOCAB_CACHE


def _grammar_lessons() -> List[Dict[str, Any]]:
    """Load grammar lessons from imlls_database_with_titles.xlsx, cached."""
    global _GRAMMAR_CACHE
    if _GRAMMAR_CACHE is not None:
        return _GRAMMAR_CACHE
    try:
        import pandas as pd
        db = Path(__file__).parent.parent / "data" / "imlls_database_with_titles.xlsx"
        df = pd.read_excel(str(db), sheet_name="lessons", engine="openpyxl")
        lessons: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            lid = row.get("lesson_id")
            if lid is None or (isinstance(lid, float) and lid != lid):
                continue
            lessons.append({
                "lesson_id":  int(lid),
                "difficulty": int(row.get("difficulty", 1)),
                "topic_en":   str(row.get("topic_en", "")),
            })
        lessons.sort(key=lambda x: x["lesson_id"])
        _GRAMMAR_CACHE = lessons
    except Exception:
        _GRAMMAR_CACHE = []
    return _GRAMMAR_CACHE


# ── Path builder ─────────────────────────────────────────────────────────────

def build_path(target_lang: str) -> List[Dict[str, Any]]:
    """
    Build the full ordered list of learning units for `target_lang`.

    Stage 0:   10 reading lessons (alphabet, basic sounds)
    Stage 1-6: Grammar (sequential) interleaved with vocab modules.
               After every _GRAMMAR_PER_VOCAB grammar lessons → insert next vocab module.
               5 more reading lessons appended after each stage.
    Tail:      Any remaining reading lessons.
    """
    lang_code     = LANG_TO_CODE.get(target_lang, "en")
    total_reading = READING_TOTAL.get(lang_code, 30)

    grammar = _grammar_lessons()
    vocab   = _vocab_lesson_ids()

    units: List[Dict[str, Any]] = []

    # ── Stage 0: first 10 reading lessons ───────────────────────────────────
    stage0_count = min(10, total_reading)
    for lid in range(1, stage0_count + 1):
        units.append(_reading_unit(lid, lang_code, stage=0))
    reading_done = stage0_count

    # ── Stages 1-6 ──────────────────────────────────────────────────────────
    for stage in range(1, 7):
        g_start, g_end = GRAMMAR_STAGES[stage]
        stage_grammar  = [g for g in grammar if g_start <= g["lesson_id"] <= g_end]
        vocab_defs     = list(VOCAB_STAGES.get(stage, []))  # [(sheet, lo, hi), ...]

        # Build a flat list of vocab lesson specs for this stage
        vocab_queue: List[Tuple[str, List[int]]] = []
        for sheet, lo, hi in vocab_defs:
            all_ids = vocab.get(sheet, [])
            if lo is None and hi is None:
                ids = all_ids
            else:
                lo_ = lo or 0
                hi_ = hi or 9999
                ids = [i for i in all_ids if lo_ <= i <= hi_]
            if ids:
                vocab_queue.append((sheet, ids))

        # Interleave: grammar in blocks of _GRAMMAR_PER_VOCAB, then vocab module
        g_count   = 0
        vocab_idx = 0

        for g in stage_grammar:
            units.append({
                "type":       "grammar",
                "stage":      stage,
                "lesson_id":  g["lesson_id"],
                "sheet":      None,
                "topic_en":   g["topic_en"],
                "difficulty": g["difficulty"],
                "lang_code":  None,
            })
            g_count += 1

            if g_count % _GRAMMAR_PER_VOCAB == 0 and vocab_idx < len(vocab_queue):
                sheet, ids = vocab_queue[vocab_idx]
                vocab_idx += 1
                for vlid in ids:
                    units.append(_vocab_unit(vlid, sheet, stage))

        # Flush remaining vocab modules for this stage
        while vocab_idx < len(vocab_queue):
            sheet, ids = vocab_queue[vocab_idx]
            vocab_idx += 1
            for vlid in ids:
                units.append(_vocab_unit(vlid, sheet, stage))

        # 5 reading lessons after each stage
        batch = min(5, total_reading - reading_done)
        for i in range(batch):
            units.append(_reading_unit(reading_done + i + 1, lang_code, stage))
        reading_done += batch

    # ── Tail: remaining reading lessons ─────────────────────────────────────
    for lid in range(reading_done + 1, total_reading + 1):
        units.append(_reading_unit(lid, lang_code, stage=6))

    return units


def _reading_unit(lesson_id: int, lang_code: str, stage: int) -> Dict[str, Any]:
    return {
        "type":       "reading",
        "stage":      stage,
        "lesson_id":  lesson_id,
        "sheet":      None,
        "topic_en":   f"Reading lesson {lesson_id}",
        "difficulty": None,
        "lang_code":  lang_code,
    }


def _vocab_unit(lesson_id: int, sheet: str, stage: int) -> Dict[str, Any]:
    return {
        "type":       "vocabulary",
        "stage":      stage,
        "lesson_id":  lesson_id,
        "sheet":      sheet,
        "topic_en":   sheet,
        "difficulty": None,
        "lang_code":  None,
    }


# ── Progress persistence ─────────────────────────────────────────────────────

def _progress_path(user_id: str, target_lang: str) -> Path:
    lang_code = LANG_TO_CODE.get(target_lang, target_lang.lower()[:2])
    logs_dir  = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    safe = "".join(c for c in user_id if c.isalnum() or c in "_-")[:32] or "user"
    return logs_dir / f"curriculum_{safe}_{lang_code}.json"


def load_progress(user_id: str, target_lang: str) -> Dict[str, Any]:
    """Load progress dict; returns defaults if file not found."""
    defaults: Dict[str, Any] = {
        "current_index": 0,
        "target_lang":   target_lang,
        "total_units":   0,
        "last_date":     None,
    }
    try:
        p = _progress_path(user_id, target_lang)
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            defaults.update(saved)
    except Exception:
        pass
    return defaults


def save_progress(user_id: str, target_lang: str, progress: Dict[str, Any]) -> None:
    try:
        p = _progress_path(user_id, target_lang)
        p.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def advance(user_id: str, target_lang: str) -> None:
    """Mark current unit done, increment index, save."""
    from datetime import date
    prog  = load_progress(user_id, target_lang)
    path  = build_path(target_lang)
    idx   = prog.get("current_index", 0)
    prog["current_index"] = min(idx + 1, len(path))
    prog["total_units"]   = len(path)
    prog["last_date"]     = str(date.today())
    save_progress(user_id, target_lang, prog)


def reset_progress(user_id: str, target_lang: str) -> None:
    save_progress(user_id, target_lang, {
        "current_index": 0,
        "target_lang":   target_lang,
        "total_units":   0,
        "last_date":     None,
    })


# ── Stats ────────────────────────────────────────────────────────────────────

def get_stats(user_id: str, target_lang: str) -> Dict[str, Any]:
    """Return summary stats for the path page (current unit, counts, upcoming)."""
    prog  = load_progress(user_id, target_lang)
    path  = build_path(target_lang)
    idx   = int(prog.get("current_index", 0))
    total = len(path)

    current_unit  = path[idx] if idx < total else None
    current_stage = current_unit["stage"] if current_unit else 6

    done_g = sum(1 for u in path[:idx] if u["type"] == "grammar")
    done_v = sum(1 for u in path[:idx] if u["type"] == "vocabulary")
    done_r = sum(1 for u in path[:idx] if u["type"] == "reading")

    tot_g = sum(1 for u in path if u["type"] == "grammar")
    tot_v = sum(1 for u in path if u["type"] == "vocabulary")
    tot_r = sum(1 for u in path if u["type"] == "reading")

    return {
        "current_index": idx,
        "total":         total,
        "pct":           round(idx / total * 100, 1) if total > 0 else 0.0,
        "current_unit":  current_unit,
        "current_stage": current_stage,
        "done_grammar":  done_g,
        "done_vocab":    done_v,
        "done_reading":  done_r,
        "total_grammar": tot_g,
        "total_vocab":   tot_v,
        "total_reading": tot_r,
        "last_date":     prog.get("last_date"),
        "upcoming":      path[idx: idx + 6],  # current + next 5
    }
