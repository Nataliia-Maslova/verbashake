"""
engine/target_grammar_paths.py -- grammar topics that are genuinely central to
a specific target language but structurally absent from imlls_database's 182
Grammar lessons, because that curriculum was built from English grammar
categories (see LINGUISTIC_AUDIT.md, section 1 -- Slavic verbal aspect,
Spanish/Portuguese ser/estar, the subjunctive mood, Japanese/Korean particles
and speech levels, German's case system, Chinese aspect markers... none of
these have an English equivalent to translate from, so they were never in the
dataset to begin with).

This is NOT a full curriculum per language -- it's a short, prioritized list
of the topics a philologist would flag as the biggest structural gaps (same
methodology as the "9 confirmed gaps" list already written for English in
CLAUDE.md, 2026-08-21). English needs no entry here; its grammar is what the
182-lesson curriculum was built from.

Each topic's sentences are batch-generated once by
scripts/generate_target_grammar_drills.py into data/target_grammar_drills.csv
(target-language text only -- native-language translation is done lazily,
same engine.gemini.translate_phrase + phrase_translations cache the CEFR-J
Vocabulary module already uses).

`lesson_id` and `category` (2026-08-23, Natalia's request: these topics
should show up as real, browsable Grammar lessons -- e.g. Ukrainian cases
inside the "Nouns & Quantities" category alongside the original 182 -- not
just live inside the Phase 3 practice picker) let
engine.target_grammar_loader.build_grammar_lesson_rows() splice them into the
normal imlls_database-shaped dataframe every other part of the Grammar module
already works with (engine/picker.py's Category filter, Select Lesson
dropdown, wave path, Phase 1-8 flow, mastery/SRS via content_units) with no
separate code path.

`lesson_id` is a PERMANENT, EXPLICIT, hand-assigned integer >= 1000 (outside
imlls_database's 1-182 range) -- content_units/mastery/srs_state rows key off
it once seeded (scripts/seed_content_units.py), so NEVER renumber an existing
topic's id or reorder topics in a way that would imply a different id;
only append new topics at the next free id (current max: 1074).
`category` is one of engine/picker.py's _GRAMMAR_CATEGORIES ids ("basics",
"nouns", "habits", "present", "modals", "past", "advanced").

`title` is written in target_lang itself (that's the grammar term the
student will actually meet). `gloss_en` is a short English name for the same
topic -- shown alongside `title` in the picker (grammar.py) so the topic is
identifiable even to a student who hasn't learned target_lang's term for it
yet, and regardless of the student's own native_lang (full native-language
translation of the roadmap, for all 13x14 native/target combinations, is out
of scope for V1 -- English is the one language every user of this app can be
assumed to have some exposure to, same reasoning as topic_en's role as the
fallback column in the main curriculum, engine/loader.py).

AI-authored roadmap, not reviewed by a native speaker of every language --
treat like data/i18n_generated.json: a reasonable first pass, worth revising
per-language as it's used, not a finished authority.
"""
from __future__ import annotations

TARGET_GRAMMAR_PATHS: dict[str, list[dict]] = {
    "Ukrainian": [
        {"key": "uk_gender_agreement", "level": "A1", "lesson_id": 1000, "category": "nouns",
         "title": "Рід іменників і узгодження прикметників",
         "gloss_en": "Gender agreement",
         "description": "Grammatical gender (masculine/feminine/neuter) and how adjectives, "
                         "demonstratives, and past-tense verb endings must agree with it."},
        {"key": "uk_cases_basic", "level": "A2", "lesson_id": 1001, "category": "nouns",
         "title": "Відмінки: називний, знахідний, родовий у побутових фразах",
         "gloss_en": "Basic case usage",
         "description": "Basic case usage in everyday sentences: nominative for the subject, "
                         "accusative for a direct object, genitive after negation and quantities."},
        {"key": "uk_aspect_basic", "level": "A2", "lesson_id": 1002, "category": "past",
         "title": "Вид дієслова: доконаний і недоконаний",
         "gloss_en": "Verbal aspect: perfective vs imperfective",
         "description": "Perfective vs imperfective aspect pairs (e.g. робити/зробити) and how "
                         "the choice changes whether an action is ongoing/habitual vs completed."},
        {"key": "uk_aspect_past", "level": "B1", "lesson_id": 1003, "category": "past",
         "title": "Вид у минулому часі: звичка проти завершеної дії",
         "gloss_en": "Aspect in the past tense",
         "description": "Using imperfective aspect in the past for habitual/repeated actions "
                         "vs perfective for a single completed action."},
        {"key": "uk_motion_verbs", "level": "B1", "lesson_id": 1004, "category": "advanced",
         "title": "Дієслова руху: однонапрямлені й різнонапрямлені",
         "gloss_en": "Verbs of motion",
         "description": "The unidirectional/multidirectional verb-of-motion pairs (йти/ходити, "
                         "їхати/їздити) and which context calls for which."},
        {"key": "uk_aspect_imperative", "level": "B1", "lesson_id": 1005, "category": "habits",
         "title": "Вид у наказовому способі",
         "gloss_en": "Aspect in commands",
         "description": "Choosing perfective vs imperfective aspect in commands (a one-time "
                         "request vs a general instruction/invitation)."},
        {"key": "uk_participles", "level": "B2", "lesson_id": 1006, "category": "advanced",
         "title": "Дієприкметники та дієприслівники",
         "gloss_en": "Participles and adverbial participles",
         "description": "Active/passive participles (написаний) and adverbial participles "
                         "(читаючи) used to compress clauses, common in written Ukrainian."},
    ],
    "Russian": [
        {"key": "ru_gender_agreement", "level": "A1", "lesson_id": 1007, "category": "nouns",
         "title": "Род существительных и согласование прилагательных",
         "gloss_en": "Gender agreement",
         "description": "Grammatical gender (masculine/feminine/neuter) and adjective/"
                         "past-tense-verb agreement with it."},
        {"key": "ru_cases_basic", "level": "A2", "lesson_id": 1008, "category": "nouns",
         "title": "Падежи: именительный, винительный, родительный в быту",
         "gloss_en": "Basic case usage",
         "description": "Basic case usage: nominative subject, accusative direct object, "
                         "genitive after negation and quantities."},
        {"key": "ru_aspect_basic", "level": "A2", "lesson_id": 1009, "category": "past",
         "title": "Вид глагола: совершенный и несовершенный",
         "gloss_en": "Verbal aspect: perfective vs imperfective",
         "description": "Perfective vs imperfective aspect pairs (делать/сделать) and how the "
                         "choice changes whether an action is ongoing/habitual vs completed."},
        {"key": "ru_aspect_past", "level": "B1", "lesson_id": 1010, "category": "past",
         "title": "Вид в прошедшем времени: привычка против завершённого действия",
         "gloss_en": "Aspect in the past tense",
         "description": "Imperfective for habitual/repeated past actions vs perfective for a "
                         "single completed one."},
        {"key": "ru_motion_verbs", "level": "B1", "lesson_id": 1011, "category": "advanced",
         "title": "Глаголы движения: однонаправленные и разнонаправленные",
         "gloss_en": "Verbs of motion",
         "description": "Unidirectional/multidirectional motion-verb pairs (идти/ходить, "
                         "ехать/ездить) and which context calls for which."},
        {"key": "ru_motion_prefixes", "level": "B2", "lesson_id": 1012, "category": "advanced",
         "title": "Приставочные глаголы движения",
         "gloss_en": "Prefixed verbs of motion",
         "description": "Directional prefixes on motion verbs (при-, у-, вы-, за-, etc.) that "
                         "turn a base motion verb into 'arrive', 'leave', 'go out', 'drop by'."},
        {"key": "ru_participles", "level": "B2", "lesson_id": 1013, "category": "advanced",
         "title": "Причастия и деепричастия",
         "gloss_en": "Participles and adverbial participles",
         "description": "Active/passive participles and adverbial participles used to compress "
                         "clauses, common in written Russian."},
    ],
    "Polish": [
        {"key": "pl_gender_agreement", "level": "A1", "lesson_id": 1014, "category": "nouns",
         "title": "Rodzaj rzeczownika i zgoda przymiotnika",
         "gloss_en": "Gender agreement",
         "description": "Grammatical gender (including the masculine-personal vs "
                         "non-masculine-personal distinction) and adjective agreement with it."},
        {"key": "pl_cases_basic", "level": "A2", "lesson_id": 1015, "category": "nouns",
         "title": "Przypadki: mianownik, biernik, dopełniacz w codziennych zdaniach",
         "gloss_en": "Basic case usage",
         "description": "Basic case usage in everyday sentences: nominative subject, "
                         "accusative direct object, genitive after negation and quantities."},
        {"key": "pl_aspect_basic", "level": "A2", "lesson_id": 1016, "category": "past",
         "title": "Aspekt czasownika: dokonany i niedokonany",
         "gloss_en": "Verbal aspect: perfective vs imperfective",
         "description": "Perfective vs imperfective aspect pairs (robić/zrobić) and how the "
                         "choice changes whether an action is ongoing/habitual vs completed."},
        {"key": "pl_aspect_past_future", "level": "B1", "lesson_id": 1017, "category": "past",
         "title": "Aspekt w czasie przeszłym i przyszłym",
         "gloss_en": "Aspect in the past and future",
         "description": "Choosing perfective vs imperfective aspect when narrating past events "
                         "or planning future ones."},
        {"key": "pl_virile_plural", "level": "B1", "lesson_id": 1018, "category": "advanced",
         "title": "Rodzaj męskoosobowy w liczbie mnogiej",
         "gloss_en": "Masculine-personal plural agreement",
         "description": "The masculine-personal vs non-masculine-personal plural agreement "
                         "(widzę tych panów vs widzę te kobiety) -- a distinction with no "
                         "equivalent in most other Slavic languages taught here."},
        {"key": "pl_participles", "level": "B2", "lesson_id": 1019, "category": "advanced",
         "title": "Imiesłowy",
         "gloss_en": "Participles",
         "description": "Adjectival and adverbial participles (imiesłowy przymiotnikowe / "
                         "przysłówkowe) used to compress clauses."},
    ],
    "Spanish": [
        {"key": "es_ser_estar", "level": "A1", "lesson_id": 1020, "category": "basics",
         "title": "Ser vs. Estar",
         "gloss_en": "Ser vs. estar (two verbs 'to be')",
         "description": "The two verbs for 'to be': ser for inherent/permanent characteristics "
                         "vs estar for states, locations, and temporary conditions."},
        {"key": "es_gender_agreement", "level": "A1", "lesson_id": 1021, "category": "nouns",
         "title": "Género y concordancia del adjetivo",
         "gloss_en": "Gender agreement",
         "description": "Noun gender (masculine/feminine) and adjective agreement with it."},
        {"key": "es_reflexive", "level": "A2", "lesson_id": 1022, "category": "habits",
         "title": "Verbos reflexivos",
         "gloss_en": "Reflexive verbs",
         "description": "Reflexive verbs and pronouns (levantarse, llamarse) for actions the "
                         "subject does to themselves."},
        {"key": "es_object_pronouns", "level": "A2", "lesson_id": 1023, "category": "advanced",
         "title": "Pronombres de objeto directo e indirecto",
         "gloss_en": "Direct/indirect object pronouns",
         "description": "Direct/indirect object pronouns (me, te, lo, la, le) and their "
                         "placement before a conjugated verb or attached to an infinitive."},
        {"key": "es_preterite_imperfect", "level": "B1", "lesson_id": 1024, "category": "past",
         "title": "Pretérito vs. imperfecto",
         "gloss_en": "Preterite vs. imperfect",
         "description": "Preterite for a completed past action vs imperfect for an ongoing or "
                         "habitual past state/action -- a core aspectual distinction English "
                         "marks far more loosely."},
        {"key": "es_subjunctive_present", "level": "B1", "lesson_id": 1025, "category": "modals",
         "title": "Presente de subjuntivo",
         "gloss_en": "Present subjunctive",
         "description": "The present subjunctive mood, triggered by expressions of wish, doubt, "
                         "emotion, or influence (quiero que..., es importante que...)."},
        {"key": "es_subjunctive_past_si", "level": "B2", "lesson_id": 1026, "category": "modals",
         "title": "Subjuntivo pasado y oraciones con si",
         "gloss_en": "Past subjunctive & si-clauses",
         "description": "Past subjunctive and its use in hypothetical si-clauses (si tuviera "
                         "tiempo, iría...)."},
    ],
    "French": [
        {"key": "fr_gender_agreement", "level": "A1", "lesson_id": 1027, "category": "nouns",
         "title": "Genre et accord de l'adjectif",
         "gloss_en": "Gender agreement",
         "description": "Noun gender (masculine/feminine) and adjective agreement with it."},
        {"key": "fr_passe_compose_imparfait", "level": "A2", "lesson_id": 1028, "category": "past",
         "title": "Passé composé vs. imparfait",
         "gloss_en": "Passé composé vs. imparfait",
         "description": "Passé composé for a completed past action vs imparfait for an ongoing "
                         "or habitual past state/action."},
        {"key": "fr_partitive", "level": "A2", "lesson_id": 1029, "category": "nouns",
         "title": "Articles partitifs",
         "gloss_en": "Partitive articles",
         "description": "Partitive articles (du, de la, des) for uncountable/unspecified "
                         "quantities, with no direct English equivalent."},
        {"key": "fr_object_pronouns", "level": "B1", "lesson_id": 1030, "category": "advanced",
         "title": "Pronoms compléments et leur ordre",
         "gloss_en": "Object pronouns & their order",
         "description": "Object pronouns (me, te, le, la, lui, y, en) and their fixed order "
                         "before the verb."},
        {"key": "fr_subjunctive_present", "level": "B1", "lesson_id": 1031, "category": "modals",
         "title": "Subjonctif présent",
         "gloss_en": "Present subjunctive",
         "description": "The present subjunctive mood, triggered by expressions of wish, "
                         "doubt, emotion, or necessity (il faut que..., je veux que...)."},
    ],
    "Italian": [
        {"key": "it_gender_agreement", "level": "A1", "lesson_id": 1032, "category": "nouns",
         "title": "Genere e accordo dell'aggettivo",
         "gloss_en": "Gender agreement",
         "description": "Noun gender (masculine/feminine) and adjective agreement with it."},
        {"key": "it_passato_prossimo_imperfetto", "level": "A2", "lesson_id": 1033, "category": "past",
         "title": "Passato prossimo vs. imperfetto",
         "gloss_en": "Passato prossimo vs. imperfetto",
         "description": "Passato prossimo for a completed past action vs imperfetto for an "
                         "ongoing or habitual past state/action."},
        {"key": "it_pronominal_particles", "level": "B1", "lesson_id": 1034, "category": "advanced",
         "title": "Particelle ci e ne",
         "gloss_en": "Particles ci and ne",
         "description": "The pronominal particles ci (there / about it) and ne (of it/them), "
                         "with no direct English equivalent."},
        {"key": "it_subjunctive_present", "level": "B1", "lesson_id": 1035, "category": "modals",
         "title": "Congiuntivo presente",
         "gloss_en": "Present subjunctive",
         "description": "The present subjunctive mood, triggered by expressions of wish, "
                         "doubt, emotion, or opinion (penso che..., voglio che...)."},
    ],
    "Portuguese": [
        {"key": "pt_ser_estar", "level": "A1", "lesson_id": 1036, "category": "basics",
         "title": "Ser vs. Estar",
         "gloss_en": "Ser vs. estar (two verbs 'to be')",
         "description": "The two verbs for 'to be': ser for inherent/permanent characteristics "
                         "vs estar for states, locations, and temporary conditions."},
        {"key": "pt_preterite_imperfect", "level": "A2", "lesson_id": 1037, "category": "past",
         "title": "Pretérito perfeito vs. imperfeito",
         "gloss_en": "Preterite vs. imperfect",
         "description": "Preterite for a completed past action vs imperfect for an ongoing or "
                         "habitual past state/action."},
        {"key": "pt_subjunctive_present", "level": "B1", "lesson_id": 1038, "category": "modals",
         "title": "Presente do subjuntivo",
         "gloss_en": "Present subjunctive",
         "description": "The present subjunctive mood, triggered by expressions of wish, "
                         "doubt, emotion, or influence (espero que..., é importante que...)."},
        {"key": "pt_personal_infinitive", "level": "B1", "lesson_id": 1039, "category": "advanced",
         "title": "Infinitivo pessoal",
         "gloss_en": "Personal infinitive",
         "description": "The personal infinitive, an inflected infinitive unique to "
                         "Portuguese among the languages here (é importante eles chegarem)."},
        {"key": "pt_future_subjunctive", "level": "B2", "lesson_id": 1040, "category": "modals",
         "title": "Futuro do subjuntivo",
         "gloss_en": "Future subjunctive",
         "description": "The future subjunctive, used in real future conditions/temporal "
                         "clauses (quando eu chegar, quando ele puder) -- a mood English has "
                         "no dedicated form for."},
    ],
    "Catalan": [
        {"key": "ca_gender_agreement", "level": "A1", "lesson_id": 1041, "category": "nouns",
         "title": "Gènere i concordança de l'adjectiu",
         "gloss_en": "Gender agreement",
         "description": "Noun gender (masculine/feminine) and adjective agreement with it."},
        {"key": "ca_pronominal_adverbs", "level": "A2", "lesson_id": 1042, "category": "advanced",
         "title": "Els pronoms febles hi i en",
         "gloss_en": "Pronominal adverbs hi and en",
         "description": "The pronominal adverbs hi (there / about it) and en (of it/them), "
                         "with no direct English equivalent."},
        {"key": "ca_subjunctive_present", "level": "B1", "lesson_id": 1043, "category": "modals",
         "title": "Present de subjuntiu",
         "gloss_en": "Present subjunctive",
         "description": "The present subjunctive mood, triggered by expressions of wish, "
                         "doubt, emotion, or necessity (vull que..., cal que...)."},
    ],
    "German": [
        {"key": "de_gender_der_die_das", "level": "A1", "lesson_id": 1044, "category": "nouns",
         "title": "Substantivgenus: der, die, das",
         "gloss_en": "Noun gender: der/die/das",
         "description": "Noun gender (der/die/das) and how it's not predictable from meaning "
                         "-- must be learned per noun."},
        {"key": "de_cases_nom_akk", "level": "A1", "lesson_id": 1045, "category": "nouns",
         "title": "Nominativ und Akkusativ",
         "gloss_en": "Nominative and accusative case",
         "description": "Nominative (subject) vs accusative (direct object) case and how the "
                         "article changes form (der/den)."},
        {"key": "de_dative", "level": "A2", "lesson_id": 1046, "category": "nouns",
         "title": "Der Dativ",
         "gloss_en": "Dative case",
         "description": "Dative case for indirect objects and after dative prepositions/verbs "
                         "(mit, helfen, gefallen)."},
        {"key": "de_separable_verbs", "level": "A2", "lesson_id": 1047, "category": "advanced",
         "title": "Trennbare Verben",
         "gloss_en": "Separable verbs",
         "description": "Separable-prefix verbs (aufstehen -> Ich stehe auf) and where the "
                         "prefix moves to in a main clause."},
        {"key": "de_genitive", "level": "B1", "lesson_id": 1048, "category": "nouns",
         "title": "Der Genitiv",
         "gloss_en": "Genitive case",
         "description": "Genitive case for possession and after genitive prepositions "
                         "(wegen, trotz), increasingly formal but still tested."},
        {"key": "de_word_order_v2", "level": "B1", "lesson_id": 1049, "category": "advanced",
         "title": "Wortstellung: Verb-Zweit und Nebensatz",
         "gloss_en": "Word order: verb-second & subordinate clauses",
         "description": "Verb-second word order in main clauses vs verb-final word order in "
                         "subordinate clauses introduced by weil/dass/wenn."},
        {"key": "de_modal_particles", "level": "B2", "lesson_id": 1050, "category": "advanced",
         "title": "Modalpartikeln",
         "gloss_en": "Modal particles",
         "description": "Modal particles (doch, mal, ja, eben) that shade a sentence's tone "
                         "with no direct one-word English translation."},
    ],
    "Dutch": [
        {"key": "nl_gender_de_het", "level": "A1", "lesson_id": 1051, "category": "nouns",
         "title": "Lidwoorden: de en het",
         "gloss_en": "Articles: de and het",
         "description": "Noun gender as marked by de vs het, not predictable from meaning -- "
                         "must be learned per noun."},
        {"key": "nl_word_order_v2", "level": "A2", "lesson_id": 1052, "category": "advanced",
         "title": "Woordvolgorde: hoofdzin en bijzin",
         "gloss_en": "Word order: main vs subordinate clauses",
         "description": "Verb-second word order in main clauses vs verb-final word order in "
                         "subordinate clauses introduced by omdat/dat/als."},
        {"key": "nl_separable_verbs", "level": "A2", "lesson_id": 1053, "category": "advanced",
         "title": "Scheidbare werkwoorden",
         "gloss_en": "Separable verbs",
         "description": "Separable-prefix verbs (opstaan -> Ik sta op) and where the prefix "
                         "moves to in a main clause."},
        {"key": "nl_verb_clusters", "level": "B1", "lesson_id": 1054, "category": "advanced",
         "title": "Werkwoordclusters aan het einde van de zin",
         "gloss_en": "Verb clusters at the end of the clause",
         "description": "Clauses with multiple verbs stacked at the end (... dat ik had "
                         "kunnen komen) and their order."},
        {"key": "nl_modal_particles", "level": "B1", "lesson_id": 1055, "category": "advanced",
         "title": "Stopwoordjes: toch, wel, even, maar",
         "gloss_en": "Modal particles",
         "description": "Modal particles (toch, wel, even, maar) that shade a sentence's tone "
                         "with no direct one-word English translation."},
    ],
    "Japanese": [
        {"key": "ja_wa_ga", "level": "A1", "lesson_id": 1056, "category": "basics",
         "title": "は と が の違い（主題と主語）",
         "gloss_en": "Wa vs ga (topic vs subject)",
         "description": "The topic particle wa vs the subject particle ga -- a distinction "
                         "with no English equivalent, central to natural Japanese sentences."},
        {"key": "ja_core_particles", "level": "A1", "lesson_id": 1057, "category": "basics",
         "title": "助詞：を・に・で・へ",
         "gloss_en": "Core particles: wo, ni, de, e",
         "description": "The core particles wo (direct object), ni (target/time/location), de "
                         "(means/place of action), and e (direction)."},
        {"key": "ja_te_form", "level": "A2", "lesson_id": 1058, "category": "habits",
         "title": "て形の使い方",
         "gloss_en": "Te-form and its uses",
         "description": "The te-form of verbs and its many uses: requests (~てください), "
                         "sequencing actions, and asking/giving permission (~てもいいですか)."},
        {"key": "ja_plain_polite", "level": "A2", "lesson_id": 1059, "category": "advanced",
         "title": "普通形とです・ます形",
         "gloss_en": "Plain form vs polite form",
         "description": "Plain form vs polite です/ます form, and when each register is used "
                         "(casual speech/writing vs polite conversation)."},
        {"key": "ja_verb_groups", "level": "B1", "lesson_id": 1060, "category": "advanced",
         "title": "動詞のグループ（五段・一段・不規則）",
         "gloss_en": "Verb conjugation groups",
         "description": "The three verb conjugation groups (godan, ichidan, irregular) and "
                         "how each conjugates differently."},
        {"key": "ja_counters", "level": "B1", "lesson_id": 1061, "category": "nouns",
         "title": "助数詞（ものを数える）",
         "gloss_en": "Counters",
         "description": "Counter words that change depending on what's being counted (人/枚/"
                         "本/匹...), with no single equivalent in English."},
        {"key": "ja_keigo_basic", "level": "B2", "lesson_id": 1062, "category": "advanced",
         "title": "敬語の基本（尊敬語・謙譲語）",
         "gloss_en": "Basic honorific speech (keigo)",
         "description": "Basic honorific speech: respectful language (尊敬語) for others' "
                         "actions and humble language (謙譲語) for one's own."},
    ],
    "Korean": [
        {"key": "ko_topic_subject_particles", "level": "A1", "lesson_id": 1063, "category": "basics",
         "title": "은/는 과 이/가 의 차이",
         "gloss_en": "Topic vs subject particles (은/는 vs 이/가)",
         "description": "The topic particles 은/는 vs the subject particles 이/가 -- a "
                         "distinction with no English equivalent, central to natural Korean."},
        {"key": "ko_speech_levels", "level": "A1", "lesson_id": 1064, "category": "advanced",
         "title": "존댓말: 해요체, 합니다체, 반말",
         "gloss_en": "Speech levels",
         "description": "Speech levels -- casual 반말, polite 해요체, and formal 합니다체 -- "
                         "and which is appropriate for which relationship/situation."},
        {"key": "ko_counters", "level": "A2", "lesson_id": 1065, "category": "nouns",
         "title": "단위 명사 (개, 명, 권...)",
         "gloss_en": "Counters",
         "description": "Counter words that change depending on what's being counted (개/명/"
                         "권/마리...), used together with native-Korean numbers."},
        {"key": "ko_irregular_verbs", "level": "A2", "lesson_id": 1066, "category": "advanced",
         "title": "불규칙 동사 (ㅂ, ㄷ, 르 불규칙)",
         "gloss_en": "Irregular verb stems",
         "description": "Irregular verb stems (ㅂ-irregular, ㄷ-irregular, 르-irregular) whose "
                         "conjugation pattern differs from the regular rule."},
        {"key": "ko_honorifics", "level": "B1", "lesson_id": 1067, "category": "advanced",
         "title": "높임법 (-시- 와 높임 어휘)",
         "gloss_en": "Honorifics",
         "description": "Honorific marking with -시- on the verb and honorific vocabulary "
                         "substitutions for referring respectfully to someone senior."},
        {"key": "ko_connectives", "level": "B1", "lesson_id": 1068, "category": "advanced",
         "title": "연결 어미 (-고, -지만, -아서/어서, -는데)",
         "gloss_en": "Connective verb endings",
         "description": "Common connective verb endings that link two clauses (and, but, "
                         "because, background/contrast) without a separate conjunction word."},
    ],
    "Chinese": [
        {"key": "zh_measure_words", "level": "A1", "lesson_id": 1069, "category": "nouns",
         "title": "量词 (measure words)",
         "gloss_en": "Measure words",
         "description": "Measure words required between a number and a noun (一个人, 两本书), "
                         "with no equivalent in English beyond a handful of fixed phrases."},
        {"key": "zh_aspect_markers", "level": "A2", "lesson_id": 1070, "category": "past",
         "title": "了 / 过 / 着 的用法",
         "gloss_en": "Aspect markers: le, guo, zhe",
         "description": "The aspect markers le (completion), guo (past experience), and zhe "
                         "(ongoing state) -- Chinese marks aspect instead of tense."},
        {"key": "zh_resultative_complements", "level": "B1", "lesson_id": 1071, "category": "advanced",
         "title": "结果补语 (verb + result complement)",
         "gloss_en": "Resultative complements",
         "description": "Resultative verb complements (听懂, 做完, 看见) that attach a result "
                         "directly onto the verb."},
        {"key": "zh_comparison_bi", "level": "B1", "lesson_id": 1072, "category": "modals",
         "title": "比字句 (comparison with 比)",
         "gloss_en": "Comparison with bi (比)",
         "description": "The bi-construction for comparison (A 比 B + adjective), structurally "
                         "unlike English comparatives."},
        {"key": "zh_ba_construction", "level": "B1", "lesson_id": 1073, "category": "advanced",
         "title": "把字句 (the ba-construction)",
         "gloss_en": "The ba-construction (把)",
         "description": "The ba-construction, which fronts a definite direct object before the "
                         "verb to emphasize what happens to it (我把书放在桌子上)."},
        {"key": "zh_potential_directional", "level": "B2", "lesson_id": 1074, "category": "advanced",
         "title": "可能补语和趋向补语",
         "gloss_en": "Potential & directional complements",
         "description": "Potential complements (听得懂/听不懂 -- can/can't understand by "
                         "hearing) and directional complements (拿出来, 走进去)."},
    ],
}

# lesson_id -> full topic dict, built once at import (every topic across all
# languages has a globally-unique lesson_id, see the module docstring).
LESSON_ID_TO_TOPIC: dict[int, dict] = {
    topic["lesson_id"]: {**topic, "target_lang": lang}
    for lang, topics in TARGET_GRAMMAR_PATHS.items()
    for topic in topics
}


def paths_for_language(target_lang: str) -> list[dict]:
    """All target-specific grammar topics for target_lang, or [] if none registered."""
    return TARGET_GRAMMAR_PATHS.get(target_lang, [])


def topic_for_lesson_id(lesson_id: int) -> dict | None:
    """Reverse lookup used by engine.target_grammar_loader / engine.picker to
    resolve one of these synthetic lesson_ids (>=1000) back to its topic dict
    (and, via the injected "target_lang" key, which language it belongs to)."""
    return LESSON_ID_TO_TOPIC.get(lesson_id)
