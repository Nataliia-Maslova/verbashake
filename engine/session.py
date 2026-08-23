"""
LessonSession — state machine for lesson-based learning (7 steps).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from engine.scorer import evaluate


@dataclass
class SessionState:
    user_id:         str
    lesson_id:       int
    native_lang:     str
    target_lang:     str
    language_pair:   str       = ""     # e.g. "en-uk"
    unit_id:         str | None = None  # e.g. "grammar:42" — content_units key, feeds the recommender.
                                         # None for untracked lessons (e.g. custom_app.py's user phrases).
    current_step:    int   = 1
    phrase_index:    int   = 0
    step_start_ts:   float = field(default_factory=time.time)
    lesson_complete: bool  = False


class LessonSession:
    def __init__(self, user_id, lesson_df, lesson_id,
                 native_lang, target_lang, language_pair="", unit_id=None):
        self.df     = lesson_df.reset_index(drop=True)
        self._fill_missing_translations(native_lang, target_lang)
        self.state  = SessionState(
            user_id=user_id, lesson_id=lesson_id,
            native_lang=native_lang, target_lang=target_lang,
            language_pair=language_pair, unit_id=unit_id,
        )
        self._step_start: dict[int, float] = {}

    def _fill_missing_translations(self, native_lang: str, target_lang: str) -> None:
        """
        Best-effort on-demand translation for phrases loaded without native
        and/or target text -- currently only engine.cefr_j_vocab_loader's
        CEFR-J Vocabulary content (one canonical English `source_en`
        sentence per row, CLAUDE.md 2026-08-22: the same word list is
        now the Vocabulary source for every target_lang, not just English).
        Rather than pre-translating ~9.8k rows per language upfront,
        engine.gemini.translate_phrase is called here for just the ~10
        phrases of the lesson actually opened (cached both in-process and
        in Supabase's phrase_translations, so repeat opens -- by this
        student or any other -- are free). translate_phrase is paid-gated
        -- a free-tier user just gets the English source text left in the
        missing column too (lesson stays usable, monolingual), same
        "free = zero live AI" fallback used everywhere else Gemini is
        optional. Not called at all when every row already has native and
        target text (every other loader in the app).
        """
        if "source_en" not in self.df.columns:
            return
        from engine import gemini
        for col, lang in (("native", native_lang), ("target", target_lang)):
            if col not in self.df.columns:
                continue
            missing = self.df[col].isna() | (self.df[col].astype(str).str.strip() == "")
            if not missing.any():
                continue
            if lang == "English":
                self.df.loc[missing, col] = self.df.loc[missing, "source_en"]
                continue
            for idx in self.df.index[missing]:
                source_text = self.df.at[idx, "source_en"]
                try:
                    self.df.at[idx, col] = gemini.translate_phrase(
                        source_text, "English", lang)
                except gemini.PaidFeatureRequired:
                    self.df.loc[missing, col] = self.df.loc[missing, "source_en"]
                    break
                except Exception:
                    self.df.at[idx, col] = source_text

    # ── Step timing ──────────────────────────────────────────────────────

    def start_step(self, step: int):
        self._step_start[step] = time.time()

    def elapsed_ms(self, step: int) -> int:
        start = self._step_start.get(step, self.state.step_start_ts)
        return int((time.time() - start) * 1000)

    # ── Navigation ───────────────────────────────────────────────────────

    def next_phrase(self):
        self.state.phrase_index  += 1
        self.state.step_start_ts  = time.time()
        if self.state.phrase_index >= len(self.df):
            self.next_step()

    def next_step(self):
        self.state.current_step  += 1
        self.state.phrase_index   = 0
        self.state.step_start_ts  = time.time()
        if self.state.current_step > 8:
            self.state.lesson_complete = True

    def go_to_step(self, step: int):
        self.state.current_step  = step
        self.state.phrase_index  = 0
        self.state.step_start_ts = time.time()
        if step > 8:
            self.state.lesson_complete = True

    # ── Getters ──────────────────────────────────────────────────────────

    def phrases(self):
        return self.df.to_dict("records")

    def current_phrase(self):
        if self.state.phrase_index >= len(self.df):
            return self.df.iloc[-1].to_dict()
        return self.df.iloc[self.state.phrase_index].to_dict()

    def progress(self):
        return self.state.phrase_index + 1, len(self.df)

    def total(self):
        return len(self.df)

    # ── Evaluation ───────────────────────────────────────────────────────

    def score(self, user_input: str, expected: str,
              step: int | None = None,
              phrase_id: int | None = None,
              duration_ms: int | None = None) -> dict:
        """
        Evaluate the answer and feed the result to the recommender (mastery +
        SRS update for self.state.unit_id), if this session is tracked.
        """
        result = evaluate(user_input, expected)
        if self.state.unit_id:
            try:
                from engine import recommender
                recommender.record_result(
                    self.state.user_id, self.state.target_lang,
                    self.state.unit_id, result["passed"],
                )
            except Exception:
                pass
        return result

    def score_phrase(self, user_input: str, phrase: dict, step: int) -> dict:
        return self.score(
            user_input = user_input,
            expected   = phrase["target"],
            step       = step,
            phrase_id  = int(phrase.get("phrase_id", 0)),
        )

    def complete(self):
        """Call when lesson is fully done — updates the resume pointer."""
        if self.state.unit_id:
            try:
                from engine import recommender
                module = self.state.unit_id.split(":", 1)[0]
                recommender.save_pointer(
                    self.state.user_id, self.state.target_lang,
                    module, self.state.unit_id, step=99,
                )
            except Exception:
                pass
