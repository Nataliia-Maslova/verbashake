"""
engine/lesson_pairs.py — hand-made table of Grammar lessons students confuse
with each other (2026-10-04, Наталья: the "Пара" Practice exercise mixes
items from the current lesson and one confusable, already-passed lesson, so
the student has to choose between the two forms instead of filling in the
lesson's own form on autopilot).

Hand-made on purpose, not AI-picked: which forms actually compete is a
teaching judgement, and a model picking "related" lessons would pair by
topic similarity, not by what students mix up.

Only lessons that really exist in imlls_database are paired. Her lesson-plan
tense pairs (Past Continuous, Past Perfect, Perfect Continuous, going to vs
will, Future Continuous/Perfect) became possible once lessons 183-190 were
added (2026-10-04).

English target only for now: the curriculum is built on English grammar
categories (LINGUISTIC_AUDIT.md section 1), and most of these contrasts
(Present Simple vs Continuous, many/much, some/any, gerund/infinitive) don't
exist in, say, Ukrainian. Extending a pair to another target means checking
the contrast exists there and adding the language to TARGETS / per-pair.
"""
from __future__ import annotations

TARGETS = frozenset({"English"})

# (lesson_a, lesson_b, contrast) — order doesn't matter; the pair works from
# either side. `contrast` is English, used in the prompt only.
PAIRS: list[tuple[int, int, str]] = [
    # Present Simple vs Present Continuous
    (45, 70, "Present Simple (habits) vs Present Continuous (now)"),
    (57, 71, "Present Simple vs Present Continuous (he/she)"),
    (49, 73, "don't + verb vs am/is/are not + -ing"),
    (58, 73, "doesn't + verb vs isn't + -ing"),
    (50, 74, "Do you...? vs Are you ...-ing?"),
    (59, 74, "Does he...? vs Is he ...-ing?"),
    (51, 75, "What do you do? vs What are you doing?"),
    (60, 75, "What does he do? vs What is he doing?"),
    (63, 76, "Who does it? vs Who is doing it?"),
    (65, 77, "tag questions: don't you? vs aren't you?"),
    # Present Simple vs Past Simple
    (45, 115, "Present Simple vs Past Simple"),
    (49, 132, "don't vs didn't"),
    (50, 133, "Do you...? vs Did you...?"),
    (51, 135, "What do you...? vs What did you...?"),
    (63, 136, "Who does it? vs Who did it?"),
    (65, 138, "tag questions: don't you? vs didn't you?"),
    # Past Simple vs Present Perfect
    (115, 160, "Past Simple vs Present Perfect (just)"),
    (115, 161, "Past Simple (finished time) vs Present Perfect (experience, never/yet)"),
    (132, 161, "didn't vs haven't/hasn't"),
    (133, 162, "Did you...? vs Have you ever...?"),
    (135, 163, "What/where did you...? vs What/where have you...?"),
    (136, 164, "Who did it? vs Who has done it?"),
    (138, 165, "tag questions: didn't you? vs haven't you?"),
    (115, 178, "Past Simple vs used to (past habits)"),
    # Modals
    (85, 91, "can't (not able) vs mustn't (not allowed)"),
    (90, 96, "must vs may"),
    (91, 97, "mustn't vs may not"),
    (90, 140, "must vs have to"),
    (84, 141, "can vs be able to / could"),
    (90, 177, "must (obligation) vs must have (deduction)"),
    # Conditions
    (102, 103, "if vs when"),
    (102, 139, "real condition (if + present) vs hypothetical (if + past, would)"),
    (139, 176, "second vs third conditional"),
    (139, 179, "If I were... vs I wish I were..."),
    # Comparisons and description
    (106, 107, "-er vs more + adjective"),
    (106, 110, "comparative (-er than) vs as...as"),
    (1, 111, "adjective vs adverb"),
    # Quantity, existence, possession
    (31, 34, "how many vs how much"),
    (32, 33, "many/few vs much/little"),
    (36, 39, "there is vs there are"),
    (10, 14, "have vs has"),
    (11, 15, "don't have vs doesn't have"),
    (171, 172, "some vs any"),
    (172, 173, "any vs no / not any"),
    # Verb patterns
    (167, 169, "verb + to-infinitive vs verb + -ing"),
    (168, 170, "verb + to-infinitive vs verb + -ing"),
    # Tense lessons added 2026-10-04 (183-190) — the pairs from her
    # lesson-plan table that had no lessons to pair with before
    (115, 184, "Past Simple vs Past Continuous (I called / I was calling)"),
    (115, 186, "Past Simple vs Past Perfect (I arrived / they had left)"),
    (186, 187, "Past Perfect vs Past Perfect Continuous (result / duration)"),
    (161, 185, "Present Perfect vs Present Perfect Continuous (I've read / I've been reading)"),
    (78, 183, "will (decision now, prediction) vs be going to (plan, evidence)"),
    (188, 189, "Future Continuous vs Future Perfect (will be doing / will have done)"),
    (189, 190, "Future Perfect vs Future Perfect Continuous (result / duration)"),
    # Active vs passive
    (45, 144, "active vs passive (present)"),
    (115, 145, "active vs passive (past)"),
    (78, 146, "active vs passive (future)"),
]


def partners_for(lesson_id: int, target_lang: str) -> list[tuple[int, str]]:
    """[(partner_lesson_id, contrast), ...] for this lesson, in table order."""
    if target_lang not in TARGETS:
        return []
    out = []
    for a, b, contrast in PAIRS:
        if a == lesson_id:
            out.append((b, contrast))
        elif b == lesson_id:
            out.append((a, contrast))
    return out
