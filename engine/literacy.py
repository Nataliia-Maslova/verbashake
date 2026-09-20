"""
engine/literacy.py — shared "does this student need the letters first?"
heuristic (2026-09-20).

Extracted out of app.py's onboarding screen so path_app.py's per-language
literacy banner can reuse the exact same script-family map and question
logic without duplicating it, and without a circular import (app.py imports
path_app.py for routing, so path_app.py can't import app.py at module load
time).
"""
from __future__ import annotations

# Coarse script family per language — used ONLY to decide whether a student
# needs to be asked the literacy ("already read this script, or need the
# letters first?") question at all. The actual answer is stored per
# (user, target_lang) in the language_literacy table (engine/user_prefs.py)
# and is what drives the reading gate in engine/recommender.py.
_SCRIPT_FAMILY: dict[str, str] = {
    "English": "latin", "French": "latin", "German": "latin", "Spanish": "latin",
    "Italian": "latin", "Portuguese": "latin", "Catalan": "latin", "Dutch": "latin",
    "Polish": "latin", "Romanian": "latin", "Czech": "latin", "Turkish": "latin",
    "Swedish": "latin",
    "Ukrainian": "cyrillic", "Russian": "cyrillic", "Bulgarian": "cyrillic",
    "Korean": "hangul", "Japanese": "japanese", "Chinese": "chinese",
}


def needs_literacy_question(native: str, target: str, self_level: str) -> bool:
    if self_level == "zero":
        return True
    return _SCRIPT_FAMILY.get(native, "latin") != _SCRIPT_FAMILY.get(target, "latin")
