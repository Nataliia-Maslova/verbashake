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

Turkish/Japanese/Korean added 2026-09-27 (Natalia: "ja/ko full sets, tr a
mini set, zh skip"). Chinese verbs don't conjugate at all (no tense/person
inflection, just aspect particles 了/过/着 and the 把-construction) -- those
already have their own topics in target_grammar_paths.py, so there is no
"three forms of one verb" triad to build for Chinese; it stays uncovered on
purpose, not by oversight. Turkish verbs are almost entirely regular by
suffix -- the one small, genuinely irregular pocket is the aorist tense for
a closed set of monosyllabic stems (gel- -> gelir, not the expected regular
-er/-ar), so Turkish gets ONE set of 8 rows instead of 3.
"""
from __future__ import annotations

# imlls lesson_ids that are English verb-form lists -- shown only when the
# target language is English.
ENGLISH_PIVOT_VERB_LESSONS = frozenset({114, 116, 118, 120, 122, 124, 126, 128, 130,
                                        148, 149, 150, 151, 152, 153, 154, 155})

ROWS_PER_GROUP = 8
GROUPS = 3
GROUP_LEVELS = ["A2", "B1", "B1"]

# Each spec: base_id (first of its PERMANENT, consecutive lesson_ids -- see
# target_grammar_paths docstring), pattern (the row's 3 roles, in the
# language's OWN terminology -- also what gemini.translate_verb_row shows the
# model so it knows what each part means), example, title/gloss (for the
# picker), what (fed to scripts/generate_verb_forms.py's prompt to describe
# which verbs to pick), and optional groups/levels overriding the
# GROUPS/GROUP_LEVELS defaults above (Turkish only needs 1 set, not 3).
_SPECS = [
    dict(lang="Spanish", base_id=1105, pattern="infinitivo - pretérito indefinido (yo) - participio",
         example="hacer - hice - hecho", title="Verbos irregulares",
         gloss="Irregular verbs: infinitive - preterite - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="French", base_id=1108, pattern="infinitif - présent (je) - participe passé",
         example="faire - je fais - fait", title="Verbes irréguliers",
         gloss="Irregular verbs: infinitive - present - past participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="German", base_id=1111, pattern="Infinitiv - Präteritum (er) - Partizip II",
         example="gehen - ging - gegangen", title="Unregelmäßige Verben",
         gloss="Strong/irregular verbs: infinitive - preterite - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Italian", base_id=1114, pattern="infinito - presente (io) - participio passato",
         example="fare - faccio - fatto", title="Verbi irregolari",
         gloss="Irregular verbs: infinitive - present - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Portuguese", base_id=1117, pattern="infinitivo - pretérito perfeito (eu) - particípio",
         example="fazer - fiz - feito", title="Verbos irregulares",
         gloss="Irregular verbs: infinitive - preterite - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Catalan", base_id=1120, pattern="infinitiu - present (jo) - participi",
         example="fer - faig - fet", title="Verbs irregulars",
         gloss="Irregular verbs: infinitive - present - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Dutch", base_id=1123, pattern="infinitief - onvoltooid verleden tijd (enkelvoud) - voltooid deelwoord",
         example="gaan - ging - gegaan", title="Onregelmatige werkwoorden",
         gloss="Irregular verbs: infinitive - past - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Swedish", base_id=1126, pattern="infinitiv - preteritum - supinum",
         example="gå - gick - gått", title="Oregelbundna verb",
         gloss="Irregular verbs: infinitive - past - supine",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Romanian", base_id=1129, pattern="infinitiv - prezent (eu) - participiu",
         example="a face - fac - făcut", title="Verbe neregulate",
         gloss="Irregular verbs: infinitive - present - participle",
         what="the most frequent IRREGULAR verbs"),
    dict(lang="Russian", base_id=1132,
         pattern="несовершенный вид - совершенный вид - прошедшее время (м. р., совершенный вид)",
         example="делать - сделать - сделал", title="Глагольные пары по виду",
         gloss="Aspect pairs: imperfective - perfective - past",
         what="very frequent everyday verbs, each as an imperfective/perfective PAIR"),
    dict(lang="Ukrainian", base_id=1135,
         pattern="недоконаний вид - доконаний вид - минулий час (ч. р., доконаний вид)",
         example="робити - зробити - зробив", title="Видові пари дієслів",
         gloss="Aspect pairs: imperfective - perfective - past",
         what="very frequent everyday verbs, each as an imperfective/perfective PAIR"),
    dict(lang="Polish", base_id=1138,
         pattern="czasownik niedokonany - czasownik dokonany - czas przeszły (r. męski, dokonany)",
         example="robić - zrobić - zrobił", title="Pary aspektowe czasowników",
         gloss="Aspect pairs: imperfective - perfective - past",
         what="very frequent everyday verbs, each as an imperfective/perfective PAIR"),
    dict(lang="Czech", base_id=1141,
         pattern="nedokonavé sloveso - dokonavé sloveso - minulý čas (m. r., dokonavé)",
         example="dělat - udělat - udělal", title="Vidové dvojice sloves",
         gloss="Aspect pairs: imperfective - perfective - past",
         what="very frequent everyday verbs, each as an imperfective/perfective PAIR"),
    dict(lang="Bulgarian", base_id=1144,
         pattern="несвършен вид - свършен вид - минало свършено време (1 л., ед. ч.)",
         example="правя - направя - направих", title="Глаголни двойки по вид",
         gloss="Aspect pairs: imperfective - perfective - aorist",
         what="very frequent everyday verbs, each as an imperfective/perfective PAIR"),
    dict(lang="Turkish", base_id=1147, groups=1, levels=["A2"],
         pattern="mastar - geniş zaman (o) - di'li geçmiş (o)",
         example="gitmek - gider - gitti", title="Düzensiz geniş zaman",
         gloss="Irregular aorist: infinitive - aorist (he/she/it) - simple past (he/she/it)",
         what=("the small, closed set of TRUE irregular-aorist Turkish verbs -- monosyllabic stems "
               "that take -ir/-ır in the aorist instead of the expected regular -er/-ar (e.g. gel- -> "
               "gelir, not 'geler'; the past form is fully regular and included just for context)")),
    dict(lang="Japanese", base_id=1148,
         pattern="辞書形 - ます形 - て形",
         example="食べる - 食べます - 食べて", title="動詞の活用",
         gloss="Verb conjugation: dictionary form - polite present (masu-form) - te-form",
         what=("common verbs spanning all three conjugation classes -- godan/u-verbs, ichidan/ru-verbs, "
               "and the two irregular verbs する and 来る -- so every set mixes classes rather than "
               "drilling only one")),
    dict(lang="Korean", base_id=1151,
         pattern="사전형 - 정중체 현재형 - 과거형",
         example="먹다 - 먹어요 - 먹었어요", title="동사 활용",
         gloss="Verb conjugation: dictionary form - polite present (-아요/-어요) - past (-았/었어요)",
         what=("common verbs, with AT LEAST HALF of each set drawn from the four irregular-stem classes "
               "that cause most learner errors: ㅂ-irregular (e.g. 덥다), ㄷ-irregular (e.g. 듣다), "
               "르-irregular (e.g. 다르다), ㅅ-irregular (e.g. 낫다)")),
]

SPECS = {s["lang"]: s for s in _SPECS}


def topic_key(lang_code: str, group: int) -> str:
    return f"{lang_code}_verb_rows_{group}"


def build_topics(lang_codes: dict[str, str]) -> dict[str, list[dict]]:
    """{language: [topic dicts]} in target_grammar_paths' own topic shape."""
    out: dict[str, list[dict]] = {}
    for lang, sp in SPECS.items():
        code = lang_codes[lang]
        n_groups = sp.get("groups", GROUPS)
        levels = sp.get("levels", GROUP_LEVELS)
        topics = []
        for g in range(1, n_groups + 1):
            suffix = f" ({g})" if n_groups > 1 else ""
            set_note = f" Set {g} of {n_groups}." if n_groups > 1 else ""
            gloss_suffix = f" (set {g}/{n_groups})" if n_groups > 1 else ""
            topics.append({
                "key": topic_key(code, g), "level": levels[g - 1],
                "lesson_id": sp["base_id"] + g - 1, "category": "past",
                "title": f"{sp['title']}{suffix}",
                "gloss_en": f"{sp['gloss']}{gloss_suffix}",
                "description": (f"A list of {sp['what']} in {lang}, one row per verb in the form "
                                f"'{sp['pattern']}' (e.g. {sp['example']}).{set_note}"),
            })
        out[lang] = topics
    return out
