# IMLLS Refactor — Implementation Prompt

## Context

Streamlit-based language learning app (Python). Key files:
- `grammar.py` — main lesson flow, 8 numbered steps (`step1`–`step8`)
- `engine/gec.py` — T5-based GEC (to be replaced with Gemini)
- `engine/stt.py` — Whisper STT (to be replaced with Google Cloud STT)
- `engine/session.py`, `engine/scorer.py`, `engine/logger.py` — keep unchanged
- `engine/adaptive.py`, `engine/gamification.py`, `engine/tts.py` — keep unchanged
- `reading_app.py`, `custom_app.py` — not in scope

---

## New lesson structure (5 phases)

The existing 8-step flow becomes **Phase 2**. Three new phases wrap around it:

```
Фаза 1: Розминка / Warmup       ← NEW
Фаза 2: Новий матеріал          ← existing steps 1–8 (GEC → Gemini only)
Фаза 3: Практика                ← NEW (Gemini-generated tests)
Фаза 4: Висловлювання           ← NEW (Gemini chat + strategy prompt + hint/translation buttons)
Фаза 5: Підсумок                ← NEW (stats + spaced repetition suggestions)
```

The app shows a top-level phase switcher (tabs or pills) so the student always
knows which phase they are in.

### Error correction flow (pedagogical principle)

Errors are collected **silently during each phase**. At the **end of each phase**,
before the "Continue →" button appears, the student goes through a short correction round:

1. Show: "Перед тим як продовжити — давай повторимо 🔧"
2. For each error: ask student to produce the phrase again —
   *"Як сказати [phrase in native language] мовою, яку ти вивчаєш?"*
3. Student answers (text or audio)
4. **If correct** → "✅ Чудово!" — NO explanation (success reinforces itself)
5. **If still wrong** → show correction + one-line explanation
6. Only AFTER all errors reviewed → "Continue →" becomes active

This uses the teacher's method: rephrase via a question, explain only when
the error persists on the correction attempt.

---

## Change 1 — Create `engine/gemini.py`

```python
"""
engine/gemini.py — Gemini API integration for IMLLS.
"""
from __future__ import annotations
import json, os, random
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_FLASH = "gemini-2.0-flash"
_LITE  = "gemini-2.5-flash-lite"


# ── PHASE 1: Розминка ─────────────────────────────────────────────────────

def warmup_question(level: str, target_lang: str, native_lang: str) -> str:
    """Generate ONE proactive warmup question in target language."""
    topics = [
        "how are you today",
        "what is the weather like",
        "what did you do yesterday",
        "what are your plans for today",
        "describe something around you",
    ]
    topic = random.choice(topics)
    result = genai.GenerativeModel(_LITE).generate_content(
        f"You are a {target_lang} teacher. Ask ONE simple {level} CEFR question "
        f"in {target_lang} about: {topic}. One sentence only. No explanation."
    )
    return result.text.strip()


def evaluate_warmup(
    answer: str, question: str,
    target_lang: str, level: str, native_lang: str
) -> dict:
    """
    Evaluate student's warmup answer.
    Returns {"feedback": str, "errors": [{"original", "corrected", "explanation"}]}
    feedback and explanations are in native_lang.
    """
    prompt = (
        f"The student is learning {target_lang} at {level} CEFR.\n"
        f"Question: «{question}»\nAnswer: «{answer}»\n\n"
        f"Return JSON only (no markdown):\n"
        '{"feedback": "one encouraging sentence in ' + native_lang + '", '
        '"errors": [{"original": "...", "corrected": "...", "explanation": "one line in ' + native_lang + '"}]}\n'
        "Empty errors list if no mistakes."
    )
    return _parse_json(genai.GenerativeModel(_FLASH).generate_content(prompt).text,
                       fallback={"feedback": "", "errors": []})


# ── PHASE 2: GEC replacement (replaces T5 models) ────────────────────────

def correct_grammar(text: str, target_lang: str, native_lang: str) -> dict:
    """
    Correct grammar. Returns:
    {"corrected": str, "errors": [{"original", "fixed", "explanation"}]}
    """
    prompt = (
        f"Correct this {target_lang} text. Return JSON only (no markdown):\n"
        '{"corrected": "...", "errors": [{"original": "...", "fixed": "...", '
        '"explanation": "one line in ' + native_lang + '"}]}\n'
        f"Text: {text}"
    )
    return _parse_json(genai.GenerativeModel(_LITE).generate_content(prompt).text,
                       fallback={"corrected": text, "errors": []})


# ── PHASE 3: Практика — generated tests ───────────────────────────────────

def generate_practice_test(
    level: str, topic: str, target_lang: str, native_lang: str,
    test_type: str = "fill_in_blank"
) -> dict:
    """
    Generate a short practice test.
    test_type: "fill_in_blank" | "multiple_choice" | "translation"
    Returns {"instructions": str, "items": [{"question": str, "answer": str, ...}]}
    """
    prompt = (
        f"Create a {level} CEFR {test_type} test in {target_lang} about '{topic}'. "
        f"3–4 items. Instructions in {native_lang}.\n"
        f"Return JSON only:\n"
        '{"instructions": "...", "items": [{"question": "...", "answer": "...", '
        '"options": ["...", "...", "...", "..."]}]}\n'
        '(options only needed for multiple_choice, otherwise empty list)'
    )
    return _parse_json(genai.GenerativeModel(_FLASH).generate_content(prompt).text,
                       fallback={"instructions": "", "items": []})


def check_practice_answer(
    question: str, student_answer: str, correct_answer: str,
    target_lang: str, native_lang: str
) -> dict:
    """Check a free-text practice answer. Returns {"correct": bool, "feedback": str}"""
    prompt = (
        f"Question: «{question}»\nExpected: «{correct_answer}»\nStudent: «{student_answer}»\n"
        f"Is the student's answer correct or acceptable? Return JSON only:\n"
        '{"correct": true/false, "feedback": "one line in ' + native_lang + '"}'
    )
    return _parse_json(genai.GenerativeModel(_LITE).generate_content(prompt).text,
                       fallback={"correct": False, "feedback": ""})


# ── PHASE 4: Висловлювання — chat tutor ───────────────────────────────────

def generate_speaking_task(
    level: str, topic: str, target_lang: str, native_lang: str
) -> str:
    """Generate a speaking/writing task with a planning prompt."""
    result = genai.GenerativeModel(_FLASH).generate_content(
        f"Create a {level} CEFR speaking or writing task in {target_lang} about '{topic}'. "
        f"Task instruction in {native_lang}. "
        f"Then add a short planning scaffold: 3 bullet points in {native_lang} to help the student "
        f"organize their thoughts BEFORE speaking. "
        f"Return plain text only."
    )
    return result.text.strip()


def chat_with_tutor(
    history: list[dict], user_msg: str,
    target_lang: str, level: str, native_lang: str
) -> str:
    """
    Continue a tutor conversation.
    history: [{"role": "user"/"model", "parts": ["..."]}]
    """
    model = genai.GenerativeModel(
        _FLASH,
        system_instruction=(
            f"You are a friendly {target_lang} tutor. "
            f"Student level: {level} CEFR. "
            f"Reply ONLY in {target_lang}. Keep replies to 2–3 sentences. "
            f"If the student makes a grammar mistake, rephrase their sentence correctly "
            f"in your reply — do not explicitly point out the error. "
            f"Encourage the student to keep talking."
        ),
    )
    return model.start_chat(history=history).send_message(user_msg).text.strip()


# ── PHASE 4: Hint / translation when stuck ───────────────────────────────

def get_hint(target_phrase: str, target_lang: str, native_lang: str) -> str:
    """One-line hint in native language — a key word or grammar tip, NOT a full translation."""
    result = genai.GenerativeModel(_LITE).generate_content(
        f"The student is trying to express this in {target_lang}: «{target_phrase}». "
        f"Give ONE short hint in {native_lang} — a key word or grammar tip. "
        f"Do NOT give the full translation. One sentence only."
    )
    return result.text.strip()


# ── Utility ───────────────────────────────────────────────────────────────

def _parse_json(text: str, fallback: dict) -> dict:
    try:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("```")[1]
            if t.startswith("json"):
                t = t[4:]
        return json.loads(t.strip())
    except Exception:
        return fallback
```

---

## Change 2 — Replace `engine/stt.py` (Whisper → Google Cloud STT)

Replace entire file:

```python
"""
engine/stt.py — Google Cloud Speech-to-Text (replaces Whisper).
Requires: pip install google-cloud-speech
Env var:  GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
"""
from __future__ import annotations
import os
import streamlit as st

_LANG_CODES: dict[str, str] = {
    "en": "en-US", "uk": "uk-UA", "de": "de-DE", "es": "es-ES",
    "ko": "ko-KR", "fr": "fr-FR", "ja": "ja-JP", "zh": "zh-CN",
    "pt": "pt-BR", "it": "it-IT", "pl": "pl-PL", "ru": "ru-RU",
}

@st.cache_resource(show_spinner=False)
def _get_client():
    from google.cloud import speech
    return speech.SpeechClient()


def transcribe_bytes(audio_bytes: bytes, language: str | None = None) -> str:
    try:
        from google.cloud import speech
        client = _get_client()
        bcp47  = _LANG_CODES.get(language or "en", "en-US")
        audio  = speech.RecognitionAudio(content=audio_bytes)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,
            language_code=bcp47,
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio)
        return " ".join(
            r.alternatives[0].transcript for r in response.results if r.alternatives
        ).strip()
    except Exception as e:
        st.warning(f"[STT] {e}")
        return ""


def transcribe_file(file_path: str, language: str | None = None) -> str:
    with open(file_path, "rb") as f:
        return transcribe_bytes(f.read(), language)


def whisper_available() -> bool:
    return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
```

---

## Change 3 — Replace `engine/gec.py` (T5 → Gemini shim)

Replace entire file. Keep the same function signatures so nothing else in `grammar.py` breaks:

```python
"""
engine/gec.py — GEC via Gemini (T5 models removed).
Same public API as before: correct(), gec_available().
"""
from __future__ import annotations

_LANG_NAMES = {
    "en": "English", "uk": "Ukrainian", "de": "German", "es": "Spanish",
    "ko": "Korean",  "fr": "French",    "ja": "Japanese","zh": "Chinese",
    "pt": "Portuguese","it": "Italian", "pl": "Polish",  "ru": "Russian",
}


def correct(text: str, lang: str = "en", native_lang: str = "en") -> str:
    """Return corrected text. Backward-compatible string interface."""
    from engine.gemini import correct_grammar
    result = correct_grammar(text, _LANG_NAMES.get(lang, lang), _LANG_NAMES.get(native_lang, native_lang))
    return result.get("corrected", text)


def correct_with_details(text: str, lang: str = "en", native_lang: str = "en") -> dict:
    """Return full dict with errors list."""
    from engine.gemini import correct_grammar
    return correct_grammar(text, _LANG_NAMES.get(lang, lang), _LANG_NAMES.get(native_lang, native_lang))


def gec_available(lang: str = "en") -> bool:
    return True  # all languages supported via Gemini


def supported_languages() -> list:
    return list(_LANG_NAMES.keys())
```

Remove from `requirements.txt`:
```
transformers
torch
```

Add to `requirements.txt`:
```
google-generativeai>=0.8.0
google-cloud-speech>=2.27.0
```

---

## Change 4 — Add phases to `grammar.py`

### 4a. Deferred error buffer helpers (add near top of grammar.py, after imports)

```python
# ── Deferred error collection ─────────────────────────────────────────────
def _init_errors(phase_key: str):
    key = f"errors_{phase_key}"
    if key not in st.session_state:
        st.session_state[key] = []

def _collect_error(original: str, corrected: str, explanation: str, phase_key: str,
                   native_prompt: str = ""):
    """
    Collect one error silently during a phase.
    native_prompt: the native-language phrase used to ask for retry
                   (e.g. «як сказати "Ich bin müde"?»).
    """
    key = f"errors_{phase_key}"
    _init_errors(phase_key)
    if original.strip() != corrected.strip():
        st.session_state[key].append({
            "original":      original,
            "corrected":     corrected,
            "explanation":   explanation,
            "native_prompt": native_prompt or corrected,  # fallback: show corrected form
        })

def _get_errors(phase_key: str) -> list:
    return st.session_state.get(f"errors_{phase_key}", [])

def _clear_errors(phase_key: str):
    st.session_state.pop(f"errors_{phase_key}", None)
    st.session_state.pop(f"errors_{phase_key}_review_idx", None)
    st.session_state.pop(f"errors_{phase_key}_review_done", None)
```

### 4a2. Error review widget (shown at end of each phase before "Continue →")

```python
def _phase_error_review(phase_key: str, wh_lang: str, target_lang: str,
                        native_lang: str) -> bool:
    """
    Interactive correction round at the end of a phase.
    Returns True when all errors have been reviewed (or there are none).
    """
    errors = _get_errors(phase_key)
    if not errors:
        return True  # no errors → proceed immediately

    review_key = f"errors_{phase_key}_review_idx"
    done_key   = f"errors_{phase_key}_review_done"

    if st.session_state.get(done_key):
        return True

    idx = st.session_state.get(review_key, 0)
    if idx >= len(errors):
        st.session_state[done_key] = True
        _clear_errors(phase_key)
        return True

    err = errors[idx]
    total = len(errors)

    st.markdown(f"### 🔧 Перевір себе — {idx + 1} / {total}")
    st.info(
        f"Як сказати **{err['native_prompt']}** мовою, яку ти вивчаєш?\n\n"
        f"Напиши або запиши голосом."
    )

    mode = st.radio("", ["⌨️ Текст", "🎙️ Голос"], horizontal=True,
                    key=f"rev_mode_{phase_key}_{idx}")
    student_retry = None

    if mode == "⌨️ Текст":
        student_retry = st.text_input("Твоя відповідь:", key=f"rev_text_{phase_key}_{idx}")
        submitted = st.button("Перевірити", key=f"rev_submit_{phase_key}_{idx}")
    else:
        audio = audio_input(f"rev_{phase_key}_{idx}")
        submitted = bool(audio) and st.button("Перевірити",
                                              key=f"rev_submit_{phase_key}_{idx}")
        if submitted and audio:
            student_retry = transcribe_bytes(audio, language=wh_lang)
            st.markdown(f"**Ти сказав:** {student_retry}")

    if submitted and student_retry:
        from engine.gemini import correct_grammar
        check = correct_grammar(student_retry, target_lang, native_lang)
        if not check.get("errors"):
            st.success("✅ Чудово! Правильно.")
        else:
            st.error(f"❌ Правильно: **{err['corrected']}**")
            if err.get("explanation"):
                st.info(err["explanation"])

        if st.button("Далі →", key=f"rev_next_{phase_key}_{idx}"):
            st.session_state[review_key] = idx + 1
            st.rerun()

    return False  # still in review
```

### 4b. Phase 1 — Розминка (new function, add before step1)

```python
def phase1_warmup(session: LessonSession, tts_lang: str, wh_lang: str) -> bool:
    """
    Phase 1: Warmup — Gemini asks a proactive question, student answers via audio.
    Errors collected silently for Phase 5 summary.
    """
    from engine.gemini import warmup_question, evaluate_warmup
    native_lang = session.state.native_lang
    target_lang = session.state.target_lang
    lesson_id   = session.state.lesson_id
    level = "A1" if lesson_id <= 30 else "A2" if lesson_id <= 70 else "B1"

    _init_errors()
    st.markdown("## 🌅 Розминка")
    st.caption("Стратегія: відповідай вільно — не бійся помилок, головне спробувати.")

    if "warmup_q" not in st.session_state:
        with st.spinner("Generating question…"):
            st.session_state["warmup_q"] = warmup_question(level, target_lang, native_lang)

    st.markdown(f"### 💬 {st.session_state['warmup_q']}")

    audio = audio_input("warmup")
    if audio and st.button("Submit", type="primary", key="warmup_submit"):
        with st.spinner("Transcribing…"):
            answer = transcribe_bytes(audio, language=wh_lang)
        if answer:
            st.markdown(f"**You said:** {answer}")
            with st.spinner("Evaluating…"):
                result = evaluate_warmup(answer, st.session_state["warmup_q"],
                                         target_lang, level, native_lang)
            st.info(result.get("feedback", ""))
            for err in result.get("errors", []):
                _collect_error(err["original"], err["corrected"],
                               err.get("explanation", ""), "Розминка")
            st.session_state["warmup_done"] = True

    if st.session_state.get("warmup_done"):
        # Error review before moving on
        if _phase_error_review("warmup", wh_lang, target_lang, native_lang):
            if st.button("Continue to lesson →", type="primary", key="warmup_next"):
                st.session_state.pop("warmup_q", None)
                st.session_state.pop("warmup_done", None)
                return True
    return False
```

### 4c. Phase 3 — Практика (new function, add after step8)

```python
def phase3_practice(session: LessonSession, tts_lang: str, wh_lang: str) -> bool:
    """
    Phase 3: Practice — Gemini-generated test based on lesson topic and level.
    Student answers, errors collected for summary.
    """
    from engine.gemini import generate_practice_test, check_practice_answer, correct_grammar
    native_lang = session.state.native_lang
    target_lang = session.state.target_lang
    topic       = getattr(session.state, "topic", "daily life") or "daily life"
    lesson_id   = session.state.lesson_id
    level = "A1" if lesson_id <= 30 else "A2" if lesson_id <= 70 else "B1"

    st.markdown("## 📝 Практика")

    test_type = st.selectbox(
        "Test type", ["fill_in_blank", "multiple_choice", "translation"],
        format_func={"fill_in_blank": "Fill in the blank",
                     "multiple_choice": "Multiple choice",
                     "translation": "Translation"}.get,
        key="p3_type"
    )

    if "p3_test" not in st.session_state or st.button("Generate new test", key="p3_regen"):
        with st.spinner("Generating test…"):
            st.session_state["p3_test"]    = generate_practice_test(
                level, topic, target_lang, native_lang, test_type)
            st.session_state["p3_answers"] = {}
            st.session_state["p3_checked"] = False

    test = st.session_state["p3_test"]
    st.markdown(f"**{test.get('instructions', '')}**")

    for i, item in enumerate(test.get("items", [])):
        st.markdown(f"**{i+1}.** {item['question']}")
        if test_type == "multiple_choice" and item.get("options"):
            choice = st.radio("", item["options"], key=f"p3_q{i}", label_visibility="collapsed")
            st.session_state["p3_answers"][i] = choice
        else:
            ans = st.text_input("Your answer:", key=f"p3_q{i}")
            st.session_state["p3_answers"][i] = ans

    if st.button("Check answers", type="primary", key="p3_check"):
        st.session_state["p3_results"] = []
        for i, item in enumerate(test.get("items", [])):
            student_ans = st.session_state["p3_answers"].get(i, "")
            result = check_practice_answer(
                item["question"], student_ans, item["answer"], target_lang, native_lang)
            st.session_state["p3_results"].append(result)
            if not result["correct"]:
                _collect_error(student_ans, item["answer"],
                               result.get("feedback", ""), "Практика")
        st.session_state["p3_checked"] = True

    if st.session_state.get("p3_checked"):
        for i, res in enumerate(st.session_state.get("p3_results", [])):
            icon = "✅" if res["correct"] else "❌"
            st.markdown(f"{icon} **{i+1}.** {res.get('feedback', '')}")

        # Error review before advancing
        if _phase_error_review("practice", wh_lang, target_lang, native_lang):
            if st.button("Continue to Висловлювання →", type="primary", key="p3_next"):
                st.session_state.pop("p3_test", None)
                st.session_state.pop("p3_answers", None)
                st.session_state.pop("p3_results", None)
                st.session_state.pop("p3_checked", None)
                return True
    return False
```

### 4d. Phase 4 — Висловлювання (new function, add after phase3_practice)

```python
def phase4_expression(session: LessonSession, tts_lang: str, wh_lang: str) -> bool:
    """
    Phase 4: Expression — student plans, then speaks/writes freely.
    Errors collected for summary. Gemini tutor available for chat.
    """
    from engine.gemini import generate_speaking_task, chat_with_tutor, correct_grammar
    native_lang = session.state.native_lang
    target_lang = session.state.target_lang
    topic       = getattr(session.state, "topic", "daily life") or "daily life"
    lesson_id   = session.state.lesson_id
    level = "A1" if lesson_id <= 30 else "A2" if lesson_id <= 70 else "B1"

    st.markdown("## 🗣️ Висловлювання")
    st.info(
        "💡 **Стратегія:** Спершу склади короткий план, тоді пиши/говори; "
        "не бійся помилок — головне висловити думку, а відшліфувати можна потім."
    )

    if "p4_task" not in st.session_state:
        with st.spinner("Generating speaking task…"):
            st.session_state["p4_task"]         = generate_speaking_task(
                level, topic, target_lang, native_lang)
            st.session_state["p4_chat_history"] = []
            st.session_state["p4_submitted"]    = False

    st.markdown(st.session_state["p4_task"])
    st.markdown("---")

    # ── Answer: text or audio ─────────────────────────────────────────────
    if not st.session_state.get("p4_submitted"):
        mode = st.radio("Input:", ["⌨️ Text", "🎙️ Voice"], horizontal=True, key="p4_mode")
        answer = None
        if mode == "⌨️ Text":
            answer = st.text_area("Write your response:", key="p4_text")
            if st.button("Submit & Chat with tutor", type="primary", key="p4_text_go"):
                st.session_state["p4_answer"] = answer
        else:
            audio = audio_input("p4_voice")
            if audio and st.button("Submit voice", type="primary", key="p4_voice_go"):
                with st.spinner("Transcribing…"):
                    st.session_state["p4_answer"] = transcribe_bytes(audio, language=wh_lang)
                st.markdown(f"**You said:** {st.session_state['p4_answer']}")

        if "p4_answer" in st.session_state:
            with st.spinner("Checking grammar…"):
                correction = correct_grammar(
                    st.session_state["p4_answer"], target_lang, native_lang)
            for err in correction.get("errors", []):
                _collect_error(err["original"], err["fixed"],
                               err.get("explanation", ""), "Висловлювання")
            st.caption("Grammar checked — errors saved for summary.")
            st.session_state["p4_submitted"] = True
            st.rerun()

    # ── Chat with tutor ───────────────────────────────────────────────────
    if st.session_state.get("p4_submitted"):
        st.markdown("### 💬 Chat with your tutor")
        st.caption("Continue the conversation in the target language. Tutor will gently correct you.")

        for msg in st.session_state["p4_chat_history"]:
            role = "You" if msg["role"] == "user" else "Tutor"
            st.markdown(f"**{role}:** {msg['parts'][0]}")

        # ── Hint / translation buttons ────────────────────────────────────
        # Show above the chat input so student can get help before typing.
        # target_phrase: most recent tutor message or task phrase.
        _last_tutor = next(
            (m["parts"][0] for m in reversed(st.session_state["p4_chat_history"])
             if m["role"] == "model"), st.session_state.get("p4_task", "")
        )
        col_hint, col_trans = st.columns(2)
        with col_hint:
            if st.button("💡 Підказка", key="p4_hint"):
                from engine.gemini import get_hint
                st.info(get_hint(_last_tutor, target_lang, native_lang))
        with col_trans:
            if st.button("🔤 Переклад", key="p4_trans"):
                # Ask Gemini for a translation of the last tutor message
                import google.generativeai as genai
                translation = genai.GenerativeModel("gemini-2.0-flash").generate_content(
                    f"Translate this {target_lang} text to {native_lang} in one sentence: "
                    f"«{_last_tutor}»"
                ).text
                st.warning(translation)

        user_input = st.chat_input("Your message…", key="p4_chat")
        if user_input:
            with st.spinner("Tutor is typing…"):
                reply = chat_with_tutor(
                    st.session_state["p4_chat_history"],
                    user_input, target_lang, level, native_lang)
            st.session_state["p4_chat_history"] += [
                {"role": "user",  "parts": [user_input]},
                {"role": "model", "parts": [reply]},
            ]
            st.rerun()

        st.markdown("---")
        # Error review before finishing
        if _phase_error_review("expression", wh_lang, target_lang, native_lang):
            if st.button("Finish lesson →", type="primary", key="p4_finish"):
                st.session_state.pop("p4_task", None)
                st.session_state.pop("p4_answer", None)
                st.session_state.pop("p4_chat_history", None)
                st.session_state.pop("p4_submitted", None)
                return True
    return False
```

### 4e. Phase 5 — Підсумок (new function)

```python
def phase5_summary(session: LessonSession) -> bool:
    """
    Phase 5: Summary — lesson stats only.
    Errors were already reviewed at the end of each phase (not repeated here).
    """
    st.markdown("## 🏁 Підсумок уроку")
    st.success("🎉 Урок завершено! Всі помилки вже опрацьовано після кожної фази.")

    # ── Lesson stats ──────────────────────────────────────────────────────
    st.markdown("### 📊 Статистика")

    # These come from the existing session/logger — read the same way
    # on_lesson_complete() currently does at the end of step8.
    state = session.state
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Урок", f"#{state.lesson_id}")
    with col2:
        # Total phrases practiced (from session)
        n_phrases = len(session.phrases())
        st.metric("Фраз опрацьовано", n_phrases)
    with col3:
        # Pull best score from session log if available
        best = getattr(state, "best_score", None)
        if best is not None:
            st.metric("Найкращий результат", f"{int(best * 100)}%")

    st.markdown("---")

    # ── Call existing gamification hook ───────────────────────────────────
    # Same call you currently make at the end of step8:
    from engine.gamification import on_lesson_complete
    on_lesson_complete(state.user_id)

    if st.button("🏠 Back to main menu", type="primary", key="p5_done"):
        return True
    return False
```

### 4f. Wire phases into `main()` in `grammar.py`

In the `main()` function, wrap the existing step dispatch with a phase-level state machine.
Add a `lesson_phase` key to `st.session_state` alongside the existing `lesson_step`:

```python
# At the start of the lesson (after session is initialised):
if "lesson_phase" not in st.session_state:
    st.session_state["lesson_phase"] = 1   # start at Phase 1: Warmup

phase = st.session_state["lesson_phase"]

# Phase header (replace with your UI style)
PHASE_LABELS = {
    1: "🌅 Розминка",
    2: "📖 Новий матеріал",
    3: "📝 Практика",
    4: "🗣️ Висловлювання",
    5: "🏁 Підсумок",
}
st.markdown(
    " · ".join(
        f"**{v}**" if k == phase else f"<span style='color:grey'>{v}</span>"
        for k, v in PHASE_LABELS.items()
    ),
    unsafe_allow_html=True,
)
st.markdown("---")

# Phase dispatch
if phase == 1:
    if phase1_warmup(sess, tts_lang, wh_lang):
        st.session_state["lesson_phase"] = 2
        st.rerun()

elif phase == 2:
    # --- existing 8-step logic unchanged ---
    # When step8 returns True (lesson complete), advance phase:
    #   st.session_state["lesson_phase"] = 3
    #   st.session_state.pop("lesson_step", None)   # reset step counter
    #   st.rerun()
    pass  # keep existing step dispatch here, just add the phase advance at the end

elif phase == 3:
    if phase3_practice(sess, tts_lang, wh_lang):
        st.session_state["lesson_phase"] = 4
        st.rerun()

elif phase == 4:
    if phase4_expression(sess, tts_lang, wh_lang):
        st.session_state["lesson_phase"] = 5
        st.rerun()

elif phase == 5:
    if phase5_summary(sess):
        # Reset everything for next lesson
        st.session_state["lesson_phase"] = 1
        st.session_state.pop("lesson_step", None)
        st.rerun()
```

Also reset `lesson_phase` when a new lesson is selected (same place you currently reset `lesson_step`).

---

## What does NOT change

- `step1` through `step8` functions — unchanged except:
  - `step8`: replace `gec_correct()` calls with `correct()` from new `engine/gec.py` (same API, works automatically)
  - `SUPPORTED_GEC_LANGS` check in `step8` — remove it; `gec_available()` now returns `True` for all languages
- `REQUIRED_STEPS`, `STEPS` dict, adaptive engine — unchanged
- All CSS, Mova design system, gamification, TTS — unchanged

---

## Environment variables (add to `.env`)

```
GEMINI_API_KEY=your_gemini_key_here
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-service-account.json
```
