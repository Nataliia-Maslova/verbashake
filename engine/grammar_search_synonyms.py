"""
engine/grammar_search_synonyms.py — a curated map from common ESL grammar
terminology ("present continuous", "past simple", "conditionals"...) to the
imlls_database lesson_ids that actually teach it.

Why this exists: search_app.py's fuzzy topic search (rapidfuzz) closes the
*word-form* gap (e.g. Ukrainian "минулий" vs a topic's "минулі" — same root,
different inflection) but not the *terminology* gap — a student searching
"present simple" finds nothing because no lesson topic is literally named
that (imlls_database's 182 lessons are named by pedagogical function —
"Describing things", "Having things — I/you/we" — not by formal grammar
term, see LINGUISTIC_AUDIT.md). This registry bridges that gap for the
terms that map cleanly onto a real cluster of lessons.

Built by hand-inspecting the real topic_en list for all 182 lessons (not
guessed, not Gemini-generated — the lesson_ids below were picked by reading
every topic name in engine.loader.load_phrases()'s output and matching them
to standard ESL terminology), so this file is authoritative for lesson_ids —
scripts/generate_grammar_search_synonym_translations.py only translates the
English terms below into the other 13 languages, it never invents new
lesson_id mappings.

Structure is keyed by target_lang, since the underlying grammar concept
(what lesson_id 69 is "about") never changes with target_lang — the exact
same imlls_database lesson_ids apply whichever language pair the student is
learning, only the sentence *text* is translated per language, not the
grammatical structure of the curriculum. This registry is only meaningful
for the "grammar" module — Vocabulary/Phrasebook/Reading have no comparable
formal-terminology gap (their topics are already plain thematic names like
"Food" or "Greetings", not grammar jargon a fuzzy match could miss).

NO_DEDICATED_LESSON holds terms that are deliberately NOT mapped to any
lesson_id, because the underlying concept isn't a discrete cluster in this
curriculum — "present simple" is the default tense used across most of the
first ~77 lessons (affirmative/negative/question forms of to be/to have/
daily habits), not a topic of its own. Pointing it at an arbitrary lesson
would mislead more than an honest "there's no single lesson for this"
message (search_app.py shows that message instead of a jump link for these).
"""
from __future__ import annotations

# term_key -> {"en": [alias, ...], "lesson_ids": [int, ...]}
GRAMMAR_TERMS: dict[str, dict] = {
    "articles": {
        "en": ["articles", "a an the", "indefinite article", "definite article"],
        "lesson_ids": [35],
    },
    "plurals": {
        "en": ["plurals", "plural nouns", "singular and plural", "irregular plurals"],
        "lesson_ids": list(range(24, 31)),
    },
    "quantifiers": {
        "en": ["quantifiers", "much many", "some any", "countable uncountable nouns"],
        "lesson_ids": [31, 32, 33, 34, 42, 171, 172, 173],
    },
    "imperative": {
        "en": ["imperative", "commands", "giving orders"],
        "lesson_ids": [43, 44],
    },
    "present_continuous": {
        "en": ["present continuous", "present progressive", "-ing form", "ing form"],
        "lesson_ids": list(range(69, 78)),
    },
    "future_simple": {
        "en": ["future simple", "future tense", "will future", "going to future"],
        "lesson_ids": list(range(78, 84)) + [105],
    },
    "modal_can": {
        "en": ["can", "modal can", "ability", "modal verbs of ability"],
        "lesson_ids": list(range(84, 90)),
    },
    "modal_must": {
        "en": ["must", "have to", "obligation", "necessity"],
        "lesson_ids": list(range(90, 96)) + [140],
    },
    "modal_may": {
        "en": ["may", "permission", "modal verbs of permission"],
        "lesson_ids": list(range(96, 101)) + [142],
    },
    "reflexive_pronouns": {
        "en": ["reflexive pronouns", "myself yourself"],
        "lesson_ids": [101],
    },
    "conditionals": {
        "en": ["conditionals", "if clauses", "first conditional", "second conditional",
               "third conditional", "unreal conditionals", "hypothetical situations"],
        "lesson_ids": [102, 103, 104, 105, 139, 176],
    },
    "comparatives_superlatives": {
        "en": ["comparatives", "superlatives", "comparison", "as...as", "comparative adjectives"],
        "lesson_ids": list(range(106, 111)),
    },
    "adverbs": {
        "en": ["adverbs", "adverbs of manner"],
        "lesson_ids": [111, 112],
    },
    "ordinal_numbers": {
        "en": ["ordinal numbers", "ordinals", "first second third"],
        "lesson_ids": [113],
    },
    "past_simple": {
        "en": ["past simple", "simple past", "past tense", "regular verbs past tense",
               "irregular verbs past tense"],
        "lesson_ids": list(range(114, 139)),
    },
    "passive_voice": {
        "en": ["passive voice", "passive", "be + past participle"],
        "lesson_ids": [144, 145, 146, 147, 156, 157, 158, 159, 166],
    },
    "present_perfect": {
        "en": ["present perfect", "have has past participle", "just already yet",
               "life experiences", "ever never"],
        "lesson_ids": list(range(160, 166)),
    },
    "verb_infinitive_gerund": {
        "en": ["gerund", "infinitive", "verb + -ing", "verb + to", "gerund vs infinitive"],
        "lesson_ids": [167, 168, 169, 170],
    },
    "reported_speech": {
        "en": ["reported speech", "indirect speech"],
        "lesson_ids": [174],
    },
    "relative_clauses": {
        "en": ["relative clauses", "who which that", "defining relative clauses"],
        "lesson_ids": [175],
    },
    "modals_deduction": {
        "en": ["modals of deduction", "must have", "might have", "can't have been"],
        "lesson_ids": [177],
    },
    "used_to": {
        "en": ["used to", "past habits", "would past habits"],
        "lesson_ids": [178],
    },
    "wishes": {
        "en": ["wishes", "i wish", "wish clauses"],
        "lesson_ids": [179],
    },
    "phrasal_verbs": {
        "en": ["phrasal verbs"],
        "lesson_ids": [180],
    },
    "causative": {
        "en": ["causative", "have something done", "get something done"],
        "lesson_ids": [181],
    },
}

# Deliberately unmapped — see module docstring. Matching one of these
# aliases should surface an explanation, not a lesson link.
NO_DEDICATED_LESSON: dict[str, list[str]] = {
    "present_simple": ["present simple", "simple present"],
}


def all_english_aliases() -> list[tuple[str, str]]:
    """Flat (term_key, alias) pairs for every English alias in the registry,
    mapped or not — used by the one-time translation script."""
    out = []
    for key, entry in GRAMMAR_TERMS.items():
        for alias in entry["en"]:
            out.append((key, alias))
    for key, aliases in NO_DEDICATED_LESSON.items():
        for alias in aliases:
            out.append((key, alias))
    return out
