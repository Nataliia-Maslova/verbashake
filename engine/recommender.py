"""
engine/recommender.py — replaces engine/curriculum.py + engine/adaptive.py.

Decides which lesson to show next across ALL modules (grammar / vocab / reading)
by scoring every candidate lesson in content_units:

    score = W_SRS * srs_urgency + W_MASTERY * mastery_gap + W_NOVELTY * novelty_bonus

  srs_urgency   — how overdue the lesson's spaced-repetition review is (0 if
                  not due yet, small constant if never attempted).
  mastery_gap   — 1 - the user's running mastery score for that lesson's topic
                  (weaker topics score higher).
  novelty_bonus — peaks when the lesson's level sits slightly above the user's
                  current mastery for that topic (~80%-success sweet spot).

V1 is a transparent heuristic, not a trained model — see CLAUDE.md decision #4.
Requires the content_units/mastery/srs_state/lesson_pointer tables from schema.sql
and a DATABASE_URL (see engine/db.py).
"""
from __future__ import annotations

from datetime import date, timedelta

from engine import db

# Re-exported so callers that used to import this from engine.curriculum don't
# need a second import.
LANG_TO_CODE: dict[str, str] = {
    "English": "en", "Ukrainian": "uk", "Spanish": "es", "Korean": "ko",
    "French": "fr", "German": "de", "Japanese": "ja", "Chinese": "zh",
    "Portuguese": "pt", "Italian": "it", "Polish": "pl", "Russian": "ru",
    "Catalan": "ca", "Dutch": "nl",
}

CODE_TO_LANG: dict[str, str] = {v: k for k, v in LANG_TO_CODE.items()}

CEFR_RANK: dict[str, int] = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

# Every module content_units can hold (schema.sql's CHECK constraint) — the
# canonical list for anything that needs to touch "all modules" at once,
# e.g. seeding placement-quiz mastery across the whole cross-module My Path,
# not just the one module the quiz happened to test.
ALL_MODULES: tuple[str, ...] = ("grammar", "vocab", "reading", "phrasebook", "target_grammar")

# imlls_database's "phrases"/"lessons" sheets tag every grammar lesson with a
# difficulty column, not a CEFR string — this is the single source of truth
# for turning that into a level, used both by scripts/seed_content_units.py
# (content_units seeding) and grammar.py::_lesson_level (Phase 1/3/4/5 level
# lookups) so the two can't drift apart the way they did before 2026-08-21.
# 1-4 (A1-B2) covers the original 173 lessons; 5/6 (C1/C2) added 2026-08-21
# for the first C1/C2 grammar content (see CLAUDE.md's "9 confirmed grammar
# gaps" -- lessons 174-182) -- grammar had no content above B2 before this.
DIFFICULTY_TO_CEFR: dict[int, str] = {1: "A1", 2: "A2", 3: "B1", 4: "B2", 5: "C1", 6: "C2"}

# Scoring weights — tunable, no training data to fit them against yet (V1).
W_SRS     = 0.5
W_MASTERY = 0.3
W_NOVELTY = 0.2

_NEW_UNIT_URGENCY  = 0.15   # small nudge so brand-new lessons aren't starved by reviews
_MASTERY_EMA_ALPHA = 0.25
_SRS_MIN_INTERVAL  = 1.0
_SRS_MAX_INTERVAL  = 60.0
_UNSEEN_MASTERY    = 0.0   # a topic with no attempts yet is "not yet mastered", not "half mastered" —
                            # this is what makes novelty correctly favor A1 first for a brand-new user

# ── Path ordering (2026-08-27, Natalia's tutoring model) ───────────────────
# get_next()/get_stats() above score every module uniformly, all competing on
# one formula -- fine for within-module picks, but Natalia's real teaching
# order is stricter: reading (script/phonics) FIRST for a brand-new learner,
# THEN grammar+vocab, with grammar taught strictly in sequence (each lesson
# is deliberately harder than the last) rather than freely reordered by
# score. get_path_next() below is a thin ordering layer on top of the
# existing per-unit scoring -- it decides WHICH MODULE gets to go next and,
# for grammar, WHICH LESSON; it still calls get_next()/mastery/srs_state
# underneath for the actual within-module ranking (vocab keeps its free
# score-based mixing, exactly as before).
SCRIPT_GATE_LANGS: frozenset[str] = frozenset({"ko", "ja", "zh"})
# Languages whose script has to be learned as a whole before grammar/vocab
# are legible at all (confirmed by Natalia's own experience learning Korean:
# without the letters, even the easiest grammar was unreadable) -- for these,
# the reading gate is every reading lesson for that language, not a fixed
# count. Everyone else uses a short fixed intro instead (Latin/Cyrillic
# learners mostly need a quick refresher on sound-spelling, not the whole
# alphabet from zero).
READING_INTRO_COUNT     = 5   # non-script languages: fixed reading-first batch before anything else opens
READING_INTERLEAVE_BATCH = 3  # once the gate clears but reading isn't exhausted yet: reading lessons per interleave cycle
GRAMMAR_ADVANCE_THRESHOLD = 0.5  # mastery score a grammar lesson's topic needs before the "frontier" moves past it


def _level_norm(level: str | None) -> float:
    if not level or level not in CEFR_RANK:
        return 0.5   # unknown level — treat as mid-scale
    return CEFR_RANK[level] / 5.0


def parse_unit_id(unit_id: str) -> dict:
    """'grammar:42' / 'vocab:Food:12' / 'phrasebook:Hobbies:474' /
    'reading:en:7' / 'custom:5' -> component dict.

    "custom" (grammar.py's My Phrases module) is not part of the recommender's
    catalog — it has no content_units row — but still parses so the
    lesson_pointer resume feature works for it (record_result/get_next simply
    never see a "custom:*" unit_id).

    "phrasebook" (CLAUDE.md, 2026-08-21) shares vocabulary_translated.xlsx and
    its global lesson_id numbering with "vocab" — same sheet/gid structure,
    just excluding the Word Bank sheets and its own unit_id prefix/module
    (see engine.vocab_loader.WORD_BANK_SHEETS) — parsed as its own module,
    not aliased to "vocab", so mastery/SRS/lesson_pointer stay independent
    tracks per module like every other pair of modules already does.
    """
    parts  = unit_id.split(":")
    module = parts[0]
    if module == "grammar":
        return {"module": "grammar", "lesson_id": int(parts[1])}
    if module == "vocab":
        return {"module": "vocab", "sheet": parts[1], "lesson_id": int(parts[2])}
    if module == "phrasebook":
        return {"module": "phrasebook", "sheet": parts[1], "lesson_id": int(parts[2])}
    if module == "reading":
        return {"module": "reading", "lang_code": parts[1], "lesson_id": int(parts[2])}
    if module == "target_grammar":
        return {"module": "target_grammar", "lang_code": parts[1], "topic_key": parts[2]}
    if module == "custom":
        return {"module": "custom", "lesson_id": int(parts[1])}
    raise ValueError(f"Unrecognised unit_id: {unit_id!r}")


def unit_id_for(lang_suffix: str, lesson_id: int, topic: str | None = None) -> str | None:
    """
    Build the content_units key for a grammar/vocab/phrasebook lesson being
    launched. Returns None for anything not in the recommender's catalog
    (e.g. the "custom" module's user-authored phrases, or a vocab/phrasebook
    lesson whose sheet couldn't be resolved) — callers pass that straight
    through as LessonSession(unit_id=...) and the session simply isn't tracked.
    """
    if lang_suffix == "grammar":
        return f"grammar:{lesson_id}"
    if lang_suffix == "vocab" and topic:
        return f"vocab:{topic}:{lesson_id}"
    if lang_suffix == "phrasebook" and topic:
        return f"phrasebook:{topic}:{lesson_id}"
    return None


def target_grammar_unit_id(target_lang: str, topic_key: str) -> str:
    """content_units key for an engine.target_grammar_paths topic — always
    seeded in advance (scripts/seed_content_units.py), unlike grammar/vocab/
    phrasebook's unit_id_for() which builds one for a lesson at launch time."""
    return f"target_grammar:{LANG_TO_CODE.get(target_lang, target_lang)}:{topic_key}"


def lookup_unit(unit_id: str) -> dict | None:
    return db.fetch_one(
        "SELECT * FROM content_units WHERE unit_id = :uid", {"uid": unit_id}
    )


def vocab_topic_for_lesson(lesson_id: int, target_lang: str, db_path) -> str | None:
    """
    Topic label for a "vocab" or "phrasebook" module lesson_id, used to
    build its unit_id (see unit_id_for). Tries the CEFR-J level ("A1".."C2")
    lookup first -- Vocabulary is CEFR-J-based for every target_lang now
    (CLAUDE.md 2026-08-22, translated on demand per lesson, see
    engine.cefr_j_vocab_loader / engine.session) -- which only ever matches
    a CEFR-J lesson_id (cefr_j_vocab_loader.GID_BASE+ range). Any other
    lesson_id -- Phrasebook, which was never migrated to CEFR-J, or a
    pre-CEFR-J Word Bank lesson_id -- falls back to the real sheet-name
    lookup from vocabulary_translated.xlsx's global index
    (engine.vocab_loader.get_topic_for_lesson), shared by both the "vocab"
    (Word Bank sheets) and "phrasebook" (everything else) module splits
    since they're keyed off the same workbook/global index
    (scripts/seed_content_units.py::seed_vocab()'s IMPORTANT note).

    Fixed 2026-08-22: this used to be a hard target_lang=="English" branch,
    then briefly a CEFR-J-only lookup with no fallback -- both left every
    Phrasebook lesson (and, in the CEFR-J-only version, every non-CEFR-J
    vocab lesson_id) with topic=None, so unit_id_for() returned None and
    the lesson's progress was silently never recorded in mastery/SRS.
    """
    from engine import cefr_j_vocab_loader
    topic = cefr_j_vocab_loader.topic_for_lesson(lesson_id)
    if topic:
        return topic
    from engine.vocab_loader import get_topic_for_lesson
    topic, _ = get_topic_for_lesson(str(db_path), lesson_id)
    return topic


# ── Candidate scoring ───────────────────────────────────────────────────────

def _candidates(target_lang: str, module: str | None = None) -> list[dict]:
    """
    content_units rows available for this target_lang. Most rows are
    language-agnostic (grammar/phrasebook: same lesson, parallel columns
    for every target language) -- only rows whose source_lesson is itself
    a real language code are locked to that one language: "reading"
    (real passages differ per language, so this stays locked).

    Word Bank vocab units (source_lesson = one of the old xlsx sheet
    names) are excluded unconditionally: CEFR-J (CLAUDE.md 2026-08-22)
    replaced them as the Vocabulary source for every target_lang, not just
    English (mistagged C2, alphabetical bucketing -- see CLAUDE.md's
    data-quality audit; translated on demand per lesson now, so it no
    longer needs a separate per-language wordlist). Without this,
    students would get both recommended interleaved, defeating the switch.
    """
    from engine.vocab_loader import WORD_BANK_SHEETS

    lang_code  = LANG_TO_CODE.get(target_lang, "en")
    real_codes = tuple(LANG_TO_CODE.values())
    sql = (
        "SELECT * FROM content_units WHERE "
        "(source_lesson NOT IN :real_codes OR source_lesson = :lang_code) "
        "AND NOT (module = 'vocab' AND source_lesson IN :word_bank_sheets)"
    )
    params: dict = {
        "lang_code": lang_code,
        "real_codes": real_codes,
        "word_bank_sheets": tuple(WORD_BANK_SHEETS),
    }
    if module:
        sql += " AND module = :module"
        params["module"] = module
    return db.fetch_all(sql, params)


def _mastery_topic(topic: str | None) -> str:
    """Real topic when tagged; "general" (the shared bucket record_result()
    already falls back to for topic-less content, e.g. Spanish/Ukrainian
    reading — CLAUDE.md's data-quality audit) otherwise. Used everywhere a
    unit's topic is turned into a mastery-table key, so real attempts,
    quiz-seeding, and lookups all agree on the same key for untagged units
    instead of seeding silently being a no-op for them."""
    return topic or "general"


def _mastery_map(user_id: str, target_lang: str) -> dict[tuple[str, str], dict]:
    rows = db.fetch_all(
        "SELECT * FROM mastery WHERE user_id = :uid AND target_lang = :lang",
        {"uid": user_id, "lang": target_lang},
    )
    return {(r["module"], r["topic"]): r for r in rows}


def _srs_map(user_id: str, target_lang: str) -> dict[str, dict]:
    rows = db.fetch_all(
        "SELECT * FROM srs_state WHERE user_id = :uid AND target_lang = :lang",
        {"uid": user_id, "lang": target_lang},
    )
    return {r["unit_id"]: r for r in rows}


def _score_unit(unit: dict, mastery_row: dict | None, srs_row: dict | None, today: date) -> float:
    if srs_row is not None:
        due = srs_row["due_date"]
        interval = max(float(srs_row["interval_days"]), 1.0)
        overdue_days = (today - due).days
        urgency = max(overdue_days / interval, 0.0)
        urgency = min(urgency, 3.0)
    else:
        urgency = _NEW_UNIT_URGENCY

    if mastery_row is not None:
        m_score = mastery_row["score"]
        target_level = min(m_score + 0.15, 1.0)   # aim slightly above known ability
    else:
        m_score = _UNSEEN_MASTERY
        target_level = 0.0   # no signal yet on this topic — aim at the easiest level,
                              # not "slightly above nothing" (that would favor A2 over A1)
    mastery_gap = 1.0 - m_score

    novelty = 1.0 - abs(_level_norm(unit["level"]) - target_level)

    return W_SRS * urgency + W_MASTERY * mastery_gap + W_NOVELTY * novelty


def get_next(user_id: str, target_lang: str, module: str | None = None, limit: int = 1) -> list[dict]:
    """
    Return up to `limit` candidate lessons, highest score first. Each item is a
    content_units row plus a "score" key. This is a live snapshot, not a fixed
    sequence — completing the top item changes mastery/SRS and can reorder the
    rest on the next call.
    """
    candidates = _candidates(target_lang, module)
    if not candidates:
        return []
    mastery = _mastery_map(user_id, target_lang)
    srs     = _srs_map(user_id, target_lang)
    today   = date.today()

    scored = [
        {**unit, "score": _score_unit(
            unit, mastery.get((unit["module"], _mastery_topic(unit["topic"]))),
            srs.get(unit["unit_id"]), today)}
        for unit in candidates
    ]
    scored.sort(key=lambda u: u["score"], reverse=True)
    return scored[:limit]


def _is_script_lang(target_lang: str) -> bool:
    return LANG_TO_CODE.get(target_lang) in SCRIPT_GATE_LANGS


def _reading_progress(user_id: str, target_lang: str) -> tuple[int, int]:
    """(attempted, total) reading units for this (user, target_lang) — "attempted"
    means it has an srs_state row (written on the first checked answer, same
    signal lesson_progress_map() already uses for the wave-picker colors)."""
    total = len(_candidates(target_lang, module="reading"))
    if total == 0:
        return 0, 0
    srs = _srs_map(user_id, target_lang)
    done = sum(1 for uid in srs if uid.startswith("reading:"))
    return done, total


def _grammar_frontier_unit(user_id: str, target_lang: str,
                            threshold: float = GRAMMAR_ADVANCE_THRESHOLD) -> dict | None:
    """
    The single grammar lesson to teach next, in the curriculum's own designed
    order (lesson_id ascending -- each lesson is deliberately harder than the
    last, per Natalia: free score-based reordering would undo that). "Done
    enough to move past" = mastery for that lesson's topic at/above
    `threshold`, not merely attempted -- so a lesson that was attempted and
    failed (mastery stays low) keeps being the frontier, which is exactly the
    "return to the missing topic" behavior Natalia described, with no extra
    state needed beyond the mastery table that already exists. A student who
    jumps ahead via the manual "harder" lesson picker and does well raises
    that lesson's own mastery (record_result already does this) without
    moving the frontier past whatever's still actually weak/unseen before it.
    """
    units = _candidates(target_lang, module="grammar")
    if not units:
        return None

    def _lid(u: dict) -> int:
        try:
            return parse_unit_id(u["unit_id"])["lesson_id"]
        except Exception:
            return 0

    units.sort(key=_lid)
    mastery = _mastery_map(user_id, target_lang)
    for u in units:
        topic = _mastery_topic(u["topic"])
        row = mastery.get(("grammar", topic))
        score = row["score"] if row else _UNSEEN_MASTERY
        if score < threshold:
            return u
    return units[-1]   # everything at/above threshold — nothing left to introduce, stay put


def grammar_neighbor(target_lang: str, lesson_id: int, direction: int) -> dict | None:
    """
    The grammar lesson immediately before (direction=-1, "Easier") or after
    (direction=+1, "Harder") `lesson_id` in the curriculum's own designed
    order -- backs the manual override buttons next to My Path's recommended
    grammar lesson (2026-08-27, Natalia: "можна пробувати давати вправу
    поскладніше... якщо учень не справляється, повертатися"). Purely a
    launch-time override — it doesn't touch mastery/srs_state itself, so it
    doesn't move _grammar_frontier_unit()'s own next recommendation; only a
    real attempt (record_result) does that, exactly like probing ahead via
    the ordinary lesson picker already worked before this function existed.
    None at either end of the sequence (already at lesson 1 / already at the
    last lesson).
    """
    units = _candidates(target_lang, module="grammar")
    if not units:
        return None
    units.sort(key=lambda u: parse_unit_id(u["unit_id"])["lesson_id"])
    ids = [parse_unit_id(u["unit_id"])["lesson_id"] for u in units]
    try:
        idx = ids.index(lesson_id)
    except ValueError:
        return None
    new_idx = idx + direction
    if 0 <= new_idx < len(units):
        return units[new_idx]
    return None


def current_level(user_id: str, target_lang: str) -> str | None:
    """
    The student's current CEFR level in target_lang, read off the grammar
    frontier (whatever lesson _grammar_frontier_unit says is next -- the
    lesson they're actually working on right now, not a guess). Used by
    My Phrases' word-list generator (2026-08-28) to pick a sensible default
    grammar difficulty when the student doesn't name a specific construction.
    None if there's no grammar catalog for this language at all.
    """
    unit = _grammar_frontier_unit(user_id, target_lang)
    return unit["level"] if unit else None


def _interleave_path(user_id: str, target_lang: str, limit: int) -> list[dict]:
    """Reading gate is cleared but reading isn't exhausted yet: 1 grammar +
    1 vocab + READING_INTERLEAVE_BATCH reading, repeating -- Natalia's own
    tutoring pattern ("граматика лексика по 1, потім ще 2-3 читання")."""
    pattern = ["grammar", "vocab"] + ["reading"] * READING_INTERLEAVE_BATCH
    frontier = _grammar_frontier_unit(user_id, target_lang)
    vocab_pool = get_next(user_id, target_lang, module="vocab", limit=limit)
    reading_pool = get_next(user_id, target_lang, module="reading", limit=limit)

    picks: list[dict] = []
    seen: set[str] = set()
    vi = ri = 0
    guard = 0
    while len(picks) < limit and guard < limit * len(pattern) + len(pattern):
        kind = pattern[guard % len(pattern)]
        guard += 1
        unit = None
        if kind == "grammar":
            unit = frontier
        elif kind == "vocab" and vi < len(vocab_pool):
            unit, vi = vocab_pool[vi], vi + 1
        elif kind == "reading" and ri < len(reading_pool):
            unit, ri = reading_pool[ri], ri + 1
        if unit is not None and unit["unit_id"] not in seen:
            picks.append(unit)
            seen.add(unit["unit_id"])
    return picks[:limit]


def _normal_path(user_id: str, target_lang: str, limit: int) -> list[dict]:
    """Reading is exhausted (or this target_lang has no reading content at
    all) -- grammar keeps its sequential frontier, everything else (vocab,
    phrasebook, reading review, target_grammar) keeps the free score-based
    mixing get_next() already does. Reading doesn't disappear here: overdue
    reading units still surface through get_next()'s own SRS-urgency term,
    just as background review, not a dedicated phase."""
    picks: list[dict] = []
    frontier = _grammar_frontier_unit(user_id, target_lang)
    if frontier:
        picks.append(frontier)
    for u in get_next(user_id, target_lang, limit=limit + 5):
        if u["module"] == "grammar":
            continue
        picks.append(u)
        if len(picks) >= limit:
            break
    return picks[:limit]


def get_path_next(user_id: str, target_lang: str, limit: int = 6) -> list[dict]:
    """
    Cross-module ordering for "My Path" (replaces the raw get_next(module=None)
    call get_stats() used to make). Three phases per (user, target_lang):

      1. Reading gate — pure reading, nothing else recommended. Full reading
         catalog for script languages (ko/ja/zh — without the alphabet
         nothing else is legible), a short fixed intro (READING_INTRO_COUNT)
         for everyone else.
      2. Interleave — gate cleared, reading not yet exhausted: 1 grammar +
         1 vocab + a small reading batch, repeating (_interleave_path).
      3. Normal — reading exhausted (or none exists for this language):
         grammar advances one lesson at a time via its mastery-gated
         frontier, everything else keeps free score-based mixing
         (_normal_path).
    """
    done, total = _reading_progress(user_id, target_lang)
    if total == 0:
        return _normal_path(user_id, target_lang, limit)

    gate = total if _is_script_lang(target_lang) else min(READING_INTRO_COUNT, total)
    if done < gate:
        return get_next(user_id, target_lang, module="reading", limit=limit)
    if done < total:
        return _interleave_path(user_id, target_lang, limit)
    return _normal_path(user_id, target_lang, limit)


# ── Recording results ───────────────────────────────────────────────────────

def record_result(user_id: str, target_lang: str, unit_id: str, correct: bool) -> None:
    """Update mastery (EMA) and srs_state (SM-2-lite) after an attempt on unit_id."""
    unit = lookup_unit(unit_id)
    if unit is None:
        return
    _update_mastery(user_id, target_lang, unit["module"], _mastery_topic(unit["topic"]), correct)
    _update_srs(user_id, target_lang, unit_id, correct)


def _update_mastery(user_id: str, target_lang: str, module: str, topic: str, correct: bool) -> None:
    row = db.fetch_one(
        "SELECT * FROM mastery WHERE user_id=:uid AND target_lang=:lang AND module=:mod AND topic=:topic",
        {"uid": user_id, "lang": target_lang, "mod": module, "topic": topic},
    )
    old_score = row["score"] if row else _UNSEEN_MASTERY
    new_score = old_score + _MASTERY_EMA_ALPHA * (float(correct) - old_score)
    db.upsert(
        "mastery",
        keys={"user_id": user_id, "target_lang": target_lang, "module": module, "topic": topic},
        values={
            "score": new_score,
            "n_attempts": (row["n_attempts"] if row else 0) + 1,
        },
    )


def _update_srs(user_id: str, target_lang: str, unit_id: str, correct: bool) -> None:
    row = db.fetch_one(
        "SELECT * FROM srs_state WHERE user_id=:uid AND target_lang=:lang AND unit_id=:uid2",
        {"uid": user_id, "lang": target_lang, "uid2": unit_id},
    )
    reps = (row["reps"] if row else 0)
    if correct:
        reps += 1
        interval = _SRS_MIN_INTERVAL if reps <= 1 else min(
            (row["interval_days"] if row else _SRS_MIN_INTERVAL) * 2.0, _SRS_MAX_INTERVAL
        )
    else:
        reps = 0
        interval = _SRS_MIN_INTERVAL

    db.upsert(
        "srs_state",
        keys={"user_id": user_id, "target_lang": target_lang, "unit_id": unit_id},
        values={
            "interval_days": interval,
            "due_date": date.today() + timedelta(days=interval),
            "last_result": correct,
            "reps": reps,
        },
    )


# ── Lesson resume pointer (replaces logger.py's "progress" sheet) ──────────
# Keyed by (user, target_lang, module) — grammar/vocab/reading progress
# independently, same granularity the old language_pair suffix gave.

def get_pointer(user_id: str, target_lang: str, module: str) -> dict | None:
    return db.fetch_one(
        "SELECT * FROM lesson_pointer WHERE user_id=:uid AND target_lang=:lang AND module=:mod",
        {"uid": user_id, "lang": target_lang, "mod": module},
    )


def save_pointer(user_id: str, target_lang: str, module: str, unit_id: str, step: int) -> None:
    db.upsert(
        "lesson_pointer",
        keys={"user_id": user_id, "target_lang": target_lang, "module": module},
        values={"unit_id": unit_id, "step": step},
    )


# ── Placement quiz support (engine.placement_quiz, CLAUDE.md item 3) ───────

def seed_mastery_from_level(
    user_id: str, target_lang: str, module: str, estimated_level: str, prior: float = 0.6,
) -> None:
    """
    Bulk-seed mastery for every topic at/below estimated_level, instead of each
    one starting at _UNSEEN_MASTERY (0.0). Used after the optional placement
    quiz so material the user already knows gets deprioritized immediately,
    rather than the recommender treating it as "knows nothing" until they
    happen to attempt it. Never overwrites a topic that already has real
    attempts recorded.

    Includes topic-less units (e.g. Spanish/Ukrainian reading has no topic
    tags at all — CLAUDE.md's data-quality audit): those collapse onto the
    shared "general" bucket via _mastery_topic(), the same fallback
    record_result() already uses for real attempts. Without this, a
    language with untagged reading content could never be seeded at all —
    every reading unit stayed permanently "unseen" regardless of quiz
    result, and cross-module My Path kept recommending it over every other,
    now-deprioritized module (reported 2026-08-23: "My Path sent me back to
    lesson 1" right after a quiz that estimated A2).
    """
    if estimated_level not in CEFR_RANK:
        return
    max_rank = CEFR_RANK[estimated_level]
    units = db.fetch_all(
        "SELECT DISTINCT topic, level FROM content_units WHERE module=:m",
        {"m": module},
    )
    existing = _mastery_map(user_id, target_lang)
    for u in units:
        if CEFR_RANK.get(u["level"], 99) > max_rank:
            continue
        topic = _mastery_topic(u["topic"])
        if (module, topic) in existing:
            continue
        db.upsert(
            "mastery",
            keys={"user_id": user_id, "target_lang": target_lang, "module": module, "topic": topic},
            values={"score": prior, "n_attempts": 0},
        )


def lesson_levels(module: str) -> dict[int, str]:
    """
    {lesson_id: CEFR level} for every unit in this module, parsed from
    unit_id — NOT content_units.source_lesson, which for vocab holds the
    sheet name rather than the lesson id. Lets the lesson-picker UI show
    each lesson's CEFR band (e.g. "Lesson 42 · A2") so a learner can see
    where A1 ends and A2 begins, not just rely on an automatic pick.
    """
    rows = db.fetch_all(
        "SELECT unit_id, level FROM content_units WHERE module=:m AND level IS NOT NULL",
        {"m": module},
    )
    out: dict[int, str] = {}
    for r in rows:
        try:
            out[parse_unit_id(r["unit_id"])["lesson_id"]] = r["level"]
        except Exception:
            continue
    return out


def lesson_progress_map(user_id: str, target_lang: str, module: str) -> dict[int, bool]:
    """
    {lesson_id: True} for every lesson in this module that has at least one
    recorded attempt (a srs_state row — written on every checked answer via
    LessonSession.score() -> record_result()). Used to color-code the wave
    lesson picker by real engagement (visited vs not-started) instead of a
    decorative, meaningless per-index color cycle.
    """
    if not user_id:
        return {}
    rows = db.fetch_all(
        "SELECT unit_id FROM srs_state WHERE user_id=:uid AND target_lang=:lang "
        "AND unit_id LIKE :prefix",
        {"uid": user_id, "lang": target_lang, "prefix": f"{module}:%"},
    )
    out: dict[int, bool] = {}
    for r in rows:
        try:
            out[parse_unit_id(r["unit_id"])["lesson_id"]] = True
        except Exception:
            continue
    return out


def has_signal(user_id: str, target_lang: str, module: str) -> bool:
    """
    True if the user has any mastery data for this module — from a real
    attempt or from placement_quiz.seed_mastery_from_level(). Used to decide
    whether a "recommended starting lesson" is meaningful, vs. just noise
    from ties between identically-scored, never-attempted lessons in a
    completely untouched catalog (those don't reliably sort to lesson 1).
    """
    row = db.fetch_one(
        "SELECT 1 FROM mastery WHERE user_id=:uid AND target_lang=:lang AND module=:mod LIMIT 1",
        {"uid": user_id, "lang": target_lang, "mod": module},
    )
    return row is not None


# ── Stats (for path_app.py) ─────────────────────────────────────────────────

def reset_user(user_id: str, target_lang: str) -> None:
    """Wipe mastery/SRS/pointer state for (user, target_lang) — 'start over'."""
    for table in ("mastery", "srs_state", "lesson_pointer"):
        db.execute(
            f"DELETE FROM {table} WHERE user_id = :uid AND target_lang = :lang",
            {"uid": user_id, "lang": target_lang},
        )


def get_stats(user_id: str, target_lang: str) -> dict:
    """Coverage-based progress summary — replaces curriculum.py's get_stats()."""
    totals: dict[str, int] = {"grammar": 0, "vocab": 0, "reading": 0}
    for unit in _candidates(target_lang):
        totals[unit["module"]] = totals.get(unit["module"], 0) + 1

    srs = _srs_map(user_id, target_lang)
    seen_by_module: dict[str, int] = {"grammar": 0, "vocab": 0, "reading": 0}
    for unit_id in srs:
        mod = parse_unit_id(unit_id)["module"]
        seen_by_module[mod] = seen_by_module.get(mod, 0) + 1

    total = sum(totals.values())
    done  = sum(seen_by_module.values())
    top   = get_path_next(user_id, target_lang, limit=6)

    return {
        "done_grammar": seen_by_module["grammar"], "total_grammar": totals["grammar"],
        "done_vocab":   seen_by_module["vocab"],   "total_vocab":   totals["vocab"],
        "done_reading": seen_by_module["reading"], "total_reading": totals["reading"],
        "done_total":   done, "total_units": total,
        "pct":          round(done / total * 100, 1) if total else 0.0,
        "current_unit": top[0] if top else None,
        "upcoming":     top,
    }
