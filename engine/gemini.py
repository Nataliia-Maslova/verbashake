"""
engine/gemini.py — Gemini API integration for IMLLS.

Covers:
  - Phase 1 Розминка:    warmup_question, evaluate_warmup
  - Phase 2 GEC:         correct_grammar  (replaces T5 models)
  - Phase 3 Практика:    generate_practice_test, check_practice_answer
  - Phase 4 Висловлювання: generate_open_question, chat_with_tutor

Requires: pip install google-genai>=1.0.0
Env var:  GEMINI_API_KEY

Phase D: every public function here is @_require_paid — free accounts get
zero live Gemini calls (CLAUDE.md decisions #1-#2). See engine/billing.py.
"""
from __future__ import annotations

import functools
import json
import os
import random

import diskcache
from google import genai
from google.genai import types

_cache = diskcache.Cache(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache", "gemini")
)


class PaidFeatureRequired(Exception):
    """Raised when a free-tier user calls a paid-only (live Gemini) feature."""


def _require_paid(fn):
    """
    Phase D: every live Gemini call is paid-only ("free = zero live AI",
    CLAUDE.md decisions #1-#2). Must be the OUTERMOST decorator — i.e. written
    above @_cache.memoize() — so the paid check runs before any cache lookup.
    Otherwise a free user could get a cache hit from a paid user's earlier
    identical call and slip past the gate entirely.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from engine import auth_gate, billing
        if not billing.is_paid(auth_gate.current_user_id()):
            raise PaidFeatureRequired(
                "This feature needs Premium — live AI generation isn't included in the free plan."
            )
        return fn(*args, **kwargs)
    return wrapper

_LANG_NAMES: dict[str, str] = {
    "en": "English", "uk": "Ukrainian", "de": "German", "es": "Spanish",
    "ko": "Korean", "fr": "French", "ja": "Japanese", "zh": "Chinese",
    "pt": "Portuguese", "it": "Italian", "pl": "Polish", "ru": "Russian",
    "ca": "Catalan", "nl": "Dutch",
}


def lang_name(code: str) -> str:
    """Full language name for a 2-letter code, e.g. 'en' -> 'English'."""
    return _LANG_NAMES.get(code, code)


_client: genai.Client | None = None


def _configure():
    """
    Lazy Gemini client init — reads from st.secrets or env at call time,
    cached as a module-level singleton (genai.Client is meant to be reused,
    unlike the old SDK's fire-and-forget genai.configure()). Safe to call
    repeatedly — every _model() call already does, plus a few functions call
    it directly beforehand too; a second call just returns immediately.
    """
    global _client
    if _client is not None:
        return
    import streamlit as st
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
    except Exception:
        secret_key = None
    key = (
        secret_key
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY", "")
    )
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found in secrets.toml or environment")
    _client = genai.Client(api_key=key)


class _ModelHandle:
    """
    Thin shim over google-genai's Client matching the old
    google-generativeai GenerativeModel interface this file's ~15 call
    sites already use -- .generate_content(prompt).text and
    .start_chat(history=[...]).send_message(text).text (chat_with_tutor's
    history format: [{"role": "user"/"model", "parts": ["text"]}]).
    Migrated 2026-08-22 (google-generativeai is deprecated -- CLAUDE.md
    tech debt) by wrapping the new client instead of touching every call
    site, since they're all already funneled through _model().
    """

    def __init__(self, client: genai.Client, name: str, system_instruction: str | None = None):
        self._client = client
        self._name = name
        self._config = (
            types.GenerateContentConfig(system_instruction=system_instruction)
            if system_instruction else None
        )

    def generate_content(self, prompt: str):
        return self._client.models.generate_content(
            model=self._name, contents=prompt, config=self._config,
        )

    def start_chat(self, history: list[dict] | None = None):
        genai_history = [
            types.Content(role=h["role"], parts=[types.Part(text=p) for p in h["parts"]])
            for h in (history or [])
        ]
        return self._client.chats.create(
            model=self._name, config=self._config, history=genai_history,
        )


def _model(name: str, **kwargs):
    """Configure Gemini lazily and return a model handle."""
    _configure()
    return _ModelHandle(_client, name, system_instruction=kwargs.get("system_instruction"))


_FLASH = "gemini-2.5-flash"
_LITE  = "gemini-2.5-flash-lite"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1: Розминка
# ─────────────────────────────────────────────────────────────────────────────

_WARMUP_TOPICS = [
    "how are you today",
    "what is the weather like",
    "what did you do yesterday",
    "what are your plans for today",
    "describe something you can see around you",
    "your hobbies",
    "your family",
    "your favorite food",
    "a recent trip or a place you'd like to visit",
    "your daily routine",
    "your job or studies",
    "your favorite season and why",
    "a movie or show you watched recently",
    "your favorite music",
    "how you get around your city",
    "your plans for the weekend",
    "something that made you happy recently",
    "your favorite way to relax",
    "a skill you'd like to learn",
    "your neighborhood",
]


@_require_paid
def warmup_question(
    level: str, target_lang: str, native_lang: str, bilingual: bool = False,
) -> dict:
    """
    Generate ONE proactive warmup question in the target language.

    bilingual=True also returns the question in native_lang, so a beginner
    can read both at once (CLAUDE.md item 2, 2026-08-20: on A1 the question
    itself is shown in both languages; the student still answers in
    target_lang). Toggleable per call, not hardcoded to a level, so the UI
    can decide when to turn it on.

    Returns: {"target": str, "native": str | None}
    """
    topic = random.choice(_WARMUP_TOPICS)
    return _warmup_question_cached(topic, level, target_lang, native_lang, bilingual)


@_cache.memoize()
def _warmup_question_cached(
    topic: str, level: str, target_lang: str, native_lang: str, bilingual: bool,
) -> dict:
    _configure()
    if not bilingual:
        result = _model(_LITE).generate_content(
            f"You are a {target_lang} language teacher. "
            f"Ask ONE simple {level} CEFR level question in {target_lang} about: {topic}. "
            f"One sentence only. No explanation, no translation."
        )
        return {"target": result.text.strip(), "native": None}

    prompt = (
        f"You are a {target_lang} language teacher. "
        f"Ask ONE simple {level} CEFR level question in {target_lang} about: {topic}. "
        f"One sentence only.\n\n"
        f"Return JSON only — no markdown fences:\n"
        "{\n"
        f'  "target": "the question in {target_lang}",\n'
        f'  "native": "the same question translated into {native_lang}"\n'
        "}"
    )
    result = _model(_LITE).generate_content(prompt)
    parsed = _parse_json(result.text, fallback=None)
    if not parsed or not parsed.get("target"):
        # Fall back to a target-only question rather than surfacing a parse error.
        return {"target": result.text.strip(), "native": None}
    return parsed


@_require_paid
def evaluate_warmup(
    answer: str,
    question: str,
    target_lang: str,
    level: str,
    native_lang: str,
) -> dict:
    """
    Evaluate the student's warmup answer.

    Returns:
        {
          "feedback": str,   # one encouraging sentence in native_lang
          "errors": [
            {"original": str, "corrected": str, "explanation": str,
             "native_prompt": str}  # phrase to use when asking student to retry
          ]
        }
    """
    prompt = (
        f"The student is learning {target_lang} at {level} CEFR level.\n"
        f"Question asked (in {target_lang}): «{question}»\n"
        f"Student answer: «{answer}»\n\n"
        f"Return JSON only — no markdown fences:\n"
        "{\n"
        f'  "feedback": "one encouraging sentence in {native_lang}",\n'
        '  "errors": [\n'
        '    {\n'
        '      "original": "the incorrect phrase as the student wrote it",\n'
        '      "corrected": "the correct version in target language",\n'
        f'      "explanation": "one short line in {native_lang}",\n'
        f'      "native_prompt": "the meaning of the phrase in {native_lang} — used to ask student to retry"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "If there are no errors, return an empty errors array."
    )
    return _parse_json(
        _model(_FLASH).generate_content(prompt).text,
        fallback={"feedback": "", "errors": []},
    )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2: Grammar correction  (replaces T5 GEC models)
# ─────────────────────────────────────────────────────────────────────────────

@_require_paid
@_cache.memoize()
def correct_grammar(text: str, target_lang: str, native_lang: str) -> dict:
    """
    Correct grammar errors in *text* (written in target_lang).

    Returns:
        {
          "corrected": str,
          "errors": [
            {"original": str, "fixed": str, "explanation": str,
             "native_prompt": str}
          ]
        }
    """
    prompt = (
        f"Correct GRAMMAR errors only in this {target_lang} text.\n"
        f"IGNORE: punctuation, capitalization, missing periods/commas, sentence fragments caused by pauses.\n"
        f"Only flag real grammar mistakes (wrong verb form, wrong word, missing article, wrong tense, etc.).\n"
        f"CRITICAL: The \"native_prompt\" field MUST be written in {native_lang}, NOT in {target_lang}.\n"
        f"native_prompt is the {native_lang} TRANSLATION of the corrected phrase, used to ask the student to retry.\n"
        f"Return JSON only — no markdown fences:\n"
        "{\n"
        '  "corrected": "full corrected text",\n'
        '  "errors": [\n'
        '    {\n'
        '      "original": "the incorrect word or phrase as written",\n'
        f'      "fixed": "the corrected word or short phrase in {target_lang}",\n'
        f'      "explanation": "one short grammar tip in {native_lang}",\n'
        f'      "native_prompt": "translation of the corrected phrase into {native_lang} — MUST be in {native_lang} only"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "If there are no real grammar errors, return empty errors array.\n"
        f"Text: {text}"
    )
    return _parse_json(
        _model(_LITE).generate_content(prompt).text,
        fallback={"corrected": text, "errors": []},
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 (New Material): rule explanation — CLAUDE.md idea A, 2026-08-23
# ─────────────────────────────────────────────────────────────────────────────

@_require_paid
@_cache.memoize()
def explain_lesson_rule(
    topic: str, level: str, target_lang: str, native_lang: str,
    seed_phrases: list[str],
) -> dict:
    """
    Rule + examples + exceptions for the grammar point a lesson teaches,
    shown at Step 1 ("Read out loud") which otherwise just lists translated
    phrases with no explanation of the pattern behind them.

    Persistently cached in Postgres (lesson_explanations, schema.sql), same
    "pay once for the whole project" pattern as translate_phrase's
    phrase_translations: (topic, level, target_lang, native_lang) is the
    same for EVERY student who opens this lesson, so this is a one-time
    Gemini cost per lesson×language pair, not per pageview or per user --
    no daily quota needed on top of @_require_paid, unlike a free-form
    tutor chat would need.

    seed_phrases: a few real example sentences from the lesson, for context
    only (same "for reference, write NEW ones" framing as
    generate_practice_test -- the returned examples should illustrate the
    rule freshly, not just restate the lesson's own sentences).

    Returns:
        {
          "rule": str,                                    # in native_lang
          "examples": [{"target": str, "native": str}],    # 2-4 new pairs
          "exceptions": [str]                              # in native_lang, may be empty
        }
    """
    cached = _lesson_explanation_from_db(topic, level, target_lang, native_lang)
    if cached is not None:
        return cached

    example_block = "\n".join(f"  - {s}" for s in seed_phrases[:4])
    context_note = (
        f"Real {target_lang} example sentences from this lesson (ground your "
        f"explanation in these -- write NEW ones below, don't just repeat "
        f"them):\n{example_block}\n\n"
        if example_block else ""
    )
    prompt = (
        f"THE LANGUAGE BEING TAUGHT (the one you must explain) is "
        f"{target_lang}. The student's NATIVE language, to write your "
        f"explanation in, is {native_lang}. Do not swap these.\n\n"
        f"You are a {target_lang} teacher explaining a grammar point to a "
        f"{level} CEFR student whose native language is {native_lang}.\n"
        f"Grammar topic label: \"{topic}\" -- this label may be borrowed "
        f"from English grammar terminology (this app's curriculum was "
        f"originally built from English grammar categories). Your job is "
        f"to explain how {target_lang} itself expresses this idea, NOT to "
        f"explain English grammar -- unless target_lang is literally "
        f"English, never mention English grammar rules. If {target_lang} "
        f"has no direct equivalent of this English-derived category, say so "
        f"briefly and explain what {target_lang} actually does instead to "
        f"express the same meaning.\n\n"
        f"{context_note}"
        f"Explain the rule simply enough for {level} level, write the "
        f"explanation in {native_lang}. Give 2-4 NEW example sentences in "
        f"{target_lang} (each with a {native_lang} translation) that "
        f"illustrate the rule. List common exceptions or mistakes learners "
        f"make with this rule, in {native_lang} -- an empty list if there "
        f"genuinely are none, don't invent one.\n\n"
        "Return JSON only — no markdown fences:\n"
        "{\n"
        f'  "rule": "explanation in {native_lang}, about {target_lang} grammar",\n'
        f'  "examples": [{{"target": "... in {target_lang}", "native": "... in {native_lang}"}}],\n'
        '  "exceptions": ["..."]\n'
        "}"
    )
    result = _parse_json(
        _model(_FLASH).generate_content(prompt).text,
        fallback={"rule": "", "examples": [], "exceptions": []},
    )
    _save_lesson_explanation_to_db(topic, level, target_lang, native_lang, result)
    return result


def _explanation_hash(topic: str, level: str, target_lang: str, native_lang: str) -> str:
    import hashlib
    return hashlib.sha256(
        f"{target_lang}|{native_lang}|{level}|{topic}".encode("utf-8")
    ).hexdigest()


def _lesson_explanation_from_db(topic: str, level: str, target_lang: str, native_lang: str) -> dict | None:
    try:
        from engine import db
        row = db.fetch_one(
            "SELECT explanation FROM lesson_explanations WHERE explanation_hash = :h",
            {"h": _explanation_hash(topic, level, target_lang, native_lang)},
        )
        return row["explanation"] if row else None
    except Exception:
        return None  # DATABASE_URL not configured, or DB unreachable -- fall through to a live call


def _save_lesson_explanation_to_db(
    topic: str, level: str, target_lang: str, native_lang: str, explanation: dict,
) -> None:
    try:
        from engine import db
        db.upsert(
            "lesson_explanations",
            keys={"explanation_hash": _explanation_hash(topic, level, target_lang, native_lang)},
            values={
                "topic": topic, "level": level, "target_lang": target_lang,
                "native_lang": native_lang, "explanation": json.dumps(explanation),
            },
            touch_updated_at=False,
        )
    except Exception:
        pass  # best-effort -- an explanation that isn't persisted just gets redone later


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3: Практика — generated tests
# ─────────────────────────────────────────────────────────────────────────────

_MODULE_FOCUS = {
    "grammar": (
        "Focus on GRAMMAR: correct verb forms/tense, endings, word order, "
        "articles, prepositions. Test whether the student can build the "
        "sentence correctly, not just whether they know the words."
    ),
    "vocab": (
        "Focus on VOCABULARY: correct word choice and natural word usage in "
        "context. Test whether the student picks/uses the right word, not "
        "grammar structure — keep sentence structure simple."
    ),
    "phrasebook": (
        "Focus on PHRASES AND COLLOCATIONS: correct, natural set expressions "
        "and word combinations used in real situations (greetings, requests, "
        "small talk). Test whether the student recognizes/produces the right "
        "phrase for the context, not an isolated grammar rule — keep sentence "
        "structure simple, the same way vocab tests do."
    ),
}

# Extra guidance for test_types that need more than the generic "create a
# {type} test" framing to come out right (CLAUDE.md, 2026-08-22 — the
# classic ESL-workbook exercise formats found in Golitsynskyi/Murphy/
# Cambridge: transform a sentence into a different grammatical form, not
# just fill a gap or pick an option).
_TEST_TYPE_GUIDANCE = {
    "sentence_transformation": (
        "This is a SENTENCE TRANSFORMATION drill (the classic grammar-book "
        "exercise — active <-> passive, statement -> question, "
        "positive <-> negative, direct -> reported speech, present -> past, "
        "or a similar rewrite — pick whichever transformation actually fits "
        "the grammar being practiced, and vary it across items rather than "
        "repeating the same one four times). Each item's \"question\" is "
        "the ORIGINAL sentence plus a short instruction of which "
        "transformation to apply (e.g. \"Rewrite in the passive: The chef "
        "cooked the meal.\"); \"answer\" is the correctly transformed "
        "sentence."
    ),
}


@_require_paid
def generate_practice_test(
    level: str,
    topic: str,
    target_lang: str,
    native_lang: str,
    test_type: str = "fill_in_blank",
    phrases: list[dict] | None = None,
    module: str = "grammar",
) -> dict:
    """
    Generate a short practice test.

    test_type: "fill_in_blank" | "multiple_choice" | "translation"
    phrases: list of {"target": str, "native": str} — questions are based on
             these rather than a generic topic. Callers may mix in phrases
             from other lessons (e.g. weak-mastery/overdue-SRS topics via
             engine.recommender) alongside the current lesson's own phrases —
             this function doesn't care which lesson each one came from.
    module: "grammar" | "vocab" | "phrasebook" — picks which dimension the
            test emphasizes, since a single generic prompt can't test all
            of them well at once (CLAUDE.md item 5, 2026-08-20; phrasebook
            added 2026-08-22).

    Returns:
        {
          "instructions": str,   # in native_lang
          "items": [
            {
              "question": str,
              "answer": str,
              "options": [str, ...]   # only for multiple_choice
            }
          ]
        }
    """
    if phrases:
        phrase_block = "\n".join(
            f"  - {p['target']} = {p['native']}" for p in phrases
        )
        # "For reference only, write NEW sentences" (not "base ONLY on these
        # phrases") — the old wording pinned the model to literally
        # rephrasing the same ~7-8 lesson sentences, so switching test_type
        # (or clicking "New exercise") just reformatted identical content
        # instead of producing genuinely different practice (CLAUDE.md,
        # 2026-08-22 — same fix already applied in
        # generate_lesson_construction_drill's prompt).
        material_ctx = (
            f"These phrases show the grammar pattern and vocabulary level to "
            f"practice (for reference only — do not reuse them verbatim, "
            f"write NEW original sentences in the same style):\n{phrase_block}\n\n"
        )
    else:
        material_ctx = f"Topic: {topic}.\n\n"

    focus    = _MODULE_FOCUS.get(module, "")
    guidance = _TEST_TYPE_GUIDANCE.get(test_type, "")

    prompt = (
        f"Create a {level} CEFR {test_type.replace('_', ' ')} test in {target_lang}. "
        f"3–4 items. Write the instructions in {native_lang}.\n"
        f"{focus}\n"
        f"{guidance}\n\n"
        + material_ctx +
        "Return JSON only — no markdown fences:\n"
        "{\n"
        '  "instructions": "...",\n'
        '  "items": [\n'
        '    {\n'
        '      "question": "...",\n'
        '      "answer": "...",\n'
        '      "options": ["...", "...", "...", "..."]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "For fill_in_blank, translation, and sentence_transformation, "
        "options should be an empty list []."
    )
    return _parse_json(
        _model(_FLASH).generate_content(prompt).text,
        fallback={"instructions": "", "items": []},
    )


@_require_paid
def generate_lesson_construction_drill(
    lesson_id: int,
    topic: str,
    seed_phrases: list[str],
    user_level: str,
    native_lang: str,
    target_lang: str = "English",
    n: int = 5,
) -> dict:
    """
    Drill a Grammar lesson's construction using fresh, level-appropriate
    vocabulary instead of imlls_database's fixed 7-8 example phrases — the
    "construction + level-appropriate vocabulary" idea from CLAUDE.md
    (2026-08-21). Works for any of the 182 Grammar lessons: the pattern is
    normally inferred from the lesson's own topic + a few of its own example
    sentences (seed_phrases) — no per-lesson authoring needed.

    target_lang=="English" uses engine.cefr_wordlist's real CEFR+POS word
    list — the strict, most accurate path, hard-constraining which nouns/
    verbs/adjectives Gemini may use. Any other target_lang (CLAUDE.md,
    2026-08-22: no equivalent open CEFR+POS list exists for uk/es/ko, and
    realistically may never for some of them) falls back to a plain
    instruction to use simple, common target_lang vocabulary for the level
    -- looser (Gemini judges "simple" itself, not a hard list) but works for
    every language today instead of staying an English-only pilot.

    topic / seed_phrases: caller supplies these (e.g. from
    engine.loader.get_lesson_topics / engine.loader.get_lesson, already in
    target_lang) — same pattern as generate_practice_test's `phrases`
    param; this function doesn't touch the database directly.

    A lesson_id registered in engine.constructions (a known defect in that
    lesson's own phrases, e.g. 139's "however, ..." padding) uses its manual
    override description INSTEAD of seed_phrases, so the defect isn't
    replicated into every generated drill.

    Returns: {"items": [{"target": str, "native": str}, ...]}
    """
    from engine import constructions

    override = constructions.override_for_lesson(lesson_id)
    if override:
        pattern_block = f"{override['name']} — {override['description']}\n{override['constraints']}"
        pos_slots = override["pos_slots"]
    else:
        example_block = "\n".join(f"  - {s}" for s in seed_phrases[:4])
        pattern_block = (
            f"Grammar topic: {topic}\n"
            f"Example sentences illustrating the pattern (for reference only — "
            f"do not reuse these exact sentences or their vocabulary):\n{example_block}"
        )
        pos_slots = ["noun", "verb", "adjective"]

    if target_lang == "English":
        from engine import cefr_wordlist
        word_pool = {
            pos: cefr_wordlist.words_for_level(user_level, pos=pos, limit=25)
            for pos in pos_slots
        }
        pool_block = "\n".join(
            f"  - {pos}: {', '.join(words)}" for pos, words in word_pool.items() if words
        )
        vocab_instruction = (
            f"Use ONLY the following words as content vocabulary (nouns/verbs/"
            f"adjectives) — you may freely use basic function words (pronouns, "
            f"articles, prepositions, auxiliaries) not listed here:\n{pool_block}"
        )
    else:
        vocab_instruction = (
            f"Use simple, common {target_lang} vocabulary that a {user_level} "
            f"CEFR-level student would already know — everyday words, no "
            f"advanced or specialized terms."
        )

    prompt = (
        f"Generate {n} example sentences in {target_lang} that practice this "
        f"grammar pattern:\n{pattern_block}\n\n"
        f"The student's level is {user_level}. {vocab_instruction}\n\n"
        "Return JSON only — no markdown fences:\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        f'      "target": "sentence in {target_lang}",\n'
        f'      "native": "translation in {native_lang}"\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    return _parse_json(
        _model(_FLASH).generate_content(prompt).text,
        fallback={"items": []},
    )


@_require_paid
def generate_target_grammar_drill(
    title: str,
    description: str,
    level: str,
    native_lang: str,
    target_lang: str,
    n: int = 5,
) -> dict:
    """
    Drill a grammar point from engine.target_grammar_paths -- topics genuine
    to target_lang that imlls_database has no lesson for at all (verbal
    aspect for Slavic languages, ser/estar and the subjunctive for Romance
    languages, particles and speech levels for Japanese/Korean, German's
    case system, Chinese aspect markers... see LINGUISTIC_AUDIT.md section 1
    for why the 182-lesson curriculum can't cover these: it was built from
    English grammar categories, and these have no English equivalent to
    translate from).

    Same shape and same "construction + level-appropriate vocabulary" idea
    as generate_lesson_construction_drill, but there's no imlls_database
    lesson_id / seed_phrases to infer the pattern from -- title+description
    (from the registry) ARE the seed. No engine.cefr_wordlist path either:
    that list is English-only, so every target_lang here uses the same
    "simple, common vocabulary for the level" instruction
    generate_lesson_construction_drill already falls back to for non-English
    targets.

    Returns: {"items": [{"target": str, "native": str}, ...]}
    """
    prompt = (
        f"Generate {n} example sentences in {target_lang} that practice this "
        f"grammar point, which is specific to {target_lang} and has no direct "
        f"English equivalent:\n{title} -- {description}\n\n"
        f"The student's level is {level}. Use simple, common {target_lang} "
        f"vocabulary that a {level} CEFR-level student would already know.\n\n"
        "Return JSON only — no markdown fences:\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        f'      "target": "sentence in {target_lang}",\n'
        f'      "native": "translation in {native_lang}"\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    return _parse_json(
        _model(_FLASH).generate_content(prompt).text,
        fallback={"items": []},
    )


@_require_paid
def check_practice_answer(
    question: str,
    student_answer: str,
    correct_answer: str,
    target_lang: str,
    native_lang: str,
) -> dict:
    """
    Check a free-text practice answer.

    Returns:
        {"correct": bool, "feedback": str}   # feedback in native_lang
    """
    prompt = (
        f"Question: «{question}»\n"
        f"Expected answer: «{correct_answer}»\n"
        f"Student answer: «{student_answer}»\n\n"
        f"IMPORTANT: Write EVERY part of your response in {native_lang} only. "
        f"Is the student's answer correct or acceptably close? "
        f"Return JSON only — no markdown fences:\n"
        "{\n"
        '  "correct": true,\n'
        f'  "feedback": "one short encouraging or explanatory sentence in {native_lang}"\n'
        "}"
    )
    return _parse_json(
        _model(_LITE).generate_content(prompt).text,
        fallback={"correct": False, "feedback": ""},
    )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4: Висловлювання — speaking task + tutor chat
# ─────────────────────────────────────────────────────────────────────────────

@_require_paid
def generate_open_question(
    topic: str,
    seed_phrases: list[str],
    level: str,
    target_lang: str,
    native_lang: str,
    bilingual: bool = False,
) -> dict:
    """
    Cambridge Vocabulary in Use "Over to you" style: ONE open, personal
    question in target_lang tied to the lesson the student just did, not a
    random topic from a fixed pool (CLAUDE.md, 2026-08-22 — the previous
    generate_speaking_task picked from data/speaking_topics.yaml, unrelated
    to the lesson). No planning scaffold or vocabulary list — the student
    answers freely, in their own words; SOS-help and chat-with-tutor already
    cover support.

    topic / seed_phrases: caller supplies these (same pattern as
    generate_practice_test's `phrases` param) — this function doesn't touch
    the database directly.

    Not cached (like generate_practice_test / generate_lesson_construction_drill):
    caching by (topic, seed_phrases, ...) would make the "New task" button
    return the identical question every time for the same lesson.

    bilingual=True also returns the question in native_lang from the same
    call (mirrors warmup_question's bilingual pattern) so an A1 student can
    read both; the student still answers in target_lang.

    Returns: {"target": str, "native": str | None}
    """
    _configure()
    example_block = "\n".join(f"  - {s}" for s in seed_phrases[:4])
    examples_note = (
        f"\nExample sentences from this lesson (for context only — do not "
        f"reuse them verbatim):\n{example_block}\n"
        if example_block else ""
    )
    task = (
        f"You are a {target_lang} language teacher. The student just studied "
        f"the topic '{topic}' at {level} CEFR level.{examples_note}\n"
        f"Ask ONE open, personal question in {target_lang} that invites the "
        f"student to talk about their own life using this topic — like the "
        f"'Over to you' questions in Cambridge Vocabulary in Use. "
        f"One sentence only."
    )
    if not bilingual:
        result = _model(_FLASH).generate_content(
            f"{task} No explanation, no scaffold, no vocabulary list."
        )
        return {"target": result.text.strip(), "native": None}

    prompt = (
        f"{task}\n\n"
        f"Return JSON only — no markdown fences:\n"
        "{\n"
        f'  "target": "the question in {target_lang}",\n'
        f'  "native": "the same question translated into {native_lang}"\n'
        "}"
    )
    result = _model(_FLASH).generate_content(prompt)
    parsed = _parse_json(result.text, fallback=None)
    if not parsed or not parsed.get("target"):
        return {"target": result.text.strip(), "native": None}
    return parsed


@_require_paid
def chat_with_tutor(
    history: list[dict],
    user_msg: str,
    target_lang: str,
    level: str,
    native_lang: str,
) -> str:
    """
    Continue a conversation with the AI language tutor.

    history format: [{"role": "user"/"model", "parts": ["text"]}]

    The tutor:
    - Replies only in target_lang
    - Keeps responses to 2–3 sentences
    - Silently rephrases errors in its own reply (does not call them out)
    - Encourages the student to keep talking
    """
    _configure()
    model = _model(
        _FLASH,
        system_instruction=(
            f"You are a friendly, encouraging {target_lang} language tutor. "
            f"The student's level is {level} CEFR. "
            f"ALWAYS reply in {target_lang} only — never switch to {native_lang}. "
            f"Keep every reply to 2–3 sentences. "
            f"If the student makes a grammar mistake, seamlessly rephrase their "
            f"idea correctly in your reply without pointing out the error explicitly. "
            f"End each reply with a short follow-up question to keep the conversation going."
        ),
    )
    chat = model.start_chat(history=history)
    return chat.send_message(user_msg).text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────────

@_require_paid
@_cache.memoize()
def suggest_alternatives(
    native_prompt: str, target_lang: str, native_lang: str
) -> list[str]:
    """Return 2-3 natural ways to express native_prompt in target_lang."""
    _configure()
    result = _model(_LITE).generate_content(
        f"Give 2-3 natural ways to say the following in {target_lang}.\n"
        f"Phrase (in {native_lang}): «{native_prompt}»\n\n"
        f"Return ONLY a numbered list (1. ... 2. ... 3. ...), no extra text."
    )
    lines = [l.strip() for l in result.text.strip().splitlines() if l.strip()]
    # strip leading "1. " "2. " etc.
    import re
    return [re.sub(r"^\d+\.\s*", "", l) for l in lines if l]


@_require_paid
@_cache.memoize()
def translate_phrase(phrase: str, from_lang: str, to_lang: str) -> str:
    """
    Exact translation of a phrase from from_lang into to_lang.

    Two cache layers (CLAUDE.md, 2026-08-22): @_cache.memoize() (local disk,
    .cache/gemini/) is fast for repeat calls within the same running
    process, but Streamlit Cloud's disk is ephemeral -- wiped on every
    redeploy, same exposure mastery/SRS/gamification had before moving to
    Supabase. phrase_translations (schema.sql) is the persistent layer that
    actually survives a redeploy, so re-opening a CEFR-J Vocabulary lesson
    (engine.cefr_j_vocab_loader — the main caller now) after a deploy
    doesn't re-pay Gemini for every word all over again.
    """
    cached = _translation_from_db(phrase, from_lang, to_lang)
    if cached is not None:
        return cached
    _configure()
    result = _model(_LITE).generate_content(
        f"Translate this phrase from {from_lang} to {to_lang}. "
        f"Return ONLY the translation, nothing else.\n\n"
        f"Phrase: {phrase}"
    ).text.strip()
    _save_translation_to_db(phrase, from_lang, to_lang, result)
    return result


def _translation_hash(phrase: str, from_lang: str, to_lang: str) -> str:
    import hashlib
    return hashlib.sha256(f"{from_lang}|{to_lang}|{phrase}".encode("utf-8")).hexdigest()


def _translation_from_db(phrase: str, from_lang: str, to_lang: str) -> str | None:
    try:
        from engine import db
        row = db.fetch_one(
            "SELECT translation FROM phrase_translations WHERE phrase_hash = :h",
            {"h": _translation_hash(phrase, from_lang, to_lang)},
        )
        return row["translation"] if row else None
    except Exception:
        return None  # DATABASE_URL not configured, or DB unreachable -- fall through to a live call


def _save_translation_to_db(phrase: str, from_lang: str, to_lang: str, translation: str) -> None:
    try:
        from engine import db
        db.upsert(
            "phrase_translations",
            keys={"phrase_hash": _translation_hash(phrase, from_lang, to_lang)},
            values={"from_lang": from_lang, "to_lang": to_lang,
                    "phrase": phrase, "translation": translation},
            touch_updated_at=False,
        )
    except Exception:
        pass  # best-effort -- a translation that isn't persisted just gets redone later


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str, fallback: dict) -> dict:
    """Parse Gemini JSON response, stripping markdown fences if present."""
    try:
        t = text.strip()
        if t.startswith("```"):
            parts = t.split("```")
            t = parts[1] if len(parts) > 1 else parts[0]
            if t.startswith("json"):
                t = t[4:]
        return json.loads(t.strip())
    except Exception:
        return fallback
