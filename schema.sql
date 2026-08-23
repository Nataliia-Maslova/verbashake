-- VerbaShake — Phase C schema (Postgres / Supabase).
-- Replaces: engine/curriculum.py's JSON progress file, engine/adaptive.py's
-- per-session RandomForest, engine/logger.py's per-step Sheets/CSV log +
-- "progress" sheet, and data/gamification.csv.
--
-- Run once against a fresh Supabase project (SQL editor, or `psql "$DATABASE_URL" -f schema.sql`).

-- ── content_units ────────────────────────────────────────────────────────────
-- Canonical registry of every learnable LESSON across modules (lesson-level,
-- matching what the UI actually launches — not one row per phrase/word).
-- lesson_id is NOT globally unique across the source Excel files (grammar/
-- vocab/reading each restart numbering from 1), so unit_id namespaces it:
--   grammar:<lesson_id>
--   vocab:<sheet_name>:<lesson_id>       (also used by phrasebook -- same
--                                         sheets/gids, just a different
--                                         `module` tag, see CLAUDE.md
--                                         2026-08-21 Vocabulary/Phrasebook split)
--   reading:<lang_code>:<lesson_number>
-- level/topic are the tags the recommender scores against, on one shared CEFR
-- vocabulary (A1..C2) across all three modules — grammar's are auto-derived
-- from imlls_database_with_titles.xlsx (topic_en + difficulty bucketed into
-- CEFR bands); vocab/reading need to be filled in from the *_tags_template.csv
-- files using the same A1..C2 labels so novelty scoring stays comparable
-- across modules.
-- 'phrasebook' added 2026-08-21: vocabulary_translated.xlsx's sheets minus
-- the "Word Bank" ones (Basic/Verbs/Food/City -- being replaced by a
-- CEFR-J-based Vocabulary module instead, see engine/vocab_loader.py's
-- WORD_BANK_SHEETS) are thematic collocations/phrases, not raw word lists --
-- split into their own module rather than lumped under "vocab".
-- 'target_grammar' added 2026-08-23: engine/target_grammar_paths.py's
-- roadmap of grammar topics genuine to one specific target language (Slavic
-- aspect, ser/estar, keigo...) with no imlls_database lesson at all --
-- unit_id = target_grammar:<lang_code>:<topic_key>, source_lesson =
-- <lang_code> (locks each unit to its one target language, same mechanism
-- "reading" already uses -- see engine/recommender.py::_candidates()).
CREATE TABLE IF NOT EXISTS content_units (
    unit_id       TEXT PRIMARY KEY,
    module        TEXT NOT NULL CHECK (module IN ('grammar', 'vocab', 'reading', 'phrasebook', 'target_grammar')),
    source_lesson TEXT NOT NULL,      -- original lesson_id (grammar/vocab) or lang_code (reading)
    source_item   TEXT,               -- unused in V1, reserved for future finer-than-lesson tracking
    level         TEXT,               -- CEFR label: A1 | A2 | B1 | B2 | C1 | C2
    topic         TEXT,               -- topic tag, English canonical form
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_content_units_module_topic ON content_units (module, topic);

-- ── mastery ──────────────────────────────────────────────────────────────────
-- Running EMA of correctness per (user, target_lang, module, topic). This is
-- the "mastery gap" input to the recommender's scoring formula.
CREATE TABLE IF NOT EXISTS mastery (
    user_id     TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    module      TEXT NOT NULL,
    topic       TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0.5,   -- EMA of correctness, 0..1
    n_attempts  INT  NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, target_lang, module, topic)
);

-- ── srs_state ────────────────────────────────────────────────────────────────
-- Spaced-repetition bookkeeping per (user, target_lang, content unit). This is
-- the "SRS urgency" input to the recommender's scoring formula.
CREATE TABLE IF NOT EXISTS srs_state (
    user_id       TEXT NOT NULL,
    target_lang   TEXT NOT NULL,
    unit_id       TEXT NOT NULL REFERENCES content_units(unit_id),
    interval_days REAL NOT NULL DEFAULT 1,
    due_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    last_result   BOOLEAN,
    reps          INT  NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, target_lang, unit_id)
);
CREATE INDEX IF NOT EXISTS idx_srs_state_due ON srs_state (user_id, target_lang, due_date);

-- ── lesson_pointer ───────────────────────────────────────────────────────────
-- Lightweight "where am I right now" resume pointer (mid-lesson step), one row
-- per (user, target_lang, module) — grammar/vocab/reading are independent
-- tracks, same as the old language_pair string's module suffix ("en-uk-vocab"
-- vs "en-uk-grammar") kept them separate. Replaces logger.py's "progress"
-- Sheets tab and curriculum.py's JSON index file. last_step convention
-- unchanged: 1..8 = mid-lesson position, 99 = lesson fully complete (sentinel).
CREATE TABLE IF NOT EXISTS lesson_pointer (
    user_id     TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    module      TEXT NOT NULL,
    unit_id     TEXT NOT NULL,
    step        INT  NOT NULL DEFAULT 1,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, target_lang, module)
);

-- ── subscriptions ────────────────────────────────────────────────────────────
-- Phase D: cached Stripe subscription status per user (user_id = Google account
-- email via st.login()). Polled from the Stripe API (engine/billing.py) rather
-- than pushed via webhooks — Streamlit has no route for Stripe to POST to, so
-- V1 re-checks Stripe on login / periodically instead of reacting to events in
-- real time. status starts 'free' for every user; becomes 'active' after a
-- successful Stripe Checkout, and engine.billing re-verifies it against Stripe
-- when the cached row goes stale (see _STALE_AFTER in engine/billing.py).
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id                 TEXT PRIMARY KEY,
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    status                  TEXT NOT NULL DEFAULT 'free',   -- free | active | past_due | canceled
    plan                    TEXT,
    current_period_end      TIMESTAMPTZ,
    checked_at              TIMESTAMPTZ NOT NULL DEFAULT now(),   -- last time we polled Stripe
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── gamification ─────────────────────────────────────────────────────────────
-- Same fields as the old data/gamification.csv, just DB-backed so it survives
-- Streamlit Cloud redeploys (the CSV had the exact same ephemeral-filesystem
-- exposure the mastery/SRS data would have had on local SQLite).
CREATE TABLE IF NOT EXISTS gamification (
    user_id             TEXT PRIMARY KEY,
    streak_current      INT  NOT NULL DEFAULT 0,
    streak_max          INT  NOT NULL DEFAULT 0,
    streak_last_date    TEXT NOT NULL DEFAULT '',
    xp_total            INT  NOT NULL DEFAULT 0,
    lessons_completed   INT  NOT NULL DEFAULT 0,
    daily_xp_date       TEXT NOT NULL DEFAULT '',
    daily_xp            INT  NOT NULL DEFAULT 0,
    badges              TEXT NOT NULL DEFAULT '',   -- comma-joined badge ids, same as before
    total_time_minutes  REAL NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── phrase_translations ─────────────────────────────────────────────────────
-- Persistent cache for engine.gemini.translate_phrase (2026-08-22): CEFR-J
-- Vocabulary content (engine/cefr_j_vocab_loader.py) is English-only in
-- vocabulary_cefrj.csv, native-language text is translated live on first
-- open of each lesson. The local diskcache other Gemini calls use (.cache/
-- gemini/) has the exact same ephemeral-filesystem exposure on Streamlit
-- Cloud that mastery/SRS/gamification had before moving to this DB -- wiped
-- on every redeploy, so every re-deploy would re-pay Gemini for words
-- students already had translated. This table survives redeploys; the local
-- diskcache still sits in front of it for same-process speed.
CREATE TABLE IF NOT EXISTS phrase_translations (
    phrase_hash  TEXT PRIMARY KEY,   -- sha256(from_lang|to_lang|phrase), keeps the PK compact
    from_lang    TEXT NOT NULL,
    to_lang      TEXT NOT NULL,
    phrase       TEXT NOT NULL,
    translation  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── lesson_explanations ─────────────────────────────────────────────────────
-- Step 1 ("Read out loud") rule explanation cache (CLAUDE.md idea A,
-- 2026-08-23; engine/gemini.py::explain_lesson_rule). Same reasoning as
-- phrase_translations above: the rule/examples/exceptions for a given
-- (topic, level, target_lang, native_lang) are identical for every student
-- who opens that lesson, so this is a one-time Gemini cost per lesson x
-- language pair for the whole project, not per pageview.
CREATE TABLE IF NOT EXISTS lesson_explanations (
    explanation_hash TEXT PRIMARY KEY,  -- sha256(target_lang|native_lang|level|topic)
    topic        TEXT NOT NULL,
    level        TEXT NOT NULL,
    target_lang  TEXT NOT NULL,
    native_lang  TEXT NOT NULL,
    explanation  JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── user_prefs ───────────────────────────────────────────────────────────────
-- Native/target language choice per user (2026-08-22). Previously the
-- launcher's language selectors only lived in st.session_state, which resets
-- on every fresh login/browser session (and never survives a Streamlit Cloud
-- redeploy) — a returning student had to re-pick their languages every
-- single time. This makes that choice sticky across sessions and devices,
-- the same way progress already is (see engine/user_prefs.py).
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id      TEXT PRIMARY KEY,
    native_lang  TEXT,
    target_lang  TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
