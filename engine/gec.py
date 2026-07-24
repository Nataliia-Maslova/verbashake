"""
engine/gec.py - Grammar Error Correction via Gemini.

Replaces the fine-tuned T5 models (natashasms/en-gec-model etc.).
Same public API: correct(), gec_available(), supported_languages().
New: correct_with_details() returns full error dict.
"""
from __future__ import annotations

_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "uk": "Ukrainian",
    "de": "German",
    "es": "Spanish",
    "ko": "Korean",
    "fr": "French",
    "ja": "Japanese",
    "zh": "Chinese",
    "pt": "Portuguese",
    "it": "Italian",
    "pl": "Polish",
    "ru": "Russian",
}


def correct(text: str, lang: str = "en", native_lang: str = "en") -> str:
    """Return corrected text. Backward-compatible string interface."""
    from engine.gemini import correct_grammar
    result = correct_grammar(
        text,
        target_lang=_LANG_NAMES.get(lang, lang),
        native_lang=_LANG_NAMES.get(native_lang, native_lang),
    )
    return result.get("corrected", text)


def correct_with_details(
    text: str, lang: str = "en", native_lang: str = "en"
) -> dict:
    """Return full dict: {"corrected": str, "errors": [...]}"""
    from engine.gemini import correct_grammar
    return correct_grammar(
        text,
        target_lang=_LANG_NAMES.get(lang, lang),
        native_lang=_LANG_NAMES.get(native_lang, native_lang),
    )


def gec_available(lang: str = "en") -> bool:
    """All languages supported via Gemini."""
    return True


def supported_languages() -> list:
    return list(_LANG_NAMES.keys())
