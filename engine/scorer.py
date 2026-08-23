"""
Scorer — text normalization and similarity scoring using RapidFuzz.
"""
import re
from rapidfuzz import fuzz

PASS_THRESHOLD = 0.82   # 82% similarity = correct


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def similarity(user_input: str, expected: str) -> float:
    """Return similarity score 0.0–1.0."""
    a = normalize(user_input)
    b = normalize(expected)
    if not a or not b:
        return 0.0
    return fuzz.ratio(a, b) / 100.0


def evaluate(user_input: str, expected: str) -> dict:
    """Full evaluation result dict."""
    score = similarity(user_input, expected)
    return {
        "transcribed": user_input,
        "expected":    expected,
        "score":       round(score, 4),
        "passed":      score >= PASS_THRESHOLD,
    }


def similarity_flexible(user_input: str, expected: str) -> float:
    """
    Word-order/synonym-tolerant similarity, for grading a free-form
    translation against a single reference answer (placement_quiz) — plain
    `similarity()` is a whole-string edit-distance ratio, so an equally
    valid phrasing that just reorders words (e.g. "libro malo" vs "mal
    libro") scores far lower than it should. Takes the best of plain,
    word-order-normalized, and word-set overlap ratios, so any of the three
    ways a correct paraphrase can differ from the reference is tolerated.
    Not used for reading/practice grading, where the reference IS the
    literal text the student is reproducing and word order matters.
    """
    a, b = normalize(user_input), normalize(expected)
    if not a or not b:
        return 0.0
    return max(
        fuzz.ratio(a, b),
        fuzz.token_sort_ratio(a, b),
        fuzz.token_set_ratio(a, b),
    ) / 100.0


def evaluate_flexible(user_input: str, expected: str) -> dict:
    """Full evaluation result dict using similarity_flexible()."""
    score = similarity_flexible(user_input, expected)
    return {
        "transcribed": user_input,
        "expected":    expected,
        "score":       round(score, 4),
        "passed":      score >= PASS_THRESHOLD,
    }
