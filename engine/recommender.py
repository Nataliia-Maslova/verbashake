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

import threading
from datetime import date, timedelta

from engine import db
from engine.curriculum_order import order_key

# Re-exported so callers that used to import this from engine.curriculum don't
# need a second import.
LANG_TO_CODE: dict[str, str] = {
    "English": "en", "Ukrainian": "uk", "Spanish": "es", "Korean": "ko",
    "French": "fr", "German": "de", "Japanese": "ja", "Chinese": "zh",
    "Portuguese": "pt", "Italian": "it", "Polish": "pl", "Russian": "ru",
    "Catalan": "ca", "Dutch": "nl", "Romanian": "ro", "Bulgarian": "bg",
    "Czech": "cs", "Turkish": "tr", "Swedish": "sv",
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

# ── Path ordering (2026-08-27, rebuilt 2026-10-22) ──────────────────────
# get_next()/get_stats() above score every module uniformly, all competing on
# one formula -- fine for within-module picks, but Natalia's real teaching
# order is stricter: grammar taught strictly in sequence (each lesson is
# deliberately harder than the last), vocabulary and phrasebook by the
# student's level. get_path_next() below is a thin ordering layer on top of
# the existing per-unit scoring.
#
# 2026-10-22, Natalia: reading is NOT a My Path lesson any more -- it is only
# the "Читання" step after the warmup inside every lesson (grammar.py /
# reading_app.render_embedded_reading_step). Two exceptions for a student who
# needs the letters:
#   - ko/ja/zh: the whole letter block (reading_start.LETTER_LESSONS) comes
#     first in My Path, then ordinary lessons -- without the script nothing
#     else is legible (Natalia's own experience learning Korean);
#   - every other language: the first lesson's "Читання" step runs
#     READING_INTRO_COUNT reading lessons in a row.
LETTER_BLOCK_LANGS: frozenset[str] = frozenset({"ko", "ja", "zh"})
READING_INTRO_COUNT = 5   # letter learners, Latin/Cyrillic: reading lessons in the first lesson's "Читання" step
PHRASEBOOK_FROM_LEVEL = "A2"  # phrasebook joins the path from this level on
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
    rows = db.fetch_all(sql, params)
    if target_lang != "English":
        # English verb-form lists are hidden for every other target language
        # (grammar.py::_load_grammar) -- keep them out of recommendations too.
        from engine.verb_form_topics import ENGLISH_PIVOT_VERB_LESSONS
        hidden = {f"grammar:{i}" for i in ENGLISH_PIVOT_VERB_LESSONS}
        rows = [r for r in rows if r["unit_id"] not in hidden]
    return rows


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


def needs_letters(user_id: str, target_lang: str) -> bool:
    """True when this student starts reading from the letter lessons
    (engine.reading_start.skips_letters is False for their level and
    "do you know the letters?" answer in this target_lang)."""
    from engine import user_prefs, reading_start
    try:
        level = user_prefs.get_language_level(user_id, target_lang)
        literacy = user_prefs.get_language_literacy(user_id, target_lang)
    except Exception:
        return False
    return not reading_start.skips_letters(level, literacy)


def path_level(user_id: str, target_lang: str, frontier: dict | None = None) -> str:
    """CEFR level My Path picks vocabulary/phrasebook for: the higher of the
    student's own answer for this language (zero / none -> A1) and one level
    below the grammar lesson they are on now, so it rises as they go. One
    below, because seeding from the student's answer marks their own level's
    grammar as known and the frontier starts a level above it."""
    from engine import user_prefs
    try:
        own = user_prefs.get_language_level(user_id, target_lang)
    except Exception:
        own = None
    own = own if own in CEFR_RANK else "A1"
    if frontier is None:
        frontier = _grammar_frontier_unit(user_id, target_lang)
    cur = frontier.get("level") if frontier else None
    if cur in CEFR_RANK and CEFR_RANK[cur] - 1 > CEFR_RANK[own]:
        return next(lvl for lvl, rk in CEFR_RANK.items() if rk == CEFR_RANK[cur] - 1)
    return own


def _reading_units(user_id: str, target_lang: str) -> list[dict]:
    """Reading units this student goes through, in catalog order. A student
    who can already read (engine.reading_start.skips_letters: B1+, or A2 who
    said "I can read") doesn't get the letter/syllable lessons — 2026-10-15,
    Natalia: a B1 student was given an alphabet lesson as the in-lesson
    "Читання" step."""
    units = _candidates(target_lang, module="reading")
    if not units:
        return units
    from engine import user_prefs, reading_start
    try:
        level = user_prefs.get_language_level(user_id, target_lang)
        literacy = user_prefs.get_language_literacy(user_id, target_lang)
    except Exception:
        return units
    if not reading_start.skips_letters(level, literacy):
        return units
    skip = reading_start.letter_lessons(LANG_TO_CODE.get(target_lang, ""))
    kept = [u for u in units if parse_unit_id(u["unit_id"]).get("lesson_id") not in skip]
    return kept or units


def _reading_progress(user_id: str, target_lang: str) -> tuple[int, int]:
    """(attempted, total) reading units for this (user, target_lang) — "attempted"
    means it has an srs_state row (written on the first checked answer, same
    signal lesson_progress_map() already uses for the wave-picker colors).
    Counts only the units this student actually goes through (_reading_units)."""
    units = _reading_units(user_id, target_lang)
    if not units:
        return 0, 0
    srs = _srs_map(user_id, target_lang)
    done = sum(1 for u in units if u["unit_id"] in srs)
    return done, len(units)


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

    units.sort(key=lambda u: order_key(_lid(u)))
    mastery = _mastery_map(user_id, target_lang)
    for u in units:
        topic = _mastery_topic(u["topic"])
        row = mastery.get(("grammar", topic))
        score = row["score"] if row else _UNSEEN_MASTERY
        if score < threshold:
            return u
    return units[-1]   # everything at/above threshold — nothing left to introduce, stay put


def _reading_frontier_units(user_id: str, target_lang: str, limit: int) -> list[dict]:
    """
    Next reading lesson(s) in the curriculum's own order (lesson_id
    ascending), not freely reordered by score -- reading lessons build on
    each other the same way grammar lessons do (phonics/letters), but unlike
    grammar there's no per-lesson mastery topic to gate on: many reading
    units share the fallback "general" mastery bucket (untagged topic, see
    _mastery_topic), so get_next()'s novelty term ends up comparing them all
    against the SAME rising mastery score after just a couple of correct
    answers on lesson 1 -- its "aim slightly above known ability" logic then
    jumps straight to whichever lesson sits at that CEFR level deep in the
    catalog (reported 2026-08-28: "after reading lesson 1, lesson 51 is
    immediately recommended"). Already-attempted lessons still resurface
    later through get_next()'s own SRS-urgency term as background review;
    this only decides what's NEXT to introduce.
    """
    units = _reading_units(user_id, target_lang)
    if not units:
        return []

    def _lid(u: dict) -> int:
        try:
            return parse_unit_id(u["unit_id"])["lesson_id"]
        except Exception:
            return 0

    units.sort(key=_lid)
    srs = _srs_map(user_id, target_lang)
    unseen = [u for u in units if u["unit_id"] not in srs]
    return (unseen if unseen else units)[:limit]


def next_reading_unit(user_id: str, target_lang: str) -> dict | None:
    """
    Public wrapper around _reading_frontier_units for embedding ONE reading
    lesson inside another module's flow (grammar.py's mandatory "Читання"
    step between Warmup and New Material, 2026-09-27 -- Natalia: "чтение
    тренировать после разминки до нового материала... алгоритму нужно
    будет подбирать урок по чтению"). Returns None when this language has
    no reading catalog at all, OR when every reading unit already has an
    srs_state row (the curated track is fully exhausted) -- both cases the
    caller falls back to a live AI-generated passage instead, per Natalia's
    "always show this step" decision. Deliberately does NOT reuse
    _reading_frontier_units' own "nothing unseen left -> return unit #1
    again" fallback (that's tuned for get_next()'s background-review
    scoring, not for "is there real new content to introduce").
    """
    done, total = _reading_progress(user_id, target_lang)
    if total == 0 or done >= total:
        return None
    units = _reading_frontier_units(user_id, target_lang, limit=1)
    return units[0] if units else None


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
    units.sort(key=lambda u: order_key(parse_unit_id(u["unit_id"])["lesson_id"]))
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


def _letter_block_units(user_id: str, target_lang: str, limit: int) -> list[dict]:
    """ko/ja/zh student who needs the letters: the letter lessons not yet
    attempted, in order. Empty once the block is done (or not needed)."""
    from engine import reading_start
    code = LANG_TO_CODE.get(target_lang, "")
    if code not in LETTER_BLOCK_LANGS or not needs_letters(user_id, target_lang):
        return []
    letters = reading_start.letter_lessons(code)
    units = [u for u in _candidates(target_lang, module="reading")
             if parse_unit_id(u["unit_id"]).get("lesson_id") in letters]
    units.sort(key=lambda u: parse_unit_id(u["unit_id"])["lesson_id"])
    srs = _srs_map(user_id, target_lang)
    return [u for u in units if u["unit_id"] not in srs][:limit]


def _by_level(pool: list[dict], level: str, allow_above: int) -> list[dict]:
    """Units of `pool` up to `level` + allow_above: the student's own level
    first, then the levels above it, then the easier ones below; get_next()'s
    order (due reviews, weak topics) kept inside each group. Untagged units
    count as the student's level."""
    rank = CEFR_RANK.get(level, 0)

    def _r(u: dict) -> int:
        return CEFR_RANK.get(u.get("level") or "", rank)

    fit = [u for u in pool if _r(u) <= rank + allow_above]
    fit.sort(key=lambda u: 0 if _r(u) == rank else (1 if _r(u) > rank else 2))
    return fit


def _level_path(user_id: str, target_lang: str, limit: int) -> list[dict]:
    """Grammar (its sequential frontier) -> vocabulary -> phrasebook (from
    PHRASEBOOK_FROM_LEVEL), repeating; vocabulary at the student's level or
    one above, phrasebook at or below it.

    target_grammar units never appear: a "target_grammar" content_units row
    has no lesson_id (parse_unit_id() returns lang_code/topic_key), and every
    caller treats a returned unit as a launchable lesson. The same topic is
    always also seeded as a real grammar:1000+ lesson, and that one comes
    through the grammar frontier."""
    frontier = _grammar_frontier_unit(user_id, target_lang)
    level = path_level(user_id, target_lang, frontier)
    pattern = ["grammar", "vocab"]
    if CEFR_RANK[level] >= CEFR_RANK[PHRASEBOOK_FROM_LEVEL]:
        pattern.append("phrasebook")
    pools = {
        "vocab": _by_level(get_next(user_id, target_lang, module="vocab", limit=100_000), level, 1),
        "phrasebook": (_by_level(get_next(user_id, target_lang, module="phrasebook", limit=100_000), level, 0)
                       if "phrasebook" in pattern else []),
    }
    idx = {"vocab": 0, "phrasebook": 0}
    picks: list[dict] = []
    seen: set[str] = set()
    for step in range(limit * len(pattern)):
        if len(picks) >= limit:
            break
        kind = pattern[step % len(pattern)]
        if kind == "grammar":
            unit = frontier if step == 0 else None
        else:
            pool = pools[kind]
            unit = pool[idx[kind]] if idx[kind] < len(pool) else None
            idx[kind] += 1
        if unit is not None and unit["unit_id"] not in seen:
            picks.append(unit)
            seen.add(unit["unit_id"])
    return picks[:limit]


def get_path_next(user_id: str, target_lang: str, limit: int = 6) -> list[dict]:
    """
    Cross-module ordering for "My Path" (replaces the raw get_next(module=None)
    call get_stats() used to make):

      1. ko/ja/zh student who needs the letters: the letter block first
         (_letter_block_units), nothing else.
      2. Everyone else / after the block: grammar frontier + vocabulary +
         phrasebook (from A2) by level (_level_path). Reading is never a
         My Path lesson -- it is the "Читання" step inside every lesson.

    Lessons the student pinned themselves (engine/path_pins.py, e.g. "➕ В мій
    шлях" in the Songs module) come before both, until mastered.
    """
    pinned = _pinned_units(user_id, target_lang)
    base = _phase_path(user_id, target_lang, limit)
    if not pinned:
        return base
    seen = {u["unit_id"] for u in pinned}
    return (pinned + [u for u in base if u["unit_id"] not in seen])[:limit]


def _phase_path(user_id: str, target_lang: str, limit: int) -> list[dict]:
    block = _letter_block_units(user_id, target_lang, limit)
    return block if block else _level_path(user_id, target_lang, limit)


def _pinned_units(user_id: str, target_lang: str) -> list[dict]:
    """Lessons the student added to My Path themselves (engine/path_pins.py,
    e.g. from a song) — shown before the regular order, oldest first, until
    the lesson's topic reaches GRAMMAR_ADVANCE_THRESHOLD. Each returned row
    carries "pinned_source" (the song title) for My Path's card. Only units
    still in this language's catalog (_candidates) count."""
    from engine import path_pins
    pins = path_pins.list_pins(user_id, target_lang)
    if not pins:
        return []
    try:
        catalog = {u["unit_id"]: u for u in _candidates(target_lang)}
        mastery = _mastery_map(user_id, target_lang)
    except Exception:
        return []
    out = []
    for p in pins:
        unit = catalog.get(p["unit_id"])
        if unit is None or unit["module"] == "target_grammar":
            continue
        row = mastery.get((unit["module"], _mastery_topic(unit["topic"])))
        if row and row["score"] >= GRAMMAR_ADVANCE_THRESHOLD:
            continue
        out.append({**unit, "pinned_source": p.get("source")})
    return out


# ── Recording results ───────────────────────────────────────────────────────

# _update_mastery/_update_srs (and record_results below) are each a plain
# read-then-write with no row lock in between: two near-simultaneous calls
# for the same (user_id, target_lang, unit_id) -- a double-click, or two
# open tabs on the same lesson -- can both read the same old row and race
# to overwrite each other's UPSERT, silently losing one attempt's effect on
# mastery/SRS. A per-key lock closes this for the realistic case (concurrent
# requests hitting the same long-running Streamlit process, which is how
# this app is actually deployed) -- it doesn't help across separate server
# processes, but there's only ever one such process for this app today.
# Grows by one Lock per distinct (user, lang, unit) ever seen for the life
# of the process -- unbounded in principle, negligible in practice at this
# app's scale (each Lock is a few dozen bytes; not worth an eviction scheme
# before there's any real evidence it matters).
_record_locks: dict[tuple[str, str, str], threading.Lock] = {}
_record_locks_guard = threading.Lock()


def _lock_for(user_id: str, target_lang: str, unit_id: str) -> threading.Lock:
    key = (user_id, target_lang, unit_id)
    with _record_locks_guard:
        lock = _record_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _record_locks[key] = lock
        return lock


def record_result(user_id: str, target_lang: str, unit_id: str, correct: bool) -> None:
    """Update mastery (EMA) and srs_state (SM-2-lite) after an attempt on unit_id."""
    with _lock_for(user_id, target_lang, unit_id):
        unit = lookup_unit(unit_id)
        if unit is None:
            return
        _update_mastery(user_id, target_lang, unit["module"], _mastery_topic(unit["topic"]), correct)
        _update_srs(user_id, target_lang, unit_id, correct)


def record_results(user_id: str, target_lang: str, unit_id: str, results: list[bool]) -> None:
    """
    Same effect as calling record_result() once per entry in `results` (in
    order) on the same unit_id, but in a fixed 5 DB round-trips total
    instead of 5 per result. Both mastery's EMA (_mastery_step) and SRS's
    SM-2-lite (_srs_step) are purely sequential -- each step depends only on
    the state the previous step produced, not on anything else -- so
    replaying them in memory and writing just the final state once produces
    the exact same mastery/SRS rows as calling record_result() in a loop.

    Written for grammar.py's target_grammar Check button, which used to
    call record_result() once per test item (up to 5 items -> up to 25
    sequential round-trips on Supabase's pooler for one click).
    """
    if not results:
        return
    with _lock_for(user_id, target_lang, unit_id):
        unit = lookup_unit(unit_id)
        if unit is None:
            return
        module, topic = unit["module"], _mastery_topic(unit["topic"])

        mrow = db.fetch_one(
            "SELECT * FROM mastery WHERE user_id=:uid AND target_lang=:lang AND module=:mod AND topic=:topic",
            {"uid": user_id, "lang": target_lang, "mod": module, "topic": topic},
        )
        score = mrow["score"] if mrow else _UNSEEN_MASTERY
        n_attempts = mrow["n_attempts"] if mrow else 0
        for correct in results:
            score = _mastery_step(score, correct)
            n_attempts += 1
        db.upsert(
            "mastery",
            keys={"user_id": user_id, "target_lang": target_lang, "module": module, "topic": topic},
            values={"score": score, "n_attempts": n_attempts},
        )

        srow = db.fetch_one(
            "SELECT * FROM srs_state WHERE user_id=:uid AND target_lang=:lang AND unit_id=:uid2",
            {"uid": user_id, "lang": target_lang, "uid2": unit_id},
        )
        reps = srow["reps"] if srow else 0
        interval = srow["interval_days"] if srow else _SRS_MIN_INTERVAL
        for correct in results:
            reps, interval = _srs_step(reps, interval, correct)
        db.upsert(
            "srs_state",
            keys={"user_id": user_id, "target_lang": target_lang, "unit_id": unit_id},
            values={
                "interval_days": interval,
                "due_date": date.today() + timedelta(days=interval),
                "last_result": results[-1],
                "reps": reps,
            },
        )


def _mastery_step(old_score: float, correct: bool) -> float:
    return old_score + _MASTERY_EMA_ALPHA * (float(correct) - old_score)


def _srs_step(reps: int, prev_interval: float, correct: bool) -> tuple[int, float]:
    """One SM-2-lite step. Returns (new_reps, new_interval_days)."""
    if correct:
        reps += 1
        interval = _SRS_MIN_INTERVAL if reps <= 1 else min(prev_interval * 2.0, _SRS_MAX_INTERVAL)
    else:
        reps = 0
        interval = _SRS_MIN_INTERVAL
    return reps, interval


def _update_mastery(user_id: str, target_lang: str, module: str, topic: str, correct: bool) -> None:
    row = db.fetch_one(
        "SELECT * FROM mastery WHERE user_id=:uid AND target_lang=:lang AND module=:mod AND topic=:topic",
        {"uid": user_id, "lang": target_lang, "mod": module, "topic": topic},
    )
    old_score = row["score"] if row else _UNSEEN_MASTERY
    new_score = _mastery_step(old_score, correct)
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
    reps, interval = _srs_step(
        row["reps"] if row else 0,
        row["interval_days"] if row else _SRS_MIN_INTERVAL,
        correct,
    )
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

    Batched (2026-09-07): a high self-report (B2/C1/C2) can qualify most or
    all of a module's topics, and app.py's onboarding calls this once per
    module in ALL_MODULES — the original per-topic db.upsert() loop meant
    up to ~530 sequential round-trips (one per distinct topic/level across
    all 5 modules) on a single "Start learning" click, on the same flaky
    Supabase pooler connection documented elsewhere in this file/CLAUDE.md
    to drop mid-batch at scale. That's both a multi-minute hang and a real
    crash risk (db._with_retry re-raises after 3 failed attempts, unlike
    most callers in this module none of which wrapped this loop in
    try/except) — see app.py's onboarding submit handler for the other half
    of this fix (session_state populated before, not after, seeding).
    Chunked like scripts/seed_content_units.py's bulk upsert for the same
    reason (a single execute_many() over everything still risked a
    mid-statement drop at this table's scale).
    """
    if estimated_level not in CEFR_RANK:
        return
    max_rank = CEFR_RANK[estimated_level]
    try:
        # _candidates() (not a raw "WHERE module=:m" query) so this respects
        # the same target_lang scoping every real recommendation already
        # goes through -- the raw query used to pool topics across all 13
        # languages' locked-language-path content (grammar/target_grammar),
        # seeding permanent dead mastery rows for languages the student
        # wasn't even onboarding into (2026-09-07 finding).
        units = _candidates(target_lang, module)
        existing = _mastery_map(user_id, target_lang)
    except Exception:
        # Same best-effort, failure-tolerant contract as the write loop
        # below -- a dropped connection here used to propagate uncaught
        # straight through app.py's onboarding "Start learning" handler,
        # crashing it before the already-saved profile's st.rerun() ran.
        return
    seen_topics: set[str] = set()
    rows = []
    for u in units:
        if CEFR_RANK.get(u["level"], 99) > max_rank:
            continue
        topic = _mastery_topic(u["topic"])
        if (module, topic) in existing or topic in seen_topics:
            continue
        seen_topics.add(topic)
        rows.append({
            "user_id": user_id, "target_lang": target_lang, "module": module,
            "topic": topic, "score": prior, "n_attempts": 0,
        })
    if not rows:
        return
    sql = (
        "INSERT INTO mastery (user_id, target_lang, module, topic, score, n_attempts) "
        "VALUES (:user_id, :target_lang, :module, :topic, :score, :n_attempts) "
        "ON CONFLICT (user_id, target_lang, module, topic) DO UPDATE SET "
        "score = EXCLUDED.score, n_attempts = EXCLUDED.n_attempts, updated_at = now()"
    )
    _CHUNK = 100
    for i in range(0, len(rows), _CHUNK):
        try:
            db.execute_many(sql, rows[i:i + _CHUNK])
        except Exception:
            pass


def all_topics(target_lang: str, module: str = "grammar") -> list[str]:
    """
    Distinct topic strings available in this module FOR target_lang — the
    candidate pool engine.gemini.classify_mistake_topics() picks from when
    resolving a free-text grammar-point guess to a real lesson (2026-09-06).

    Reuses _candidates()' existing per-language scoping instead of querying
    content_units directly — a raw `SELECT DISTINCT topic` would mix in
    topics that only exist as target-language-specific synthetic lessons
    for some OTHER language (target_grammar-promoted grammar:1000+ rows are
    locked to one target_lang via source_lesson, same as "reading" always
    has been — see _candidates()' own docstring), which would let a French
    learner's mistake get matched to a Ukrainian-only topic.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for u in _candidates(target_lang, module):
        topic = u.get("topic")
        if topic and topic not in seen_set:
            seen_set.add(topic)
            seen.append(topic)
    return seen


def lesson_for_topic(topic: str, target_lang: str, module: str = "grammar") -> dict | None:
    """
    content_units row tagged with this EXACT topic string, scoped to
    target_lang. Used after engine.gemini.classify_mistake_topics() has
    already picked `topic` verbatim from this same module's all_topics()
    candidate list, so an exact match is guaranteed to exist — no fuzzy
    matching needed (an earlier rapidfuzz-based attempt was dropped after a
    live test failed: imlls_database's topic labels are often paraphrased/
    colloquial, so a semantically-right guess scored far below the correct
    lesson on plain text similarity — see classify_mistake_topics()'s
    docstring for the full story).
    """
    for u in _candidates(target_lang, module):
        if u.get("topic") == topic:
            return u
    return None


def lesson_position(target_lang: str, module: str, lesson_id: int) -> int | None:
    """
    1-based position of `lesson_id` among this module's lessons FOR target_lang
    (same ordering/scoping the module's own lesson picker and sidebar
    "Topic 6 / 981" counter use), or None if it isn't found. For display only:
    raw ids are meaningless to a student -- CEFR-J vocab ids are 100000+ and
    target-grammar-path grammar ids 1000+ (found live 2026-09-20: My Path said
    "Урок 1104"). Built on _candidates(), so language-locked lessons of OTHER
    languages don't inflate the position.
    """
    ids = []
    for u in _candidates(target_lang, module):
        try:
            ids.append(parse_unit_id(u["unit_id"])["lesson_id"])
        except Exception:
            continue
    ids = sorted(set(ids), key=order_key) if module == "grammar" else sorted(set(ids))
    return ids.index(lesson_id) + 1 if lesson_id in ids else None


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


def passed_grammar_lessons(user_id: str, target_lang: str, lesson_ids: list[int]) -> dict[int, float]:
    """
    {lesson_id: mastery} for those of `lesson_ids` the student has passed —
    mastery for the lesson's topic at/above GRAMMAR_ADVANCE_THRESHOLD, the same
    "done enough to move past" bar _grammar_frontier_unit() uses. Used by the
    "Пара" Practice exercise (engine.lesson_pairs) to offer only partner
    lessons the student has actually been through. Best-effort: {} on failure.
    """
    if not user_id or not lesson_ids:
        return {}
    try:
        rows = db.fetch_all(
            "SELECT unit_id, topic FROM content_units WHERE unit_id = ANY(:uids)",
            {"uids": [f"grammar:{lid}" for lid in lesson_ids]},
        )
        mastery = _mastery_map(user_id, target_lang)
    except Exception:
        return {}
    out: dict[int, float] = {}
    for r in rows:
        m = mastery.get(("grammar", _mastery_topic(r["topic"])))
        if m and m["score"] >= GRAMMAR_ADVANCE_THRESHOLD:
            out[parse_unit_id(r["unit_id"])["lesson_id"]] = m["score"]
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


def languages_with_progress(user_id: str) -> list[str]:
    """Every target_lang this user has any real progress in (a mastery or
    lesson_pointer row) — mastery/srs_state/lesson_pointer are all keyed by
    (user_id, target_lang, ...), so switching the launcher's target-language
    selector never loses anything, it just changes which language's rows the
    rest of the app reads. Used by app.py's quick-switch chips (Natalia,
    2026-09-07: "быстрый переключатель") so a student juggling more than one
    language doesn't have to hunt through the full 14-language dropdown to
    jump back to one they already started."""
    if not user_id:
        return []
    try:
        rows = db.fetch_all(
            "SELECT DISTINCT target_lang FROM mastery WHERE user_id = :uid "
            "UNION "
            "SELECT DISTINCT target_lang FROM lesson_pointer WHERE user_id = :uid",
            {"uid": user_id},
        )
    except Exception:
        return []
    return sorted(r["target_lang"] for r in rows if r["target_lang"])


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
