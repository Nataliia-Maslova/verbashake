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
1-25 "Ж ж жаба жена") count as letter lessons too: for a reader they are
the alphabet course. Rule-plus-words lessons (French "É café été",
Japanese small っ with words) are kept.

These lessons aren't removed — they stay in the Reading module's own
picker; they're only left out of the "what to read next" order.
"""
from __future__ import annotations

_R = lambda a, b: set(range(a, b + 1))  # noqa: E731

LETTER_LESSONS: dict[str, set[int]] = {
    "en": {1, 3, 8, 16},
    "fr": {1, 2, 4},
    "de": {1, 2, 4, 6, 7},
    "pt": {1, 2, 4},
    "it": {1, 2, 4},
    "pl": {1, 2, 4},
    "ru": {1, 2, 4},
    "nl": {1, 2, 4},
    "ca": {1, 2, 4},
    "ro": {1, 2, 4, 6, 8, 10, 12, 14},
    "cs": {1, 2, 3, 4, 6, 8, 10, 12, 14, 17, 20},
    "tr": {1, 2, 4, 6, 8},
    "sv": {1, 2, 4, 6, 8, 10, 12, 14, 16},
    "bg": _R(1, 25),
    "uk": _R(1, 47),
    "es": _R(1, 41),
    "ko": _R(1, 56),
    "ja": _R(1, 11) | _R(15, 19),
    "zh": _R(1, 10),
}

_BEGINNER = {"zero", "A1"}
_B1_PLUS = {"B1", "B2", "C1", "C2"}


def skips_letters(level: str | None, literacy_required: bool | None) -> bool:
    """True when this student starts reading from word lessons.

    - asked for the letters ("навчи мене літер")  -> letters
    - level zero / A1 / not answered               -> letters
    - B1+                                          -> words
    - A2 who said "I can already read"             -> words
    """
    if literacy_required is True or not level or level in _BEGINNER:
        return False
    return level in _B1_PLUS or literacy_required is False


def letter_lessons(lang_code: str) -> set[int]:
    return LETTER_LESSONS.get(lang_code, set())
