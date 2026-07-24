"""
engine/gemini.py — Gemini API integration for IMLLS.

Covers:
  - Phase 1 Розминка:    warmup_question, evaluate_warmup
  - Phase 2 GEC:         correct_grammar  (replaces T5 models)
  - Phase 3 Практика:    generate_practice_test, check_practice_answer
  - Phase 4 Висловлювання: generate_speaking_task, chat_with_tutor, get_hint

Requires: pip install google-generativeai>=0.8.0
Env var:  GEMINI_API_KEY
"""
from __future__ import annotations

import json
import os
import random

import google.generativeai as genai


def _configure():
    """Lazy Gemini config — reads from st.secrets or env at call time."""
    import streamlit as st
    key = (
        st.secrets.get("GEMINI_API_KEY")
        or st.secrets.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY", "")
    )
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found in secrets.toml or environment")
    genai.configure(api_key=key)

def _model(name: str, **kwargs):
    """Configure Gemini lazily and return a GenerativeModel."""
    _configure()
    return genai.GenerativeModel(name, **kwargs)


_FLASH = "gemini-2.5-flash"
_LITE  = "gemini-2.5-flash-lite"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1: Розминка
# ─────────────────────────────────────────────────────────────────────────────

def warmup_question(level: str, target_lang: str, native_lang: str) -> str:
    """Generate ONE proactive warmup question in the target language."""
    topics = [
        "how are you today",
        "what is the weather like",
        "what did you do yesterday",
        "what are your plans for today",
        "describe something you can see around you",
    ]
    topic = random.choice(topics)
    _configure()
    result = _model(_LITE).generate_content(
        f"You are a {target_lang} language teacher. "
        f"Ask ONE simple {level} CEFR level question in {target_lang} about: {topic}. "
        f"One sentence only. No explanation, no translation."
    )
    return result.text.strip()


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
# PHASE 3: Практика — generated tests
# ─────────────────────────────────────────────────────────────────────────────

def generate_practice_test(
    level: str,
    topic: str,
    target_lang: str,
    native_lang: str,
    test_type: str = "fill_in_blank",
    phrases: list[dict] | None = None,
) -> dict:
    """
    Generate a short practice test.

    test_type: "fill_in_blank" | "multiple_choice" | "translation"
    phrases: list of {"target": str, "native": str} from the lesson — if provided,
             questions will be based on these phrases rather than a generic topic.

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
        material_ctx = (
            f"Base the questions ONLY on these phrases from the lesson:\n{phrase_block}\n\n"
        )
    else:
        material_ctx = f"Topic: {topic}.\n\n"

    prompt = (
        f"Create a {level} CEFR {test_type.replace('_', ' ')} test in {target_lang}. "
        f"3–4 items. Write the instructions in {native_lang}.\n\n"
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
        "For fill_in_blank and translation, options should be an empty list []."
    )
    return _parse_json(
        _model(_FLASH).generate_content(prompt).text,
        fallback={"instructions": "", "items": []},
    )


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

def generate_speaking_task(
    level: str,
    topic: str,
    target_lang: str,
    native_lang: str,
) -> str:
    """
    Generate a speaking / writing task with a planning scaffold.

    Returns plain text:
      - Task instruction (in native_lang)
      - 3 planning bullet points (in native_lang) to organize thoughts
      - Example vocabulary / sentence starters (in target_lang)
    """
    _configure()
    result = _model(_FLASH).generate_content(
        f"Create a {level} CEFR speaking or writing task in {target_lang} "
        f"about the topic '{topic}'.\n\n"
        f"Format (plain text only, no JSON):\n"
        f"1. Task instruction in {native_lang} (1–2 sentences).\n"
        f"2. Planning scaffold in {native_lang}: 3 short bullet points to help "
        f"the student organize their thoughts BEFORE speaking.\n"
        f"3. Helpful vocabulary / sentence starters in {target_lang} (3–5 items).\n\n"
        "Keep the whole response under 150 words."
    )
    return result.text.strip()


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


def get_hint(target_phrase: str, target_lang: str, native_lang: str) -> str:
    """
    Return a one-line hint in native_lang for a student who is stuck.
    Gives a key word or grammar tip — NOT a full translation.
    """
    _configure()
    result = _model(_LITE).generate_content(
        f"The student is trying to express this idea in {target_lang}: «{target_phrase}». "
        f"Give ONE short hint in {native_lang}: a key vocabulary word or a grammar tip. "
        f"Do NOT give the full translation or the full sentence. One sentence only."
    )
    return result.text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# YouTube search
# ─────────────────────────────────────────────────────────────────────────────

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


def translate_phrase(phrase: str, from_lang: str, to_lang: str) -> str:
    """Exact translation of a phrase from from_lang into to_lang."""
    _configure()
    result = _model(_LITE).generate_content(
        f"Translate this phrase from {from_lang} to {to_lang}. "
        f"Return ONLY the translation, nothing else.\n\n"
        f"Phrase: {phrase}"
    )
    return result.text.strip()


def get_lesson_topic(phrases: list[dict], target_lang: str, level: str) -> str:
    """
    Given lesson phrases, return a short English grammatical/thematic topic
    suitable as a YouTube search term (e.g. 'irregular past tense verbs', 'food vocabulary').
    Always returns in English regardless of target_lang.
    """
    if not phrases:
        return f"{target_lang} lesson"
    sample = "\n".join(
        f"- {p.get('target', p.get('native', ''))}" for p in phrases[:8]
    )
    result = _model(_LITE).generate_content(
        f"Look at these {target_lang} lesson phrases ({level} CEFR level):\n{sample}\n\n"
        f"What is the main grammar or vocabulary topic of this lesson?\n"
        f"Reply with 2-5 words in ENGLISH only, suitable as a YouTube search query.\n"
        f"Examples: 'irregular past tense verbs', 'present continuous tense', "
        f"'food and drinks vocabulary', 'modal verbs must should'.\n"
        f"Reply with the topic only, no punctuation."
    )
    return result.text.strip()


def generate_youtube_query(
    topic_en: str, phrases: list[dict], target_lang: str, level: str
) -> str:
    """
    Generate a short (3-6 word) YouTube search query optimised for language learning videos.
    Combines the key target-language word/phrase with English context.
    Example output: 'poder no puedo Spanish lesson' or 'Spanish past tense irregular verbs'
    """
    if not phrases:
        return f"{target_lang} {topic_en} lesson"
    targets = [p.get("target", "") for p in phrases[:6] if p.get("target")]
    sample = ", ".join(targets)
    result = _model(_LITE).generate_content(
        f"I need a YouTube search query to find a language learning video.\n"
        f"Language being learned: {target_lang} ({level} CEFR)\n"
        f"Lesson topic: {topic_en}\n"
        f"Key phrases from the lesson: {sample}\n\n"
        f"Write ONE short YouTube search query (3-6 words max).\n"
        f"Rules:\n"
        f"- Include 1-2 key words FROM the lesson phrases (in {target_lang})\n"
        f"- Format: <key phrase> learn {target_lang} lesson\n"
        f"- NO extra words, NO punctuation\n"
        f"Examples: 'no puedo learn Spanish lesson', 'большая собака learn Russian lesson', "
        f"'sein haben learn German lesson'\n"
        f"Reply with the query only."
    )
    return result.text.strip()


def find_youtube_videos(
    topic: str, level: str, lang: str, limit: int = 3,
    sample_phrases: list[str] | None = None,
) -> list[dict]:
    """
    Search YouTube via YouTube Data API v3.
    Requires YOUTUBE_API_KEY in st.secrets or env.
    Returns list of {"title": str, "url": str, "thumbnail": str}.
    """
    import streamlit as st
    import urllib.request, urllib.parse

    api_key = (
        st.secrets.get("YOUTUBE_API_KEY")
        or os.environ.get("YOUTUBE_API_KEY", "")
    )
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY not set")

    _LANG_TO_CODE = {
        "english": "en", "spanish": "es", "german": "de", "french": "fr",
        "italian": "it", "portuguese": "pt", "ukrainian": "uk", "korean": "ko",
        "japanese": "ja", "chinese": "zh", "polish": "pl", "russian": "ru",
    }
    lang_code = _LANG_TO_CODE.get(lang.lower(), "en")

    level_keywords = {
        "A1": "beginner simple slow",
        "A2": "beginner elementary",
        "B1": "intermediate",
        "B2": "upper intermediate",
        "C1": "advanced",
        "C2": "native fluent",
    }
    kw = level_keywords.get(level, "")
    if sample_phrases:
        # sample_phrases already contains a pre-built optimised query string
        query = sample_phrases[0] if len(sample_phrases) == 1 else " ".join(sample_phrases[:4])
    else:
        query = f"{lang} {topic} {kw} lesson".strip()

    params = urllib.parse.urlencode({
        "part":              "snippet",
        "q":                 query,
        "type":              "video",
        "maxResults":        limit,
        "relevanceLanguage": lang_code,
        "key":               api_key,
    })
    url = f"https://www.googleapis.com/youtube/v3/search?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API {e.code}: {body}") from e

    results = []
    for item in data.get("items", []):
        vid_id = item["id"].get("videoId", "")
        snippet = item.get("snippet", {})
        results.append({
            "title":     snippet.get("title", ""),
            "url":       f"https://www.youtube.com/watch?v={vid_id}",
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        })
    return results


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
