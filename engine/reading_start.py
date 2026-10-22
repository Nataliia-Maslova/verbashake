"""
engine/reading_start.py — which reading lessons a student who can already
read skips (2026-10-15, Natalia: "букви потрібні тільки для початкового
рівня ... з середнього — одразу з уроків зі словами").

LETTER_LESSONS lists, per reading catalog, the lessons that only teach
letters or syllables (alphabet tables, "MA ME MI", hangul/kana charts,
pinyin initials/finals). Set by hand after reading every catalog's lessons
— the reading lessons' own CEFR tags are positional buckets, not content
(Spanish "PAN PEN PIN" is tagged B2), so they can't decide this.

Lessons that introduce a letter together with real words (Bulgarian
1-25 "Ж ж жаба жена") count as letter lessons too, and so do the word drills
between the letter tables that only practise the letters just taught
(English 2 "Bad Mad Bag", French 3 "bal mal par", Russian 3 "мама папа" —
added 2026-10-22): for a reader they are the alphabet course. Rule-plus-words
lessons (French "É café été", Japanese small っ with words) are kept.

These lessons aren't removed — they stay in the Reading module's own
picker; they're only left out of the "what to read next" order.
"""
from __future__ import annotations

_R = lambda a, b: set(range(a, b + 1))  # noqa: E731

LETTER_LESSONS: dict[str, set[int]] = {
    "en": _R(1, 17) | {19},
    "fr": _R(1, 5),
    "de": _R(1, 7),
    "pt": _R(1, 5),
    "it": _R(1, 5),
    "pl": _R(1, 5),
    "ru": _R(1, 5),
    "nl": _R(1, 5),
    "ca": _R(1, 5),
    "ro": _R(1, 15),
    "cs": _R(1, 15) | {17, 18, 20, 21},
    "tr": _R(1, 9),
    "sv": _R(1, 16),
    "bg": _R(1, 25),
    "uk": _R(1, 47),
    "es": _R(1, 41),
    "ko": _R(1, 56),
    "ja": _R(1, 11) | _R(15, 19),
    "zh": _R(1, 10),
}

_B1_PLUS = {"B1", "B2", "C1", "C2"}


def skips_letters(level: str | None, literacy_required: bool | None) -> bool:
    """True when this student starts reading from word lessons.

    - asked for the letters ("навчи мене літер")  -> letters
    - said "I already know the letters"            -> words, at any level
      (2026-10-22: a zero/A1 student who answered "так, уже знаю букви"
      was still given letter lessons as the in-lesson "Читання" step)
    - B1+                                          -> words
    - zero / A1 / A2 / not answered, no answer     -> letters
    """
    if literacy_required is True:
        return False
    if literacy_required is False:
        return True
    return level in _B1_PLUS


def letter_lessons(lang_code: str) -> set[int]:
    return LETTER_LESSONS.get(lang_code, set())
