"""
engine/verb_form_topics.py -- language-specific "verb rows" lessons (2026-09-25).

The 182 imlls lessons include 17 English-pivot verb-form lists ("to bring -
brought - brought"...). For a non-English target language those rows were
mistranslations of an English phenomenon (French "faire - fait" twice, one
row per English verb, etc.). Instead each language below gets its OWN rows,
in its own system of irregular/aspectual forms, generated into
data/target_grammar_drills.csv by scripts/generate_verb_forms.py and served
through the normal target_grammar machinery (lesson_id >= 1075, locked to the
language, native side translated lazily). The English-pivot lessons are hidden
for every target language except English (ENGLISH_PIVOT_VERB_LESSONS).

Not covered (already have their own dedicated topics): Turkish, Japanese
(ja_verb_groups/ja_te_form), Korean (ko_irregular_verbs), Chinese.
"""
from __future__ import annotations

# imlls lesson_ids that are English verb-form lists -- shown only when the
# target language is English.
ENGLISH_PIVOT_VERB_LESSONS = frozenset({114, 116, 118, 120, 122, 124, 126, 128, 130,
                                        148, 149, 150, 151, 152, 153, 154, 155})

ROWS_PER_GROUP = 8
GROUPS = 3
GROUP_LEVELS = ["A2", "B1", "B1"]

# (language, first lesson_id, kind, form pattern, example row, title stem, gloss stem)
# lesson ids are PERMANENT (see target_grammar_paths docstring): 3 consecutive per language.
_SPECS = [
    ("Spanish",    1105, "irregular", "infinitivo - pretérito indefinido (yo) - participio", "hacer - hice - hecho",
     "Verbos irregulares", "Irregular verbs: infinitive - preterite - participle"),
    ("French",     1108, "irregular", "infinitif - présent (je) - participe passé", "faire - je fais - fait",
     "Verbes irréguliers", "Irregular verbs: infinitive - present - past participle"),
    ("German",     1111, "irregular", "Infinitiv - Präteritum (er) - Partizip II", "gehen - ging - gegangen",
     "Unregelmäßige Verben", "Strong/irregular verbs: infinitive - preterite - participle"),
    ("Italian",    1114, "irregular", "infinito - presente (io) - participio passato", "fare - faccio - fatto",
     "Verbi irregolari", "Irregular verbs: infinitive - present - past participle"),
    ("Portuguese", 1117, "irregular", "infinitivo - pretérito perfeito (eu) - particípio", "fazer - fiz - feito",
     "Verbos irregulares", "Irregular verbs: infinitive - preterite - participle"),
    ("Catalan",    1120, "irregular", "infinitiu - present (jo) - participi", "fer - faig - fet",
     "Verbs irregulars", "Irregular verbs: infinitive - present - participle"),
    ("Dutch",      1123, "irregular", "infinitief - onvoltooid verleden tijd (enkelvoud) - voltooid deelwoord", "gaan - ging - gegaan",
     "Onregelmatige werkwoorden", "Irregular verbs: infinitive - past - participle"),
    ("Swedish",    1126, "irregular", "infinitiv - preteritum - supinum", "gå - gick - gått",
     "Oregelbundna verb", "Irregular verbs: infinitive - past - supine"),
    ("Romanian",   1129, "irregular", "infinitiv - prezent (eu) - participiu", "a face - fac - făcut",
     "Verbe neregulate", "Irregular verbs: infinitive - present - participle"),
    ("Russian",    1132, "aspect", "несовершенный вид - совершенный вид - прошедшее время (м. р., совершенный вид)", "делать - сделать - сделал",
     "Глагольные пары по виду", "Aspect pairs: imperfective - perfective - past"),
    ("Ukrainian",  1135, "aspect", "недоконаний вид - доконаний вид - минулий час (ч. р., доконаний вид)", "робити - зробити - зробив",
     "Видові пари дієслів", "Aspect pairs: imperfective - perfective - past"),
    ("Polish",     1138, "aspect", "czasownik niedokonany - czasownik dokonany - czas przeszły (r. męski, dokonany)", "robić - zrobić - zrobił",
     "Pary aspektowe czasowników", "Aspect pairs: imperfective - perfective - past"),
    ("Czech",      1141, "aspect", "nedokonavé sloveso - dokonavé sloveso - minulý čas (m. r., dokonavé)", "dělat - udělat - udělal",
     "Vidové dvojice sloves", "Aspect pairs: imperfective - perfective - past"),
    ("Bulgarian",  1144, "aspect", "несвършен вид - свършен вид - минало свършено време (1 л., ед. ч.)", "правя - направя - направих",
     "Глаголни двойки по вид", "Aspect pairs: imperfective - perfective - aorist"),
]

SPECS = {s[0]: {"base_id": s[1], "kind": s[2], "pattern": s[3], "example": s[4], "title": s[5], "gloss": s[6]} for s in _SPECS}


def topic_key(lang_code: str, group: int) -> str:
    return f"{lang_code}_verb_rows_{group}"


def build_topics(lang_codes: dict[str, str]) -> dict[str, list[dict]]:
    """{language: [topic dicts]} in target_grammar_paths' own topic shape."""
    out: dict[str, list[dict]] = {}
    for lang, sp in SPECS.items():
        code = lang_codes[lang]
        topics = []
        for g in range(1, GROUPS + 1):
            what = ("most frequent irregular verbs" if sp["kind"] == "irregular"
                    else "most frequent everyday verbs as imperfective/perfective pairs")
            topics.append({
                "key": topic_key(code, g), "level": GROUP_LEVELS[g - 1],
                "lesson_id": sp["base_id"] + g - 1, "category": "past",
                "title": f"{sp['title']} ({g})",
                "gloss_en": f"{sp['gloss']} (set {g}/{GROUPS})",
                "description": (f"A list of the {what} in {lang}, one row per verb in the form "
                                f"'{sp['pattern']}' (e.g. {sp['example']}). Set {g} of {GROUPS}."),
            })
        out[lang] = topics
    return out
