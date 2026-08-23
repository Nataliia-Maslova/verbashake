"""
engine/constructions.py — manual overrides for the "construction + level-
vocabulary" drill engine (CLAUDE.md, 2026-08-21), keyed by Grammar lesson_id
(imlls_database_with_titles.xlsx, "lessons" sheet).

Most of the 173 Grammar lessons need NO entry here: the pattern is derived
automatically from the lesson's own topic_en + example phrases (see
engine.gemini.generate_lesson_construction_drill). An override exists only
where a lesson's own example phrases carry a defect that would otherwise get
baked into every generated drill — e.g. lesson 139 pads every example with
an unrelated "however, ..." clause explaining why the condition is false.

Add an entry here only after finding a concrete problem with a lesson's own
phrases, not preemptively for every lesson.
"""
from __future__ import annotations

CONSTRUCTIONS: dict[int, dict] = {
    139: {
        "name": "Second Conditional",
        "cefr_level": "B1",
        "description": (
            "hypothetical/unreal present or future: "
            "'If + subject + past simple, subject + would + base verb (+ object)' "
            "— e.g. 'If I had a car, I would drive to work.'"
        ),
        "pos_slots": ["noun", "verb", "adjective"],
        "constraints": (
            "Each item must be a SINGLE if/would sentence only. Do NOT add a "
            "second sentence explaining why the condition is untrue (no "
            "'however, ...' clause) — imlls_database lesson 139 does this and "
            "it tests grammar beyond this construction."
        ),
    },
}


def override_for_lesson(lesson_id: int) -> dict | None:
    return CONSTRUCTIONS.get(lesson_id)
