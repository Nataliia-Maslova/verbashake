"""
engine/i18n.py — localized strings for the 8-step practice flow.

Step titles are action verbs ("Read out loud", "Translate aloud") and hints
are short emoji formulas ("🎧 → ⏸ → 🎤") so they read fast at A1-B1 level.
Each step has one icon and an activity-type tag that drives the colour of
its left border in the UI.

Strings are organised by language code. English and Ukrainian are fully
hand-written below; Spanish/Korean are hand-written for their most-visible
~13 keys only. CLAUDE.md 2026-08-22: every other key/language (including
the 10 languages with no hand-written bucket at all -- French, German,
Japanese, Chinese, Portuguese, Italian, Polish, Russian, Catalan, Dutch)
used to silently fall back to English with no indication anything was
missing (_code() had no LANG_TO_CODE entry for them). Now
data/i18n_generated.json (scripts/generate_i18n_strings.py's one-time batch
translation output) is merged in at import time to fill exactly the gaps,
never overwriting a hand-written entry -- see _load_generated() below.

``get(lang, key, step)`` still falls back to English for any key genuinely
missing from both (e.g. data/i18n_generated.json hasn't been generated/run
yet, or a brand-new key was added to "en" but not translated).
"""
from __future__ import annotations

import json
from pathlib import Path

# Same 14-language name->code mapping as engine/loader.py / engine/vocab_loader.py.
LANG_TO_CODE = {
    "English":    "en",
    "Ukrainian":  "uk",
    "Spanish":    "es",
    "Korean":     "ko",
    "French":     "fr",
    "German":     "de",
    "Japanese":   "ja",
    "Chinese":    "zh",
    "Portuguese": "pt",
    "Italian":    "it",
    "Polish":     "pl",
    "Russian":    "ru",
    "Catalan":    "ca",
    "Dutch":      "nl",
}

# Big icon shown next to the step title. Universal across languages.
STEP_ICONS = {
    1: "👀",
    2: "🎧",
    3: "🎧",
    4: "⚡",
    5: "🗣️",
    6: "🔄",
    7: "⚡",
    8: "✍️",
}

# Activity type → drives the left-border colour of the step header.
STEP_TYPES = {
    1: "reading",
    2: "listening",
    3: "matching",
    4: "reading",
    5: "listening",
    6: "translation",
    7: "translation",
    8: "composing",
}

# Hex colour per type (used in CSS).
TYPE_COLORS = {
    "reading":     "#5060c0",
    "listening":   "#8050b0",
    "matching":    "#40a0a0",
    "translation": "#40a060",
    "composing":   "#c06080",
}

# Per-language strings.
STRINGS = {
    "en": {
        "step_label": "STEP",
        "required":   "required",
        "try_first":  "Complete the exercise first",
        "main_menu":  "🏠 Main menu",
        # Launcher (app.py) -- was hardcoded English regardless of the
        # student's native language, mismatched against the fully-localized
        # 8-step flow right below it (design review, 2026-08-23).
        "native_language": "🌐 Native language",
        "target_language": "🎯 Target language",
        "start_prefix":    "Start",
        "word_lesson":     "Lesson",
        "word_phrase":     "Phrase",
        "word_unit":       "Unit",
        "no_lessons_yet":  "No lessons yet",
        # Placement-quiz / mastery recommendation banner (grammar.py::render_setup)
        "rec_reason_revisit":    "revisit {word} {lid} to shore up a weaker topic before moving on",
        "rec_reason_skip_ahead": "skip ahead to {word} {lid} — you're tracking ahead of it already",
        "rec_banner_main":       "💡 Your placement quiz / recent activity suggests you {reason} ({level}). Your saved place at {word} {cur_lid} is untouched — this is just a suggestion.",
        "rec_jump_button":       "Jump to {lid} →",
        # Phase labels
        "phase_warmup":    "Warmup",
        "phase_material":  "New Material",
        "phase_practice":  "Practice",
        "phase_speaking":  "Speaking",
        "phase_video":     "🎬 Video",
        # Phase UI
        "skip":            "Skip →",
        "next":            "Next →",
        "generate_exercise": "▶ Generate exercise",
        "generate_task":   "▶ Generate task",
        "rule_explanation_title": "📖 Explain the rule",
        "rule_explanation_btn":   "▶ Explain this rule",
        "rule_exceptions_label":  "Watch out for:",
        "new_exercise":    "🔄 New",
        "error_review_title": "🔍 Error review",
        "error_review_start": "Start correction →",
        "check_self":      "🔧 Check yourself",
        "how_to_say":      "How to say",
        "in_target_lang":  "in the language you're learning?",
        "write_or_record": "Write or record your answer.",
        "answer_label":    "Your answer:",
        "check_btn":       "Check",
        "correct":         "✅ Correct!",
        "try_again":       "❌ Try again. Options:",
        "next_btn":        "Next →",
        "video_title":     "🎬 Videos for review",
        "video_search_label": "YouTube search query:",
        "video_search_btn":   "🔍 Find videos",
        "video_new_search":   "🔄 New search",
        "video_not_found":    "No videos found. Try changing the topic.",
        "video_beyond_curated": "🎬 At this level, the best practice is real content made for native speakers — watch a show, movie, or video you'd genuinely enjoy.",
        "video_channels_intro": "Explore these channels for more practice at your level:",
        "video_ai_search_title": "🔍 Or find your own, on your own topic",
        "video_ai_search_intro": "Copy this prompt into ChatGPT, Gemini, or any AI chat to get video suggestions that match your level *and* your interests:",
        "video_ai_search_interest_label": "Your interests (optional — makes the prompt more specific)",
        "video_ai_search_interest_placeholder": "e.g. football, cooking, video games, true crime…",
        "video_open":         "🔗 Open on YouTube",
        "to_main_menu":       "Back to main menu →",
        "sos_label":          "🆘 SOS & HELP — translation",
        "sos_placeholder":    "Type a phrase to translate…",
        "translate_btn":      "Translate",
        "translation_result": "Translation",
        # Phase 1 — Warmup
        "warmup_title":      "🌅 Warmup",
        "warmup_strategy":   "Strategy: answer freely — don't be afraid of mistakes, just try. We'll review them before the next phase.",
        "no_errors":         "✅ Great — no errors found!",
        "error_breakdown":   "🔍 Error review",
        "answer_method":     "Answer method",
        "voice_opt":         "🎙️ Voice",
        "text_opt":          "⌨️ Text",
        "warmup_bilingual_toggle": "🌐 Show the question in my language too",
        "step8_errors_title":  "✏️ Corrections found — pick what to practice",
        "step8_no_errors":     "✓ All phrases are grammatically correct!",
        "practice_selected_btn": "Practice selected →",
        "select_all":           "Select all",
        "error_drill_title":       "✍️ Practice it",
        "error_drill_instruction": "Write or say 2-3 new phrases using the same word, phrase, or structure.",
        "error_drill_input_label": "Your phrases (one per line):",
        # Phase 3 — Practice
        "practice_title":    "📝 Practice",
        "test_type_label":   "Test type",
        "fill_in_blank":     "Fill in the blank",
        "multiple_choice":   "Multiple choice",
        "translation_type":  "Translation",
        "sentence_transformation": "Sentence transformation (grammar-only)",
        "construction_drill": "Construction drill (fresh, grammar-only)",
        "target_grammar":    "Language-specific grammar (beyond English)",
        "target_grammar_topic_label": "Topic",
        "generating_ex":     "Generating exercise…",
        # Phase 4 — Speaking
        "speaking_title":    "Speaking",
        "speaking_strategy": "Strategy: first make a short plan, then write/speak; don't worry about mistakes — express your ideas, you can polish them later.",
        "mode_label":        "Method",
        "enter_phrase_hint": "Type a phrase to translate…",
        "no_audio_warning":  "Please record your voice first.",
        "write_answer":      "Write your answer:",
        "you_asked":         "You asked:",
        "new_btn":           "🔄 New",
        # Phase 5 — Video caption
        "level_label":       "Level",
        "lang_label":        "Language",
        "topic_label":       "Topic",
        "titles": {
            1: "Read out loud",
            2: "Listen, then repeat",
            3: "Hear it, pick the translation",
            4: "Read as fast as you can",
            5: "Echo the speaker",
            6: "Translate aloud",
            7: "Translate as fast as you can",
            8: "Make your own sentences",
        },
        "hints": {
            1: "👀 Read every phrase. Both languages are shown.",
            2: "🎧 Listen → ⏸ pause → 🎤 repeat each phrase.",
            3: "🎧 Listen → 👆 tap the correct translation.",
            4: "⚡ Read all phrases fast. Speed = recording length.",
            5: "🎧🗣️ Speak along with the audio — like an echo.",
            6: "🔄 See your language, say the target language.",
            7: "⚡🔄 Translate every phrase as fast as you can.",
            8: "✍️ Create new phrases. AI will check the grammar.",
        },
    },
    "uk": {
        "step_label": "КРОК",
        "required":   "обов'язковий",
        "try_first":  "Спочатку виконай завдання",
        "main_menu":  "🏠 Головне меню",
        # Launcher (app.py)
        "native_language": "🌐 Рідна мова",
        "target_language": "🎯 Мова, яку вивчаєш",
        "start_prefix":    "Почати",
        "word_lesson":     "Урок",
        "word_phrase":     "Фраза",
        "word_unit":       "Юніт",
        "no_lessons_yet":  "Ще немає уроків",
        # Банер-рекомендація вступного тесту / mastery (grammar.py::render_setup)
        "rec_reason_revisit":    "повернутися до {word} {lid}, щоб закріпити слабшу тему, перш ніж рухатись далі",
        "rec_reason_skip_ahead": "перейти одразу до {word} {lid} — ти вже випереджаєш цей рівень",
        "rec_banner_main":       "💡 Твій вступний тест / нещодавня активність підказує {reason} ({level}). Збережене місце на {word} {cur_lid} лишається недоторканим — це просто підказка.",
        "rec_jump_button":       "Перейти до {lid} →",
        # Phase labels
        "phase_warmup":    "Розминка",
        "phase_material":  "Новий матеріал",
        "phase_practice":  "Практика",
        "phase_speaking":  "Висловлювання",
        "phase_video":     "🎬 Відео",
        # Phase UI
        "skip":            "Пропустити →",
        "next":            "Далі →",
        "generate_exercise": "▶ Згенерувати вправу",
        "generate_task":   "▶ Згенерувати завдання",
        "rule_explanation_title": "📖 Пояснити правило",
        "rule_explanation_btn":   "▶ Пояснити це правило",
        "rule_exceptions_label":  "Зверни увагу на:",
        "new_exercise":    "🔄 Нова вправа",
        "error_review_title": "🔍 Розбір помилок",
        "error_review_start": "Почати виправлення →",
        "check_self":      "🔧 Перевір себе",
        "how_to_say":      "Як сказати",
        "in_target_lang":  "мовою, яку ти вивчаєш?",
        "write_or_record": "Напиши або запиши голосом.",
        "answer_label":    "Твоя відповідь:",
        "check_btn":       "Перевірити",
        "correct":         "✅ Чудово! Правильно.",
        "try_again":       "❌ Спробуй ще. Варіанти:",
        "next_btn":        "Далі →",
        "video_title":     "🎬 Відео для закріплення",
        "video_search_label": "Пошуковий запит YouTube:",
        "video_search_btn":   "🔍 Знайти відео",
        "video_new_search":   "🔄 Новий пошук",
        "video_not_found":    "Відео не знайдено. Спробуй змінити тему.",
        "video_beyond_curated": "🎬 На цьому рівні найкраща практика — реальний контент для носіїв мови: подивись серіал, фільм чи відео, яке тобі й так цікаво.",
        "video_channels_intro": "Досліджуй ці канали для практики на своєму рівні:",
        "video_ai_search_title": "🔍 Або знайди своє, на свою тему",
        "video_ai_search_intro": "Скопіюй цей запит у ChatGPT, Gemini чи будь-який AI-чат — і отримаєш поради під твій рівень *і* твої інтереси:",
        "video_ai_search_interest_label": "Твої інтереси (необов'язково — робить запит точнішим)",
        "video_ai_search_interest_placeholder": "напр. футбол, кулінарія, ігри, true crime…",
        "video_open":         "🔗 Відкрити на YouTube",
        "to_main_menu":       "До головного меню →",
        "sos_label":          "🆘 SOS & HELP — переклад",
        "sos_placeholder":    "Введи фразу для перекладу…",
        "translate_btn":      "Перекласти",
        "translation_result": "Переклад",
        # Phase 1 — Warmup
        "warmup_title":      "🌅 Розминка",
        "warmup_strategy":   "Стратегія: відповідай вільно — не бійся помилок, головне спробувати. Ми опрацюємо їх перед наступною фазою.",
        "no_errors":         "✅ Чудово — помилок не знайдено!",
        "error_breakdown":   "🔍 Розбір помилок",
        "answer_method":     "Спосіб відповіді",
        "voice_opt":         "🎙️ Голос",
        "text_opt":          "⌨️ Текст",
        "warmup_bilingual_toggle": "🌐 Показати запитання й моєю мовою",
        "step8_errors_title":  "✏️ Знайдено виправлення — обери, що відпрацювати",
        "step8_no_errors":     "✓ Усі фрази граматично правильні!",
        "practice_selected_btn": "Відпрацювати вибране →",
        "select_all":           "Обрати всі",
        "error_drill_title":       "✍️ Відпрацюй це",
        "error_drill_instruction": "Напиши або скажи 2-3 нові фрази з тим самим словом, словосполученням чи структурою.",
        "error_drill_input_label": "Твої фрази (одна на рядок):",
        # Phase 3 — Practice
        "practice_title":    "📝 Практика",
        "test_type_label":   "Тип тесту",
        "fill_in_blank":     "Заповни пропуск",
        "multiple_choice":   "Вибір відповіді",
        "translation_type":  "Переклад",
        "sentence_transformation": "Трансформація речення (лише граматика)",
        "construction_drill": "Тренування конструкції (нове, лише граматика)",
        "target_grammar":    "Граматика цієї мови (поза англійською)",
        "target_grammar_topic_label": "Тема",
        "generating_ex":     "Генерую вправу…",
        # Phase 4 — Speaking
        "speaking_title":    "Висловлювання",
        "speaking_strategy": "Стратегія: Спершу склади короткий план, тоді пиши/говори; не бійся помилок — головне висловити думку, а відшліфувати можна потім.",
        "mode_label":        "Спосіб",
        "enter_phrase_hint": "Введи фразу для перекладу…",
        "no_audio_warning":  "Спочатку запиши голос.",
        "write_answer":      "Напиши свою відповідь:",
        "you_asked":         "Ти запитав:",
        "new_btn":           "🔄 Нове",
        # Phase 5 — Video caption
        "level_label":       "Рівень",
        "lang_label":        "Мова",
        "topic_label":       "Тема",
        "titles": {
            1: "Прочитай уголос",
            2: "Слухай і повторюй",
            3: "Послухай і знайди переклад",
            4: "Прочитай якомога швидше",
            5: "Говори тінню за диктором",
            6: "Переклади вголос",
            7: "Перекладай якомога швидше",
            8: "Склади свої речення",
        },
        "hints": {
            1: "👀 Прочитай кожну фразу. Видно обидві мови.",
            2: "🎧 Слухай → ⏸ пауза → 🎤 повтори кожну фразу.",
            3: "🎧 Послухай → 👆 натисни правильний переклад.",
            4: "⚡ Прочитай усі фрази швидко. Швидкість = тривалість запису.",
            5: "🎧🗣️ Говори одразу за диктором — як луна.",
            6: "🔄 Бачиш рідну мову, кажеш цільову.",
            7: "⚡🔄 Перекладай кожну фразу якомога швидше.",
            8: "✍️ Створи нові фрази. ШІ перевірить граматику.",
        },
    },
    "es": {
        "step_label": "PASO",
        "required":   "obligatorio",
        "try_first":  "Primero completa el ejercicio",
        "main_menu":  "🏠 Menú principal",
        "titles": {
            1: "Lee en voz alta",
            2: "Escucha y repite",
            3: "Escucha y elige la traducción",
            4: "Lee lo más rápido posible",
            5: "Habla como un eco",
            6: "Traduce en voz alta",
            7: "Traduce lo más rápido posible",
            8: "Crea tus propias frases",
        },
        "hints": {
            1: "👀 Lee cada frase. Ambos idiomas son visibles.",
            2: "🎧 Escucha → ⏸ pausa → 🎤 repite cada frase.",
            3: "🎧 Escucha → 👆 pulsa la traducción correcta.",
            4: "⚡ Lee todas las frases rápido. Velocidad = duración del audio.",
            5: "🎧🗣️ Habla a la vez que el audio — como un eco.",
            6: "🔄 Ves tu idioma, dices el idioma objetivo.",
            7: "⚡🔄 Traduce cada frase lo más rápido posible.",
            8: "✍️ Crea frases nuevas. La IA revisará la gramática.",
        },
    },
    "ko": {
        "step_label": "단계",
        "required":   "필수",
        "try_first":  "먼저 연습을 완료하세요",
        "main_menu":  "🏠 메인 메뉴",
        "titles": {
            1: "소리내어 읽기",
            2: "듣고 따라 말하기",
            3: "듣고 알맞은 번역 고르기",
            4: "최대한 빠르게 읽기",
            5: "음성을 그림자처럼 따라 말하기",
            6: "소리내어 번역하기",
            7: "최대한 빠르게 번역하기",
            8: "나만의 문장 만들기",
        },
        "hints": {
            1: "👀 모든 문장을 읽으세요. 두 언어가 모두 보입니다.",
            2: "🎧 듣기 → ⏸ 멈춤 → 🎤 따라 말하기.",
            3: "🎧 듣고 → 👆 알맞은 번역을 누르세요.",
            4: "⚡ 모든 문장을 빠르게 읽으세요. 속도 = 녹음 길이.",
            5: "🎧🗣️ 음성과 동시에 말하세요 — 메아리처럼.",
            6: "🔄 모국어를 보고 목표 언어로 말하세요.",
            7: "⚡🔄 각 문장을 최대한 빠르게 번역하세요.",
            8: "✍️ 새 문장을 만드세요. AI가 문법을 확인합니다.",
        },
    },
}


def _load_generated() -> None:
    """
    Merge data/i18n_generated.json (scripts/generate_i18n_strings.py's
    one-time batch-translation output) into STRINGS: fills in a language's
    bucket (creating it if the language has no hand-written entry at all)
    or an individual missing key within an existing bucket (es/ko), without
    ever overwriting a hand-written value. A missing/malformed file just
    leaves STRINGS as the hand-written en/uk/es/ko above -- same
    English-fallback degradation get() already had, not a hard dependency.
    """
    path = Path(__file__).parent.parent / "data" / "i18n_generated.json"
    try:
        generated = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    for code, gen_bucket in generated.items():
        bucket = STRINGS.setdefault(code, {})
        for key, value in gen_bucket.items():
            if key in ("titles", "hints"):
                sub = bucket.setdefault(key, {})
                for step_str, text in value.items():
                    sub.setdefault(int(step_str), text)
            else:
                bucket.setdefault(key, value)


_load_generated()


def _code(lang: str | None) -> str:
    if not lang:
        return "en"
    if lang in STRINGS:
        return lang
    return LANG_TO_CODE.get(lang, "en")


def get(lang: str, key: str, step: int | None = None) -> str:
    code = _code(lang)
    bucket = STRINGS.get(code) or STRINGS["en"]
    if step is None:
        val = bucket.get(key)
        if val is None:
            val = STRINGS["en"].get(key, "")
        return val
    sub = bucket.get(key) or {}
    val = sub.get(step)
    if val is None:
        val = STRINGS["en"].get(key, {}).get(step, "")
    return val


def step_icon(step: int) -> str:
    return STEP_ICONS.get(step, "📝")

def step_type(step: int) -> str:
    return STEP_TYPES.get(step, "reading")

def step_color(step: int) -> str:
    return TYPE_COLORS.get(step_type(step), "#5060c0")
