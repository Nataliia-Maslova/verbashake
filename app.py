"""
IMLLS - main launcher.

Run:
    streamlit run app.py

Lets the user choose between three practice modes at the start of a session:
  - Grammar  (uses grammar.py + data/imlls_database.xlsx)
  - Vocabulary (uses grammar.py with module="vocab" + data/vocabulary.xlsx)
  - Reading (uses reading_app.py + data/reading_lessons.xlsx)

Each module has its own resume pointer tracked separately (engine.recommender's
lesson_pointer table, keyed by user/target_lang/module).

The main menu also shows a per-module progress bar (% of all exercises
completed and "exercise N of M"), so the user always knows where they are
on their learning path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# IMPORTANT: page config must be the very first Streamlit call
st.set_page_config(
    page_title="IMLLS",
    page_icon="🎓",
    layout="wide",
    # 'auto' lets the user keep the sidebar open inside lessons (for nav)
    # while still allowing them to collapse it on the launcher.
    initial_sidebar_state="auto",
)

# Import after set_page_config so the sub-apps' guarded set_page_config calls
# are no-ops (they're wrapped in try/except).
import grammar as grammar_app          # noqa: E402
import reading_app                  # noqa: E402
import custom_app                   # noqa: E402
import path_app                     # noqa: E402
import search_app                   # noqa: E402
from engine import auth_gate        # noqa: E402
from engine import billing          # noqa: E402
from engine import user_prefs       # noqa: E402
from engine.gamification import sidebar_widget  # noqa: E402

# Used for fetching progress on the launcher
from engine.loader  import (                  # noqa: E402
    load_phrases, get_available_lessons,
)
from engine.vocab_loader import (             # noqa: E402
    load_vocab, get_available_vocab_lessons,
)
from engine.custom_store import list_user_lessons  # noqa: E402
from engine import placement_quiz                   # noqa: E402
from engine import i18n                              # noqa: E402


def _app_url() -> str:
    """The app's own public URL, for Stripe Checkout's success/cancel redirect.
    Derived from the [auth] redirect_uri (already required for st.login()) so
    there's no separate secret to configure — falls back to localhost for
    local dev before secrets are set up."""
    try:
        redirect_uri = st.secrets["auth"]["redirect_uri"]
        return redirect_uri.rsplit("/oauth2callback", 1)[0]
    except Exception:
        return "http://localhost:8501"


# ═══════════════════════════════════════════════════════════════════════════
# Mova design system — Phase 1 integration
# ═══════════════════════════════════════════════════════════════════════════
MOVA_DIR = ROOT / "static" / "mova"

# Phase 1 CSS overrides on top of the three Mova files.
# - Relax container max-width so existing wide tables still fit (Mova default
#   is 720px which is too narrow for our two-column phrase tables).
# - Preserve a small no-op so future tweaks have a place to live.
_MOVA_LOCAL_OVERRIDES = """
:root { --mova-container-max: 1000px; }
"""


@st.cache_data(show_spinner=False)
def _read_mova_css() -> str:
    """Return the concatenated Mova CSS (tokens → overrides → components).
    Cached so the file system is hit only once per session.

    Sanitises the CSS so any literal `<style>` / `</style>` / `<\\/style>`
    sequences inside comments can't break out of our <style> block (this is
    a real risk — streamlit-overrides.css ships with a demo snippet in its
    own header comment that contains exactly these tokens).
    """
    parts = []
    for name in ("tokens.css", "streamlit-overrides.css", "components.css"):
        path = MOVA_DIR / name
        if path.exists():
            parts.append(f"/* ===== {name} ===== */\n{path.read_text(encoding='utf-8')}")
    parts.append(f"/* ===== local overrides ===== */{_MOVA_LOCAL_OVERRIDES}")
    css = "\n\n".join(parts)
    # Strip patterns that could prematurely close our <style> block when
    # Streamlit's markdown renderer pipes the string through markdown-it.
    css = (css.replace("</style>", "/* */")
              .replace("<\\/style>", "/* */")
              .replace("<style>", "/* */"))
    return css


def _inject_mova_css() -> None:
    """Inject the Mova design system: Google Fonts + 3 CSS files + local tweaks.

    Loaded on every page render. Sits on top of the sub-apps' existing CSS so
    Mova rules win via CSS cascade (and `!important` where present).

    Uses `@import` instead of <link> tags because Streamlit's markdown
    parser treats <link> as inline text in some versions.
    """
    if not MOVA_DIR.exists():
        return
    css = _read_mova_css()
    st.markdown(
        f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');
{css}
</style>""",
        unsafe_allow_html=True,
    )


LANGUAGES = [
    "English", "Ukrainian", "Spanish", "Korean",
    "French", "German", "Japanese", "Chinese",
    "Portuguese", "Italian", "Polish", "Russian",
    "Catalan", "Dutch",
]

DB_GRAMMAR  = ROOT / "data" / "imlls_database.xlsx"
DB_VOCAB    = ROOT / "data" / "vocabulary_translated.xlsx"
DB_READING  = ROOT / "data" / "reading_lessons.xlsx"
APP_IMG_DIR = ROOT / "static" / "app_images"


def _img_b64(path) -> str:
    """Return base64 data-URL for an image, or empty string if missing."""
    import base64
    p = Path(path)
    if not p.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


MODULES = {
    "grammar": {
        "label":       "Grammar",
        "icon":        "🗣️",
        "img":         str(APP_IMG_DIR / "vocab_school.jpg"),
        "tagline":     "Practice phrases - 8 steps with GEC correction",
        "color_from":  "var(--mova-card)",
        "color_to":    "var(--mova-card)",
    },
    "vocab": {
        "label":       "Vocabulary",
        "icon":        "📖",
        "img":         str(APP_IMG_DIR / "vocab_basic.jpg"),
        "tagline":     "Learn words by topic - Family, Food, Travel...",
        "color_from":  "var(--mova-card)",
        "color_to":    "var(--mova-card)",
    },
    "phrasebook": {
        "label":       "Phrasebook",
        "icon":        "💬",
        "img":         str(APP_IMG_DIR / "vocab_greetings.jpg"),
        "tagline":     "Useful phrases by topic - Hobbies, Restaurant, Travel...",
        "color_from":  "var(--mova-card)",
        "color_to":    "var(--mova-card)",
    },
    "reading": {
        "label":       "Reading",
        "icon":        "🔤",
        "img":         str(APP_IMG_DIR / "reading_banner.jpg"),
        "tagline":     "Learn to read with IPA audio",
        "color_from":  "var(--mova-card)",
        "color_to":    "var(--mova-card)",
    },
    "custom": {
        "label":       "My Phrases",
        "icon":        "📝",
        "img":         str(APP_IMG_DIR / "my_phrases_banner.jpg"),
        "tagline":     "Create your own lessons - same 8-step practice flow",
        "color_from":  "var(--mova-card)",
        "color_to":    "var(--mova-card)",
    },
    "path": {
        "label":       "My Path",
        "icon":        "🗺️",
        "img":         str(ROOT / "static" / "lesson_images" / "lesson_088.jpg"),
        "tagline":     "Guided curriculum — reading, grammar & vocabulary in order",
        "color_from":  "var(--mova-card)",
        "color_to":    "var(--mova-card)",
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# Progress helpers — used to show "Lesson N / M · X%" on every module card
# ═══════════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def _grammar_lesson_ids(native: str, target: str) -> list[int]:
    """
    Sorted lesson_ids available for the chosen language pair.

    Must go through grammar.py::_load_grammar (not a bare load_phrases()
    call) so this list includes the engine.target_grammar_paths synthetic
    lessons (lesson_id 1000+, spliced on per target_lang since 2026-08-23) --
    a user whose lesson_pointer references one of those (real, e.g. the
    recommender routed them into a target-language grammar topic) would
    otherwise have `saved_lesson not in lesson_ids` here, and
    _module_progress falls back to its old raw-id arithmetic -- exactly the
    ">100%" bug this position-based rewrite exists to fix, just for a
    different id range than the one it was first found on (found in review,
    2026-08-24, before this ever shipped to a real user).
    """
    try:
        from grammar import _load_grammar
        df = _load_grammar(DB_GRAMMAR, native, target)
        return get_available_lessons(df)
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def _vocab_lesson_ids(native: str, target: str) -> list[int]:
    """CEFR-J lesson_ids -- same list for every target now (CLAUDE.md
    2026-08-22: see grammar.py::_load_vocabulary). "Phrasebook"
    (_phrasebook_lesson_ids) still covers the old Word Bank workbook.

    Sorted, not just unique() -- _module_progress() below needs a real
    position (.index()) for a saved lesson_id, not just a count.
    """
    try:
        from engine.cefr_j_vocab_loader import _build_index, CSV_PATH
        return sorted(int(x) for x in _build_index(str(CSV_PATH))["lesson_id"].unique())
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def _phrasebook_lesson_ids(native: str, target: str) -> list[int]:
    """Vocabulary sheets minus the Word Bank ones -- see grammar.py::_load_phrasebook."""
    try:
        from engine.vocab_loader import get_vocab_nav_data, WORD_BANK_SHEETS
        nav_data = get_vocab_nav_data(str(DB_VOCAB))
        return sorted(
            row["gid"] for sheet, rows in nav_data.items()
            if sheet not in WORD_BANK_SHEETS for row in rows
        )
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def _count_reading_lessons(lang: str = "en") -> int:
    """Total reading lessons available for the given language sheet."""
    try:
        import pandas as pd
        df = pd.read_excel(str(DB_READING), engine="openpyxl", sheet_name=lang)
        return int(df.iloc[:, 0].nunique())
    except Exception:
        return 0


def _module_progress(user_id: str, target: str, module: str, total: int,
                      lesson_ids: list[int] | None = None) -> dict:
    """
    Look up the saved resume pointer for (user, target, module) and convert it
    into: {"current": N, "total": M, "pct": float, "done": bool}

    lesson_ids: the real sorted list of lesson_ids for this module/language
    pair, when the caller has one (Grammar/Vocabulary/Phrasebook — see
    _grammar_lesson_ids / _vocab_lesson_ids / _phrasebook_lesson_ids).
    Position = lesson_ids.index(saved_lesson), the SAME "index in the
    sorted list, not the raw id" fix already applied to the in-lesson
    sidebar (grammar.py, 2026-08-23/24) -- without it this function did
    `min(saved_lesson, total)`, silently treating the raw lesson_id itself
    as if it were a position. That's wrong for any lesson_id that isn't a
    contiguous 1..N sequence: CEFR-J Vocabulary's global index starts at
    100000+, and Grammar's engine.target_grammar_paths lessons start at
    1000+ -- both instantly clamp to `total`, producing a false "100%,
    N/N" on the launcher card the moment such a lesson is opened (found
    live, 2026-08-24: Vocabulary showed "Тема 981 / 981 · 100%" for a
    student five lessons in). Custom lesson_ids look sequential but are NOT
    (engine.custom_store hands out ids from one global Postgres sequence
    shared across every user) -- found live, 2026-08-28: a user's first
    custom lesson could get e.g. id 57 and instantly show "1/1 · 100%", so
    it now also passes a real lesson_ids list. Reading is the only module
    still using the raw-id fallback below (lesson_ids=None) -- its ids
    really are a contiguous per-language 1..N sequence from the fixed
    reading_lessons.xlsx catalog.
    """
    info = {"current": 1, "total": max(total, 0), "pct": 0.0, "done": False}
    if not user_id or total <= 0:
        return info
    try:
        from engine import recommender as _recommender
        ptr = _recommender.get_pointer(user_id, target, module)
    except Exception:
        ptr = None
    if not ptr:
        return info

    saved_step = int(ptr.get("step") or 1)
    try:
        saved_lesson = _recommender.parse_unit_id(ptr["unit_id"])["lesson_id"]
    except Exception:
        saved_lesson = 0

    # 1-based position of the saved lesson among all of this module's
    # lessons. With a real lesson_ids list, that's index+1 (0-based index
    # -> 1-based count). Without one (reading/custom), fall back to using
    # saved_lesson itself, exactly as before this function took lesson_ids
    # -- correct there because those two modules' ids already ARE a
    # contiguous 1..N sequence, so no behavior change for them.
    if lesson_ids and saved_lesson in lesson_ids:
        position = lesson_ids.index(saved_lesson) + 1
    else:
        position = saved_lesson

    if saved_step >= 99:
        completed = min(position, total)
        info.update({
            "current": min(completed + 1, total),
            "pct":     round(completed / total * 100, 1),
            "done":    completed >= total,
        })
    else:
        completed = min(max(position - 1, 0), total)
        info.update({
            "current": min(position, total),
            "pct":     round(completed / total * 100, 1),
        })
    return info


def _module_progress_card(module_key: str, native: str, target: str,
                          user_id: str) -> dict:
    """Returns the progress info to render on a module card."""
    lesson_ids = None
    if module_key == "reading":
        import streamlit as _st
        r_lang = _st.session_state.get("r_lang", "en")
        total  = _count_reading_lessons(lang=r_lang)
        module = "reading"
        word   = i18n.get(native, "word_lesson")
    elif module_key == "grammar":
        lesson_ids = _grammar_lesson_ids(native, target)
        total  = len(lesson_ids)
        module = "grammar"
        word   = i18n.get(native, "word_lesson")
    elif module_key == "vocab":
        lesson_ids = _vocab_lesson_ids(native, target)
        total  = len(lesson_ids)
        module = "vocab"
        word   = i18n.get(native, "topic_label")
    elif module_key == "phrasebook":
        lesson_ids = _phrasebook_lesson_ids(native, target)
        total  = len(lesson_ids)
        module = "phrasebook"
        word   = i18n.get(native, "word_phrase")
    elif module_key == "path":
        try:
            from engine import recommender as _recommender
            stats = _recommender.get_stats(user_id, target)
            return {
                "current": stats["done_total"] + 1, "total": stats["total_units"],
                "pct": stats["pct"], "done": False,
                "lesson_word": i18n.get(native, "word_unit"), "module_key": "path",
            }
        except Exception:
            return {"current": 1, "total": 0, "pct": 0.0, "done": False,
                    "lesson_word": i18n.get(native, "word_unit"), "module_key": "path"}
    else:
        try:
            # Custom lesson_ids come from a global Postgres sequence
            # (nextval('custom_lesson_id_seq') in engine.custom_store),
            # shared across ALL users -- not a per-user 1..N sequence, so
            # (unlike Reading) this module needs the real lesson_ids list
            # too, same as grammar/vocab/phrasebook above. Without it, the
            # very first lesson a user creates could get e.g. id 57 and
            # instantly render as "1/1 · 100% done".
            lesson_ids = sorted(
                list_user_lessons(user_id, native_lang=native, target_lang=target)
                ["lesson_id"].tolist()
            )
            total = len(lesson_ids)
        except Exception:
            total = 0
        module = "custom"
        word   = i18n.get(native, "word_lesson")
    pr = _module_progress(user_id, target, module, total, lesson_ids=lesson_ids)
    pr["lesson_word"] = word
    pr["module_key"]  = module_key
    return pr


def render_launcher():
    st.markdown("""
    <style>
    /* removed: was fighting Mova surface; theme is now driven by tokens.css */
    #MainMenu,footer{visibility:hidden;}
    /* Keep Streamlit's sidebar collapse/expand control reachable on every device,
       including iOS Safari, where the control would otherwise be invisible. */
    header{background:transparent !important;}
    header [data-testid="stDecoration"]{display:none;}
    /* Floating sidebar toggle (visible whenever the sidebar is collapsed) */
    [data-testid="collapsedControl"]{
        visibility:visible !important;
        opacity:1 !important;
        display:flex !important;
        z-index:9999 !important;
        position:fixed !important;
        top:0.6rem !important;
        left:0.6rem !important;
        background:var(--mova-card) !important;
        border:1px solid var(--mova-indigo) !important;
        border-radius:8px !important;
        box-shadow:0 2px 8px rgba(0,0,0,.4) !important;
    }
    [data-testid="collapsedControl"] button,
    [data-testid="collapsedControl"] svg{
        color:var(--mova-indigo) !important;
        fill:var(--mova-indigo) !important;
        min-width:36px !important;
        min-height:36px !important;
    }
    .mode-card{
        background:var(--mova-card);
        border:1px solid var(--mova-line);
        border-radius:18px;
        padding:24px 12px 18px;
        text-align:center;
        transition:all .2s;
        height:100%;
    }
    .mode-card:hover{
        border-color:var(--mova-indigo);
        background:var(--mova-surface-3);
        transform:translateY(-3px);
        box-shadow:var(--mova-shadow-3);
    }
    .mode-icon{font-size:2.4rem;margin-bottom:6px;}
    .mode-title{
        color:var(--mova-ink);
        /* 6 equal columns leave ~78px of text width even on a wide desktop
           viewport (vw-based sizing here doesn't track actual card width,
           which stays roughly constant as columns grow) -- at the old
           .85-1.1rem range, 10-letter labels like "Vocabulary" /
           "Phrasebook" didn't fit and broke mid-word. Sized down so the
           longest real label fits on one line without needing
           word-break to fall back to a character split. */
        font-size:clamp(.68rem, 1.6vw, .82rem);
        font-weight:600;
        line-height:1.25;
        margin:6px 0;
        white-space:nowrap;
        overflow:visible;
    }
    .mode-tag{color:var(--mova-ink-2);font-size:.88rem;margin-bottom:14px;}
    .pb-wrap{background:var(--mova-surface-3);border-radius:8px;height:8px;margin:8px 0 6px;
             overflow:hidden;border:1px solid var(--mova-line-2);}
    .pb-fill{height:8px;border-radius:8px;
             background:linear-gradient(90deg, var(--mova-indigo), #6E66FF);transition:width .4s;}
    .pb-info{display:flex;justify-content:space-between;
             font-family:'JetBrains Mono',monospace;font-size:.72rem;
             color:#9090c0;margin-bottom:2px;}
    .pb-done{color:var(--mova-mint) !important;}
    .pb-fill-done{background:linear-gradient(90deg,var(--mova-mint),var(--mova-mint)) !important;}
    .pb-empty{color:var(--mova-ink-3) !important;}
    .menu-wrap{max-width:920px;margin:0 auto;}
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center;padding:40px 0 20px">
      <div style="display:inline-block;width:200px;height:200px">
        <svg viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg" font-family="'Segoe UI', Arial, sans-serif">
          <rect width="400" height="400" fill="#FFFDF7" rx="40"/>
          <ellipse cx="200" cy="175" rx="90" ry="85" fill="#FFE08A" opacity="0.35"/>
          <rect x="105" y="90" width="190" height="130" rx="30" fill="#FF8C42"/>
          <polygon points="145,218 125,255 175,218" fill="#FF8C42"/>
          <rect x="115" y="100" width="170" height="110" rx="22" fill="#FFA563" opacity="0.5"/>
          <path d="M130 140 Q145 125 160 140 Q175 155 190 140 Q205 125 220 140 Q235 155 250 140 Q260 130 270 140" stroke="white" stroke-width="5" fill="none" stroke-linecap="round"/>
          <path d="M130 165 Q145 150 160 165 Q175 180 190 165 Q205 150 220 165 Q235 180 250 165 Q260 155 270 165" stroke="white" stroke-width="5" fill="none" stroke-linecap="round" opacity="0.6"/>
          <circle cx="310" cy="100" r="5" fill="#FFD166"/>
          <circle cx="325" cy="85" r="3" fill="#FF8C42"/>
          <circle cx="295" cy="82" r="4" fill="#FFD166" opacity="0.7"/>
          <circle cx="90" cy="105" r="4" fill="#FFD166"/>
          <circle cx="75" cy="90" r="3" fill="#FF8C42" opacity="0.8"/>
          <circle cx="105" cy="80" r="5" fill="#FFD166" opacity="0.6"/>
          <text x="200" y="300" text-anchor="middle" font-size="38" font-weight="800" letter-spacing="-1">
            <tspan fill="#FF8C42">Verba</tspan><tspan fill="#2D2D2D">Shake</tspan>
          </text>
          <text x="200" y="328" text-anchor="middle" font-size="13" fill="#AAA" letter-spacing="2.5" font-weight="500">LANGUAGE LEARNING</text>
          <circle cx="168" cy="355" r="4" fill="#FFD166"/>
          <circle cx="185" cy="355" r="4" fill="#FF8C42"/>
          <circle cx="200" cy="355" r="6" fill="#FF8C42"/>
          <circle cx="215" cy="355" r="4" fill="#FF8C42"/>
          <circle cx="232" cy="355" r="4" fill="#FFD166"/>
        </svg>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Account (Google, via st.login) + language preferences ───────────────
    # Defaults persist across reruns via session_state.
    user_id        = auth_gate.current_user_id()
    default_native = st.session_state.get("launcher_native", "Ukrainian")
    default_target = st.session_state.get("launcher_target", "English")

    if st.session_state.get("_prefs_is_new_user"):
        st.info(
            "👋 Welcome! Pick your native and target language below — "
            "we'll remember this for next time."
        )

    with st.container():
        c1, c2, c3 = st.columns([2, 1.3, 1.3])
        with c1:
            st.markdown(
                f'<div style="padding-top:1.9rem">👤 {auth_gate.current_user_name()}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            # Labelled in the student's last-known native language, same as
            # the rest of the launcher below (was hardcoded English even
            # when the sidebar gamification widget right next to it was
            # already fully localized -- design review, 2026-08-23).
            native = st.selectbox(i18n.get(default_native, "native_language"), LANGUAGES,
                                  index=LANGUAGES.index(default_native)
                                  if default_native in LANGUAGES else 0,
                                  key="launcher_native_input")
        with c3:
            target_options = [l for l in LANGUAGES if l != native]
            target_default_idx = (target_options.index(default_target)
                                  if default_target in target_options else 0)
            target = st.selectbox(i18n.get(native, "target_language"), target_options,
                                  index=target_default_idx,
                                  key="launcher_target_input")

    # Persist for next render and for sub-apps to read
    st.session_state["launcher_user"]   = user_id
    st.session_state["launcher_native"] = native
    st.session_state["launcher_target"] = target

    # Save to the DB only when the choice actually changed (not on every
    # rerun) — CLAUDE.md 2026-08-22. Also clears the new-user welcome banner
    # once a real choice has been saved.
    if user_id and (native, target) != (
        st.session_state.get("_prefs_saved_native"),
        st.session_state.get("_prefs_saved_target"),
    ):
        user_prefs.save_prefs(user_id, native, target)
        st.session_state["_prefs_saved_native"] = native
        st.session_state["_prefs_saved_target"] = target
        st.session_state["_prefs_is_new_user"]  = False

    # ── Placement quiz — promoted right under language choice (was a hidden
    # expander below 6 scrolling module cards on mobile; design review,
    # 2026-08-27) so a new learner sees it before, not after, committing to
    # a starting point. ─────────────────────────────────────────────────────
    st.markdown("<div style='margin:18px 0 0'></div>", unsafe_allow_html=True)
    _render_placement_quiz(native, target, user_id)

    # ── Sidebar: streak/XP + account + subscription ──────────────────────────
    with st.sidebar:
        if user_id:
            sidebar_widget(user_id)
        st.markdown("---")
        if billing.is_paid(user_id):
            st.markdown("⭐ **Premium**")
        else:
            st.markdown("Free plan")
            checkout_url = st.session_state.get("_checkout_url")
            if checkout_url:
                st.link_button("Continue to checkout →", checkout_url, use_container_width=True)
            elif st.button("⭐ Upgrade", use_container_width=True, type="primary",
                           key="launcher_upgrade"):
                try:
                    st.session_state["_checkout_url"] = billing.create_checkout_session(
                        user_id, user_id, return_url=_app_url()
                    )
                    st.rerun()
                except Exception as e:
                    # Never echo the raw exception into the UI: a malformed
                    # STRIPE_SECRET_KEY (e.g. trailing whitespace from a
                    # copy-paste) can produce a Stripe AuthenticationError
                    # whose message includes the offending key value --
                    # printing it server-side keeps it out of anyone's
                    # browser, including other users viewing the same
                    # misconfigured deployment.
                    print(f"[app] checkout session error: {e}")
                    st.error("Checkout unavailable right now — please try again in a moment.")
        if st.button("Sign out", use_container_width=True, key="launcher_signout"):
            st.logout()

    st.markdown("<div style='margin:18px 0 10px'></div>", unsafe_allow_html=True)

    # ── Single "Continue to My Path" hero — replaces the 6-card grid that
    # forced a horizontal/vertical scroll through near-identical cards on
    # mobile (design review, 2026-08-27). My Path is now the one thing this
    # screen leads to; the individual modules (Grammar/Vocab/Phrasebook/
    # Reading/My Phrases) are reachable from a swipeable strip ON the My
    # Path screen itself (path_app.py::_render_module_swipe_strip), not from
    # here — picking one is a "pure single-module view" action you take
    # once you're already looking at your recommended path, not instead of it.
    info = MODULES["path"]
    pr   = _module_progress_card("path", native, target, user_id)
    tot, cur, pct, word = pr["total"], pr["current"], pr["pct"], pr["lesson_word"]

    if tot <= 0:
        _no_lessons = i18n.get(native, "no_lessons_yet")
        progress_html = (
            f'<div class="pb-info" style="justify-content:center">'
            f'<span class="pb-empty">{_no_lessons}</span></div>'
            '<div class="pb-wrap"><div class="pb-fill" style="width:0%"></div></div>'
        )
    elif pr["done"]:
        _word_done = f"{word.lower()}s" if native == "English" else word
        progress_html = (
            f'<div class="pb-info">'
            f'<span class="pb-done">All {tot} {_word_done} done!</span>'
            f'<span class="pb-done">100%</span></div>'
            f'<div class="pb-wrap">'
            f'<div class="pb-fill pb-fill-done" style="width:100%"></div></div>'
        )
    else:
        progress_html = (
            f'<div class="pb-info">'
            f'<span>{word} {cur} / {tot}</span>'
            f'<span>{pct:.0f}%</span></div>'
            f'<div class="pb-wrap">'
            f'<div class="pb-fill" style="width:{pct}%"></div></div>'
        )

    _b64 = _img_b64(info.get("img", ""))
    _img_html = (
        f'<img src="{_b64}" style="width:100%;height:150px;'
        f'object-fit:cover;border-radius:10px;margin-bottom:10px"/>'
        if _b64 else
        f'<div class="mode-icon">{info["icon"]}</div>'
    )
    with st.container():
        st.markdown(f"""
        <div class="mode-card" style="max-width:420px;margin:0 auto">
          {_img_html}
          <div class="mode-title" style="font-size:1.1rem;white-space:normal">{info['label']}</div>
          {progress_html}
        </div>
        """, unsafe_allow_html=True)
        _cta_col1, _cta_col2, _cta_col3 = st.columns([1, 2, 1])
        with _cta_col2:
            if st.button(f"▶ {i18n.get(native, 'start_prefix')} My Path",
                         use_container_width=True, type="primary", key="pick_path"):
                _switch_to("path")


def _render_placement_quiz(native: str, target: str, user_id: str) -> None:
    """
    Optional short placement quiz (CLAUDE.md item 3, decided 2026-08-21: a
    short quiz rather than a full adaptive test). Free for every user — it's
    graded locally (engine.scorer), zero Gemini calls — and seeds initial
    mastery via engine.recommender.seed_mastery_from_level() so a learner who
    already knows some material isn't started from 0.0 on every topic.
    """
    with st.expander(i18n.get(native, "pq_expander_title")):
        quiz_module = st.selectbox(
            i18n.get(native, "pq_module_label"), ["grammar", "vocab"],
            format_func=lambda m: MODULES[m]["label"], key="pq_module",
        )
        if st.button(i18n.get(native, "pq_generate_btn"), key="pq_generate"):
            cfg = grammar_app._module_config(quiz_module)
            df_all = cfg["load"](str(cfg["db_path"]), native, target)
            st.session_state["pq_items"] = placement_quiz.build_quiz(
                quiz_module, target, df_all, cfg["get_lesson"]
            )
            st.session_state["pq_module_used"] = quiz_module
            st.session_state.pop("pq_result", None)

        items = st.session_state.get("pq_items")
        if items == [] and st.session_state.get("pq_module_used") == "vocab":
            st.caption(i18n.get(native, "pq_vocab_unavailable"))
        if items:
            st.caption(i18n.get(native, "pq_instructions"))
            answers = {}
            for i, item in enumerate(items):
                answers[i] = st.text_input(
                    f"{item['level']}  ·  {item['native']}", key=f"pq_ans_{i}"
                )
            if st.button(i18n.get(native, "pq_submit_btn"), type="primary", key="pq_submit"):
                st.session_state["pq_result"] = placement_quiz.score_quiz(
                    user_id, target, st.session_state["pq_module_used"], items, answers,
                )

        result = st.session_state.get("pq_result")
        if result:
            if result["estimated_level"]:
                st.success(
                    i18n.get(native, "pq_result_estimated").format(level=result["estimated_level"])
                )
            else:
                st.info(i18n.get(native, "pq_result_beginner"))
            for r in result["results"]:
                icon = "✅" if r["passed"] else "❌"
                said = (i18n.get(native, "pq_you_wrote").format(answer=r["user_answer"])
                        if r["user_answer"] else "")
                st.caption(f"{icon} {r['level']}: {r['native']} → {r['target']}{said}")


def _switch_to(module_key: str):
    """Reset session state and remember the chosen module + user prefs."""
    # Save launcher prefs so sub-app can pre-fill them
    user   = st.session_state.get("launcher_user", "student1")
    native = st.session_state.get("launcher_native", "Ukrainian")
    target = st.session_state.get("launcher_target", "English")

    # Wipe everything so previous-module state can't bleed through
    for k in list(st.session_state):
        del st.session_state[k]
    st.session_state["active_module"]   = module_key
    st.session_state["launcher_user"]   = user
    st.session_state["launcher_native"] = native
    st.session_state["launcher_target"] = target
    st.query_params["module"] = module_key
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Main router
# ═══════════════════════════════════════════════════════════════════════════
def _inject_pwa_head() -> None:
    """
    Phase E (PWA packaging, 2026-08-24): link the manifest + register the
    service worker so the browser offers "Install app" / "Add to Home
    Screen". Same reach-into-the-real-page trick as the dark-mode toggle
    below (st.markdown can't inject a <script>, browsers don't execute
    script tags from innerHTML) -- components.html's iframe gives us
    window.parent, the actual top-level document/navigator.

    Idempotent AND once-per-session: the <head> tags/SW registration only
    need to happen once for the whole browser tab, not on every rerun --
    main() calls this on every single Streamlit interaction (every button
    click), and each call spins up a real (if invisible) iframe, so without
    a session_state guard this would inject-and-tear-down that iframe and
    re-run the script on every click across the entire app forever. The
    data-attribute marker on <head> alone (checked inside the script) would
    still make each individual injection a no-op, but wouldn't stop the
    components.html iframe itself from being recreated every rerun -- the
    session_state check below skips calling components.html at all once
    this tab has already done it.

    Static files (static/pwa/manifest.json, sw.js, icons) are served at
    app/static/pwa/... only because .streamlit/config.toml now sets
    server.enableStaticServing=true (this is the first feature in the repo
    that needs the browser to fetch a file from ./static/ directly, rather
    than server-side via st.image/CSS-file-read).
    """
    if st.session_state.get("_pwa_head_injected"):
        return
    st.session_state["_pwa_head_injected"] = True
    import streamlit.components.v1 as _components
    _components.html(
        "<script>"
        "const d = window.parent.document;"
        "if (!d.head.querySelector('[data-verbashake-pwa]')) {"
        "  const manifest = d.createElement('link');"
        "  manifest.rel = 'manifest';"
        "  manifest.href = 'app/static/pwa/manifest.json';"
        "  manifest.setAttribute('data-verbashake-pwa', '1');"
        "  d.head.appendChild(manifest);"
        "  const theme = d.createElement('meta');"
        "  theme.name = 'theme-color';"
        "  theme.content = '#FF7B6B';"
        "  d.head.appendChild(theme);"
        "  const touchIcon = d.createElement('link');"
        "  touchIcon.rel = 'apple-touch-icon';"
        "  touchIcon.href = 'app/static/pwa/apple-touch-icon.png';"
        "  d.head.appendChild(touchIcon);"
        "  if ('serviceWorker' in window.parent.navigator) {"
        "    window.parent.navigator.serviceWorker"
        "      .register('app/static/pwa/sw.js', {scope: 'app/static/pwa/'})"
        "      .catch(() => {});"  # best-effort -- installability is a nice-to-have, never block the app
        "  }"
        "}"
        "</script>",
        height=0,
    )


def main():
    # Mova design system — Phase 1. Loaded on every rerun so it overrides
    # the sub-apps' legacy CSS via cascade.
    _inject_mova_css()
    _inject_pwa_head()

    # 🌙 Dark mode — tokens.css already ships a full [data-theme="dark"]
    # palette (design review, 2026-08-23: it just had nothing that ever set
    # the attribute activating it). Session-only, not persisted per-user --
    # a nice-to-have toggle, not worth a DB round-trip. st.markdown can't run
    # a <script> tag (browsers don't execute script from innerHTML), so the
    # attribute is set via components.html's iframe -> window.parent, the
    # same pattern already used elsewhere in this app (grammar.py's audio
    # player) for reaching into the real page from a component.
    with st.sidebar:
        _dark = st.toggle("🌙 Dark mode", key="_dark_mode")
    import streamlit.components.v1 as _components
    # Setting the data-theme attribute alone wasn't enough: .stApp's
    # background never actually switched even though --mova-surface's
    # computed value did change to the dark hex (verified via devtools) --
    # something in Streamlit's own generated CSS keeps winning the cascade
    # for that one property. An inline style set with 'important' priority
    # via the DOM API outranks every selector-based rule regardless (inline
    # specificity beats class/attribute selectors outright), so set it
    # directly instead of trusting inheritance through the class rule.
    _components.html(
        "<script>"
        "const d = window.parent.document;"
        f"d.documentElement.setAttribute('data-theme', '{'dark' if _dark else 'light'}');"
        "const app = d.querySelector('.stApp');"
        "if (app) app.style.setProperty('background', 'var(--mova-surface)', 'important');"
        "</script>",
        height=0,
    )

    # ── Login gate — must pass before anything else is shown ────────────────
    if not auth_gate.check_and_gate():
        return

    # Swipe-strip navigation from My Path (path_app.py::_render_module_swipe_strip)
    # -- a plain <a href="?swipe_module=grammar"> since Streamlit buttons can't
    # live inside a custom scroll-snap strip. Checked unconditionally (unlike
    # the general qp_module sync below, which only fills in an EMPTY
    # active_module) because this needs to override an already-set "path"
    # session — same "explicit query-param bridge, consumed once" pattern
    # already used for reading_app.py's vnav_lesson wave-nav clicks.
    _swipe_target = st.query_params.get("swipe_module")
    if _swipe_target:
        st.query_params.clear()
        _switch_to(_swipe_target)
        return

    # Finalise a Stripe Checkout redirect, if we just came back from one.
    billing.handle_checkout_return()
    if st.session_state.pop("_billing_just_upgraded", False):
        st.toast("⭐ Welcome to Premium!")

    # Real account from here on — every downstream module reads this.
    user_id = auth_gate.current_user_id()
    st.session_state["launcher_user"] = user_id

    # Load the student's saved native/target language once per session
    # (CLAUDE.md 2026-08-22) — a returning login shouldn't reset the choice
    # back to the hardcoded Ukrainian/English default. Guarded so it only
    # seeds session_state on the first render of this session, never
    # overwriting a change the student just made in the selectors below.
    if user_id and not st.session_state.get("_prefs_loaded"):
        _saved_prefs = user_prefs.get_prefs(user_id)
        st.session_state["_prefs_is_new_user"] = not _saved_prefs
        if _saved_prefs:
            if _saved_prefs.get("native_lang"):
                st.session_state["launcher_native"] = _saved_prefs["native_lang"]
            if _saved_prefs.get("target_lang"):
                st.session_state["launcher_target"] = _saved_prefs["target_lang"]
        st.session_state["_prefs_loaded"] = True

    # Sub-apps may set this flag in their sidebar "Switch mode" button.
    if st.session_state.pop("_show_launcher", False):
        # Preserve launcher preferences across the reset
        user   = st.session_state.get("launcher_user", "student1")
        native = st.session_state.get("launcher_native", "Ukrainian")
        target = st.session_state.get("launcher_target", "English")
        for k in list(st.session_state):
            del st.session_state[k]
        st.session_state["launcher_user"]   = user
        st.session_state["launcher_native"] = native
        st.session_state["launcher_target"] = target
        st.query_params.clear()
        render_launcher()
        return

    # Restore module from URL query param (enables browser back/forward)
    qp_module = st.query_params.get("module")
    if qp_module and not st.session_state.get("active_module"):
        st.session_state["active_module"] = qp_module
    elif st.session_state.get("active_module") and not qp_module:
        # Session has module but URL doesn't — keep session as truth, update URL
        st.query_params["module"] = st.session_state["active_module"]

    active = st.session_state.get("active_module")

    if active is None:
        render_launcher()
        return

    if active == "grammar":
        grammar_app.main(module="grammar")
    elif active == "vocab":
        grammar_app.main(module="vocab")
    elif active == "phrasebook":
        grammar_app.main(module="phrasebook")
    elif active == "reading":
        # Sync launcher target language -> reading language code (only if not yet set)
        _TARGET_TO_RLANG = {
            "English":   "en",
            "Ukrainian": "uk",
            "Spanish":   "es",
            "Korean":    "ko",
        }
        _target = st.session_state.get("launcher_target", "English")
        if "r_lang" not in st.session_state:
            st.session_state["r_lang"] = _TARGET_TO_RLANG.get(_target, "en")
        reading_app.main()
    elif active == "custom":
        custom_app.main()
    elif active == "path":
        path_app.main()
    elif active == "search":
        search_app.main()
    else:
        # Unknown module - reset
        for k in list(st.session_state):
            del st.session_state[k]
        st.query_params.clear()
        render_launcher()


if __name__ == "__main__":
    main()
