"""
Smoke tests -- catch import breakage, data-file corruption and loader
regressions without a live Streamlit session, real login, or (for most
tests) a live DATABASE_URL/GEMINI_API_KEY.

Run: python -m pytest tests/ -q  (from the repo root, inside venv)

These are NOT a substitute for the "жива перевірка" (real browser click-
through) this project relies on for UI/UX correctness -- they only catch
the class of bug that a full py_compile + a real function call would catch:
missing sheets/columns, wrong dict keys, exceptions on real data, obviously
broken language coverage. Kept fast and read-only; no test writes to the
live DB except test_recommender_db_roundtrip, which is opt-in (skipped
unless DATABASE_URL is configured) and always cleans up its own rows.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# 1. Every module imports cleanly (catches syntax errors, missing deps,
#    the Python-3.9 "X | None" without __future__ class of bug documented
#    in CLAUDE.md, top-level code that throws on import).
# ---------------------------------------------------------------------------

ENGINE_MODULES = [
    "engine.loader", "engine.vocab_loader", "engine.cefr_j_vocab_loader",
    "engine.cefr_wordlist", "engine.target_grammar_loader",
    "engine.target_grammar_paths", "engine.recommender", "engine.scorer",
    "engine.i18n", "engine.session", "engine.gamification", "engine.db",
    "engine.characters", "engine.schedule", "engine.literacy",
    "engine.mistakes", "engine.user_prefs", "engine.youtube_links",
    "engine.picker", "engine.client_tz", "engine.warmup_loader",
    "engine.constructions", "engine.analyzer", "engine.rate_limit",
]

TOP_LEVEL_MODULES = [
    "grammar", "reading_app", "app", "path_app", "search_app",
    "custom_app", "mistakes_app",
]


@pytest.mark.parametrize("name", ENGINE_MODULES)
def test_engine_module_imports(name):
    importlib.import_module(name)


@pytest.mark.parametrize("name", TOP_LEVEL_MODULES)
def test_top_level_module_imports(name):
    # These call st.set_page_config() at import time, guarded by the
    # project's own try/except (see grammar.py/reading_app.py) -- safe to
    # import repeatedly and outside a real Streamlit run.
    importlib.import_module(name)


# ---------------------------------------------------------------------------
# 2. Data files load with the app's own loaders, for a spread of language
#    pairs -- not just English, which is the only pair someone editing the
#    xlsx by hand tends to eyeball.
# ---------------------------------------------------------------------------

from engine import loader, vocab_loader, recommender  # noqa: E402

DB_PATH = str(ROOT / "data" / "imlls_database_with_titles.xlsx")
VOCAB_PATH = str(ROOT / "data" / "vocabulary_translated.xlsx")

SAMPLE_LANG_PAIRS = [
    ("English", "Ukrainian"), ("Russian", "Spanish"), ("Korean", "German"),
    ("Ukrainian", "Japanese"), ("Chinese", "French"), ("English", "Swedish"),
    ("Polish", "Turkish"), ("English", "Bulgarian"),
]


@pytest.mark.parametrize("native,target", SAMPLE_LANG_PAIRS)
def test_grammar_loader_all_sample_pairs(native, target):
    df = loader.load_phrases(DB_PATH, native, target)
    assert len(df) > 0, f"no grammar phrases for {native}->{target}"
    assert {"native", "target", "lesson_id", "phrase_id"} <= set(df.columns)
    assert df["native"].astype(str).str.strip().eq("").sum() == 0
    assert df["target"].astype(str).str.strip().eq("").sum() == 0


def test_grammar_loader_all_182_lessons_present_for_english_ukrainian():
    df = loader.load_phrases(DB_PATH, "English", "Ukrainian")
    assert sorted(df["lesson_id"].unique()) == list(range(1, 183))


def test_vocab_loader_word_bank_and_phrasebook_partition_cleanly():
    word_bank = vocab_loader.load_vocab(
        VOCAB_PATH, "English", "English",
        include_sheets=vocab_loader.WORD_BANK_SHEETS)
    phrasebook = vocab_loader.load_vocab(
        VOCAB_PATH, "English", "English",
        exclude_sheets=vocab_loader.WORD_BANK_SHEETS)
    assert len(word_bank) > 0 and len(phrasebook) > 0
    assert set(word_bank["topic"]) == vocab_loader.WORD_BANK_SHEETS
    assert set(phrasebook["topic"]).isdisjoint(vocab_loader.WORD_BANK_SHEETS)


CEFRJ_PATH = str(ROOT / "data" / "vocabulary_cefrj.csv")


@pytest.mark.parametrize("target", ["Spanish", "Korean", "Catalan", "Romanian"])
def test_cefrj_vocabulary_loads_for_non_english_target(target):
    from engine import cefr_j_vocab_loader
    df = cefr_j_vocab_loader.load_cefrj_vocab(CEFRJ_PATH, native_lang="English", target_lang=target)
    assert len(df) > 0
    assert "source_en" in df.columns


# ---------------------------------------------------------------------------
# 3. Reading: every language the app claims to support (reading_app.TTS_CONFIG)
#    actually has a loadable sheet with real rows.
# ---------------------------------------------------------------------------

import reading_app  # noqa: E402

READING_PATH = str(ROOT / "data" / "reading_lessons.xlsx")


@pytest.mark.parametrize("lang", sorted(reading_app.TTS_CONFIG))
def test_reading_load_every_supported_language(lang):
    df = reading_app.load(READING_PATH, lang=lang, native_lang="English")
    assert len(df) > 0, f"reading_app.load() returned 0 rows for {lang}"
    assert df["word"].astype(str).str.strip().eq("").sum() == 0
    # Regression guard for the 2026-09-22 bug: ro/bg/cs/tr/sv silently lost
    # their "rule" column by falling into the uk/es 4-column branch.
    if lang in ("en", "ko", "fr", "de", "ja", "zh", "pt", "it", "pl", "ru",
                "nl", "ca", "ro", "bg", "cs", "tr", "sv"):
        assert "rule" in df.columns


def test_reading_no_duplicate_lesson_row_within_any_language():
    for lang in reading_app.TTS_CONFIG:
        df = reading_app.load(READING_PATH, lang=lang, native_lang="English")
        dup = df.duplicated(subset=["lesson_id", "row_id"])
        assert not dup.any(), f"{lang}: duplicate (lesson_id,row_id) rows"


# ---------------------------------------------------------------------------
# 4. target_grammar: every registered topic actually has generated drill
#    sentences on disk, and the loader returns them without needing Gemini
#    when native_lang == target_lang (pure pool read, no live translation).
# ---------------------------------------------------------------------------

from engine import target_grammar_paths, target_grammar_loader  # noqa: E402

_ALL_TOPICS = [
    (lang, t["key"])
    for lang in ("Ukrainian", "Russian", "Polish", "Spanish", "Portuguese",
                 "French", "Italian", "Catalan", "German", "Dutch",
                 "Japanese", "Korean", "Chinese", "Romanian", "Bulgarian",
                 "Czech", "Turkish", "Swedish")
    for t in target_grammar_paths.paths_for_language(lang)
]


@pytest.mark.parametrize("lang,topic_key", _ALL_TOPICS)
def test_target_grammar_drills_exist_for_every_registered_topic(lang, topic_key):
    rows = target_grammar_loader.load_topic_drills(lang, topic_key, native_lang=lang, n=8)
    assert len(rows) > 0, f"no generated drill sentences for {lang}/{topic_key}"
    for r in rows:
        assert r["target"].strip()
        assert r["native"] == r["target"]  # native==target path: no Gemini call


# ---------------------------------------------------------------------------
# 5. i18n: a handful of load-bearing keys resolve to a real (non-empty,
#    non-crashing) string for every supported language -- catches a broken
#    merge of data/i18n_generated.json before it reaches the UI.
# ---------------------------------------------------------------------------

from engine import i18n  # noqa: E402

CORE_I18N_KEYS = [
    "step_label", "required", "main_menu", "module_grammar", "module_vocab",
    "module_phrasebook", "module_reading", "word_lesson",
    "rule_explanation_title", "schedule_section_title",
]


@pytest.mark.parametrize("lang", sorted(i18n.LANG_TO_CODE))
@pytest.mark.parametrize("key", CORE_I18N_KEYS)
def test_i18n_core_keys_resolve_for_every_language(lang, key):
    value = i18n.get(lang, key)
    assert isinstance(value, str) and value.strip(), f"{lang}/{key} is empty"


DIALOGUE_I18N_KEYS = [
    # Added 2026-09-23 (warmup / Phase 4 Open Question & Roleplay / app.py
    # sidebar) after finding them hardcoded English on every screen they
    # appear on -- regression guard against them silently dropping a
    # language again.
    "submit_btn", "evaluating_spinner", "generating_warmup_spinner",
    "generating_speaking_task_spinner", "submit_chat_tutor_btn",
    "submit_voice_btn", "grammar_checked_caption", "chat_with_tutor_header",
    "chat_with_tutor_caption", "chat_role_you", "chat_role_tutor",
    "chat_message_placeholder", "tutor_typing_spinner", "finish_lesson_btn",
    "sidebar_free_plan", "sidebar_premium", "sidebar_continue_checkout_btn",
    "sidebar_upgrade_btn", "sidebar_signout_btn", "checkout_unavailable_error",
]


@pytest.mark.parametrize("lang", sorted(i18n.LANG_TO_CODE))
@pytest.mark.parametrize("key", DIALOGUE_I18N_KEYS)
def test_i18n_dialogue_keys_resolve_for_every_language(lang, key):
    value = i18n.get(lang, key)
    assert isinstance(value, str) and value.strip(), f"{lang}/{key} is empty"
    assert "✅" not in value and "❌" not in value, f"{lang}/{key} has stray emoji: {value!r}"


def test_i18n_lang_to_code_matches_loader_lang_columns():
    # These two maps have drifted apart before (CLAUDE.md, 2026-08-22 i18n
    # audit) -- keep them in lockstep so a newly-added language can't be
    # missing from one of the two.
    assert set(i18n.LANG_TO_CODE) == set(loader.LANG_COLUMNS)


# ---------------------------------------------------------------------------
# 6. Pure-function sanity: scorer, search matching, recommender unit-id
#    round-trips -- cheap, no I/O, catch regressions in logic everything
#    else depends on.
# ---------------------------------------------------------------------------

from engine import scorer  # noqa: E402
from search_app import _match_score  # noqa: E402


def test_scorer_exact_match_is_correct():
    result = scorer.evaluate("hello world", "hello world")
    assert result["passed"] is True
    assert result["score"] == 1.0


def test_scorer_typo_is_close_but_flagged():
    result = scorer.evaluate("helo wrold", "hello world")
    assert 0 < result["score"] < 1


def test_search_match_score_prefers_exact_word_over_substring():
    # Tiers per search_app._match_score (CLAUDE.md, 2026-09-20 rewrite):
    # whole word 100 -> start-of-word 97 -> infix (query >=5 chars) 94 -> fuzzy -> 0.
    exact = _match_score("hello", "hello")
    prefix = _match_score("hel", "hello")
    infix = _match_score("ellow", "yellow")  # 5-char query, matches mid-word
    unrelated = _match_score("xyz", "hello")
    assert exact > prefix > infix > unrelated == 0


@pytest.mark.parametrize("module,target,extra", [
    ("grammar", 42, None),
    ("vocab", 12, "Food"),
    ("phrasebook", 474, "Hobbies"),
    ("target_grammar", None, ("uk", "uk_aspect_basic")),
])
def test_recommender_unit_id_round_trip(module, target, extra):
    if module == "target_grammar":
        lang, topic_key = extra
        unit_id = recommender.target_grammar_unit_id(lang, topic_key)
    else:
        unit_id = recommender.unit_id_for(module, target, extra)
    assert unit_id is not None
    parsed = recommender.parse_unit_id(unit_id)
    assert parsed["module"] == module


def test_recommender_reading_unit_id_round_trip():
    # reading builds its own "reading:<lang_code>:<lesson_id>" string directly
    # (reading_app.py/search_app.py/seed_content_units.py) rather than going
    # through unit_id_for() -- exercise that exact shape here.
    unit_id = "reading:es:7"
    parsed = recommender.parse_unit_id(unit_id)
    assert parsed["module"] == "reading"


def test_difficulty_to_cefr_covers_full_1_to_6_range():
    for d in range(1, 7):
        assert d in recommender.DIFFICULTY_TO_CEFR


def test_schedule_today_status_survives_midnight_crossing():
    # Regression test for the 2026-09-23 fix: a late-evening slot (e.g.
    # Monday 23:45) whose +-TOLERANCE_MINUTES grace window crosses into the
    # next calendar day used to vanish the instant the clock ticked past
    # midnight (today_entry was looked up by *today's* weekday only).
    import datetime as dt
    from unittest.mock import patch
    from engine import schedule

    class FakeDT(dt.datetime):
        _now = None

        @classmethod
        def now(cls, tz=None):
            return cls._now.replace(tzinfo=tz)

    def status_at(when, entries, done_today=False):
        FakeDT._now = when
        with patch("engine.schedule.get_schedule", return_value=entries):
            with patch("engine.schedule._dt.datetime", FakeDT):
                return schedule.today_status("u", done_today=done_today)

    monday_entry = [{"day_of_week": 0, "time_of_day": "23:45"}]  # Monday
    # 2026-09-21 is a Monday -> 2026-09-22 00:10 is 25 minutes later, still
    # within the default 30-minute tolerance.
    still_in_window = status_at(dt.datetime(2026, 9, 22, 0, 10), monday_entry)
    assert still_in_window["state"] == "in_window"

    long_past = status_at(dt.datetime(2026, 9, 22, 0, 40), monday_entry)
    assert long_past["state"] != "in_window"

    # An ordinary same-day lookup (no midnight crossing involved, and well
    # outside the +-30min tolerance either side) must be completely
    # unaffected by the new branch.
    ordinary = status_at(dt.datetime(2026, 9, 22, 8, 0),
                          [{"day_of_week": 1, "time_of_day": "10:15"}])  # Tuesday
    assert ordinary["state"] == "not_yet"


# ---------------------------------------------------------------------------
# 7. Every .py file in the repo (outside venv/scratch) compiles under the
#    interpreter running the tests -- cheap, catches syntax slips fast
#    without needing to import each one's runtime dependencies.
# ---------------------------------------------------------------------------

import py_compile  # noqa: E402

EXCLUDED_DIRS = {"venv", ".venv", "__pycache__", ".git"}


def _all_py_files():
    for p in ROOT.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in p.parts):
            continue
        yield p


@pytest.mark.parametrize("path", list(_all_py_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_py_compile(path):
    py_compile.compile(str(path), doraise=True)


# ---------------------------------------------------------------------------
# 8. Phrasebook sheets: every language column must be row-aligned with `en`
#    (2026-09-25: Restaurant's uk/es/ko had been stored at stride 2, so
#    uk-native students got pairs like "Я б хотів забронювати столик…" next
#    to "demandez le menu").
# ---------------------------------------------------------------------------

def _phrasebook_sheets():
    import pandas as pd
    xl = pd.ExcelFile(ROOT / "data" / "vocabulary_translated.xlsx")
    return [s for s in xl.sheet_names if s not in vocab_loader.WORD_BANK_SHEETS]


@pytest.mark.parametrize("sheet", _phrasebook_sheets())
def test_phrasebook_sheet_languages_row_aligned_with_english(sheet):
    import pandas as pd
    d = pd.read_excel(ROOT / "data" / "vocabulary_translated.xlsx", sheet_name=sheet)
    en = d["en"].notna()
    for lang in ("uk", "es", "ko", "fr", "de", "ja", "zh", "pt", "it", "pl",
                 "ru", "ca", "nl", "ro", "bg", "cs", "tr", "sv"):
        if lang in d.columns:
            mism = int((d[lang].notna() != en).sum())
            assert mism <= 1, f"{sheet}/{lang}: {mism} rows not aligned with en"


# ---------------------------------------------------------------------------
# 9. Language-specific verb-row lessons (2026-09-25)
# ---------------------------------------------------------------------------

def test_target_grammar_lesson_ids_globally_unique():
    ids = [t["lesson_id"] for ts in target_grammar_paths.TARGET_GRAMMAR_PATHS.values() for t in ts]
    assert len(ids) == len(set(ids))


def test_verb_row_topics_have_eight_three_part_rows_without_repeated_verbs():
    from engine.verb_form_topics import SPECS, ROWS_PER_GROUP, GROUPS
    for lang in SPECS:
        infs = []
        for t in target_grammar_paths.paths_for_language(lang):
            if "_verb_rows_" not in t["key"]:
                continue
            rows = target_grammar_loader.load_topic_drills(lang, t["key"], native_lang=lang, n=50)
            assert len(rows) == ROWS_PER_GROUP, (lang, t["key"], len(rows))
            for r in rows:
                parts = r["target"].split(" - ")
                assert len(parts) == 3, r["target"]
                infs.append(parts[0].strip())
        assert len(infs) == ROWS_PER_GROUP * GROUPS and len(set(infs)) == len(infs), lang


def test_english_verb_lists_hidden_for_other_targets_but_kept_for_english():
    import grammar
    from engine.verb_form_topics import ENGLISH_PIVOT_VERB_LESSONS
    es = set(grammar._load_grammar(grammar.DB_PATH, "Ukrainian", "Spanish")["lesson_id"])
    en = set(grammar._load_grammar(grammar.DB_PATH, "Ukrainian", "English")["lesson_id"])
    assert not (es & ENGLISH_PIVOT_VERB_LESSONS)
    assert ENGLISH_PIVOT_VERB_LESSONS <= en


# ---------------------------------------------------------------------------
# 10. Design-token contrast (WCAG AA) -- 2026-09-25: white text on the coral
#     CTA was 2.5:1, dark-mode "ink" text colours were never overridden.
# ---------------------------------------------------------------------------

def _tokens(block_start):
    import re
    css = (ROOT / "static" / "mova" / "tokens.css").read_text(encoding="utf-8")
    i = css.index(block_start)
    j = css.index("}", i)
    return dict(re.findall(r"--mova-([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", css[i:j]))


def _contrast(a, b):
    def lum(h):
        h = h.lstrip("#")
        r, g, bl = [int(h[k:k + 2], 16) / 255 for k in (0, 2, 4)]
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_light_theme_text_contrast_meets_aa():
    t = _tokens(":root {")
    for fg, bg in [("ink", "surface"), ("ink-2", "surface"), ("ink-3", "surface"), ("ink-3", "surface-2"),
                   ("ink-on-coral", "coral"), ("ink-on-coral", "coral-press"), ("indigo-ink", "indigo-soft"),
                   ("coral-ink", "coral-soft"), ("mint-ink", "mint-soft"), ("amber-ink", "amber-soft")]:
        assert _contrast(t[fg], t[bg]) >= 4.5, (fg, bg, _contrast(t[fg], t[bg]))


def test_dark_theme_text_contrast_meets_aa():
    light = _tokens(":root {")
    dark = {**light, **_tokens('[data-theme="dark"] {')}
    for fg, bg in [("ink", "surface"), ("ink-2", "card"), ("ink-3", "card"), ("indigo-ink", "indigo-soft"),
                   ("coral-ink", "coral-soft"), ("mint-ink", "mint-soft"), ("amber-ink", "amber-soft")]:
        assert _contrast(dark[fg], dark[bg]) >= 4.5, (fg, bg, _contrast(dark[fg], dark[bg]))


PLAYER_I18N_KEYS = ["player_play_all", "player_ready", "player_done", "player_phrase",
                    "player_stopped", "player_stop", "player_label"]


@pytest.mark.parametrize("lang", sorted(i18n.LANG_TO_CODE))
@pytest.mark.parametrize("key", PLAYER_I18N_KEYS)
def test_audio_player_strings_localized_for_every_language(lang, key):
    v = i18n.get(lang, key)
    assert isinstance(v, str) and v.strip()
    assert "✅" not in v and "❌" not in v


def test_audio_player_html_uses_localized_strings_and_readable_grey():
    import grammar
    html = grammar.autoplaylist_with_table([{"native": "a", "target": "b"}], [""], [1.0], uid="t", native_lang="Ukrainian")
    assert "Відтворити все" in html and 'aria-live="polite"' in html
    assert "#7A7390" not in html   # was 4.2:1 on white
