"""
IMLLS — Intelligent Multilingual Language Learning System
Lesson-based flow: 7 steps, full lesson visible at once.
JS MediaRecorder for in-browser audio capture.

Run: streamlit run app.py
"""
from __future__ import annotations

import sys, base64, random, time, json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

LESSON_IMG_DIR = ROOT / "static" / "lesson_images"
APP_IMG_DIR    = ROOT / "static" / "app_images"

# Mapping from vocab sheet names (as stored in df["topic"]) to image slugs.
_TOPIC_SLUG: dict[str, str] = {
    # Keys must match EXACT sheet names in vocabulary.xlsx (incl. truncation)
    "Greetings, Basics & Courtesy":        "greetings",
    "Questions, Directions & Emergen":     "questions",   # truncated to 30 chars
    "Daily Life, Routine & Feelings":      "daily_life",
    "Basic":                               "basic",
    "Verbs":                               "verbs",
    "Food":                                "food",
    "City":                                "city",
    "Restaurant, Food & Shopping":         "restaurant_food_shopping",
    "Travel, Lodging & Weather":           "travel_lodging_weather",
    "Emotions":                            "emotions",
    "House and Home":                      "house",
    "Weather":                             "weather",
    "Shopping":                            "shopping",
    "Daily Routine":                       "daily_routine",
    "At the Doctor":                       "doctor",
    "Food and Drinks":                     "food_drinks",
    "Work":                                "work",
    "School":                              "school",
    "Travel":                              "travel",
    "Hobbies":                             "hobbies",
    "Clothes":                             "clothes",
    "Transport":                           "transport",
    "Restaurant":                          "restaurant",
    "Friends and Relationships":           "friends",
    "Family":                              "family",
    "Technology":                          "technology",
    "Holidays":                            "holidays",
    "Sports":                              "sports",
    "City and Directions":                 "city_directions",
}


def _show_vocab_image(topic: str):
    """Show centered vocab topic illustration if the file exists."""
    slug = _TOPIC_SLUG.get(topic)
    if not slug:
        return
    p = APP_IMG_DIR / f"vocab_{slug}.jpg"
    if not p.exists():
        return
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.image(str(p), use_container_width=True)


def _show_lesson_image(lesson_id: int, max_width_px: int = 340):
    """Show centered lesson illustration if the file exists."""
    p = LESSON_IMG_DIR / f"lesson_{lesson_id:03d}.jpg"
    if not p.exists():
        return
    # Center by putting image in a middle column
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.image(str(p), use_container_width=True)

from engine.loader  import (load_phrases, get_lesson, get_available_lessons,
                            get_lesson_topics as get_grammar_topics,
                            TTS_LANG, WHISPER_LANG)
from engine.vocab_loader import (
    load_vocab, get_vocab_lesson, get_available_vocab_lessons, get_lesson_topics,
    WORD_BANK_SHEETS,
)
from engine import cefr_j_vocab_loader as _cefrj_vocab
from engine.session import LessonSession
from engine.scorer  import evaluate
from engine.tts     import get_audio_path
from engine.stt      import transcribe_bytes, whisper_available
from engine.gamification import on_step_complete, on_lesson_complete, sidebar_widget
from engine import gemini as _gemini
from engine import youtube_links
from engine import recommender as _recommender
from engine.picker import _render_flat_wave_nav
from engine import i18n
from engine.character_widget import show_character

_FULL_SEQ = [1, 2, 3, 4, 5, 6, 7, 8]


def _get_progress(user_id: str, target_lang: str, module: str) -> dict | None:
    """Resume pointer, same shape the old engine.logger.get_progress returned."""
    ptr = _recommender.get_pointer(user_id, target_lang, module)
    if not ptr:
        return None
    try:
        lesson_id = _recommender.parse_unit_id(ptr["unit_id"])["lesson_id"]
    except Exception:
        return None
    return {"last_completed_lesson": lesson_id, "last_step": int(ptr["step"])}

# Prefer the workbook with lesson titles (topic_en / topic_uk columns) if it
# exists; otherwise fall back to the original. Both have identical phrase data.
DB_PATH_TITLED = ROOT / "data" / "imlls_database_with_titles.xlsx"
DB_PATH_PLAIN  = ROOT / "data" / "imlls_database.xlsx"
DB_PATH        = DB_PATH_TITLED if DB_PATH_TITLED.exists() else DB_PATH_PLAIN
VOCAB_DB_PATH  = ROOT / "data" / "vocabulary_translated.xlsx"
LANGUAGES      = [
    "English", "Ukrainian", "Spanish", "Korean",
    "French", "German", "Japanese", "Chinese",
    "Portuguese", "Italian", "Polish", "Russian",
    "Catalan", "Dutch",
]

# st.set_page_config is set up by main_app.py when used as a launcher.
# When this file is run directly, set it here too.
try:
    st.set_page_config(page_title="IMLLS", page_icon="🗣️",
                       layout="wide", initial_sidebar_state="collapsed")
except Exception:
    pass  # Already set by main_app.py


# ═══════════════════════════════════════════════════════════════════════════
# Module dispatch — same 8-step flow for grammar and vocabulary
# ═══════════════════════════════════════════════════════════════════════════
def _load_phrasebook(db_path, native_lang, target_lang):
    """
    Vocabulary content minus the Word Bank sheets (vocab_loader.WORD_BANK_SHEETS)
    -- the "Phrasebook" module (CLAUDE.md, 2026-08-21): thematic collocations
    + example sentences, as opposed to Word Bank's raw alphabetically-bucketed
    word lists (being replaced by the CEFR-J-based Vocabulary module instead).
    Same lesson_id numbering as the "vocab" module (load_vocab's global index
    is built over the whole workbook either way) -- existing unit_ids for
    these sheets stay valid.
    """
    return load_vocab(db_path, native_lang, target_lang, exclude_sheets=WORD_BANK_SHEETS)


def _load_vocabulary(db_path, native_lang, target_lang, **kwargs):
    """
    "Vocabulary" module content (CLAUDE.md, 2026-08-21/22, extended
    2026-08-22): CEFR-J-based for every target language (9.8k words A1-C2,
    one English example sentence each, translated on demand per lesson --
    see engine.cefr_j_vocab_loader / engine.session._fill_missing_translations)
    -- replaces the old Word Bank sheets, which only ever covered
    en/uk/es/ko and had known data-quality issues (mistagged C2,
    alphabetical bucketing). `db_path` is unused (CEFR-J's own CSV path is
    fixed); kept as the first positional arg so this drops into
    cfg["load"] exactly like every other module's loader. `**kwargs`
    absorbs the `topic=` some callers still pass (leftover from the old
    per-sheet lazy loading) -- CEFR-J always loads its one small CSV
    whole, so it's simply ignored.
    """
    return _cefrj_vocab.load_cefrj_vocab(str(_cefrj_vocab.CSV_PATH), native_lang, target_lang)


def _module_config(module: str) -> dict:
    """Return loader dispatch + UI labels for the chosen practice module."""
    if module == "vocab":
        return {
            "db_path":     VOCAB_DB_PATH,
            "load":        _load_vocabulary,
            "get_lesson":  get_vocab_lesson,
            "get_lessons": get_available_vocab_lessons,
            "topics":      get_lesson_topics,
            "label":       "Vocabulary",
            "icon":        "📖",
            "lang_suffix": "vocab",
            "lesson_word": "Topic",
        }
    if module == "phrasebook":
        return {
            "db_path":     VOCAB_DB_PATH,
            "load":        _load_phrasebook,
            "get_lesson":  get_vocab_lesson,
            "get_lessons": get_available_vocab_lessons,
            "topics":      get_lesson_topics,
            "label":       "Phrasebook",
            "icon":        "💬",
            "lang_suffix": "phrasebook",
            "lesson_word": "Phrase",
        }
    if module == "custom":
        # User-created lessons. Data is loaded on demand by custom_app,
        # so the "load"/"get_lessons" callables are intentionally None —
        # they're never called for this module (custom_app pushes the
        # session into st.session_state before grammar.main() runs).
        return {
            "db_path":     None,
            "load":        None,
            "get_lesson":  None,
            "get_lessons": None,
            "topics":      None,
            "label":       "My Phrases",
            "icon":        "📝",
            "lang_suffix": "custom",
            "lesson_word": "Lesson",
        }
    return {
        "db_path":     DB_PATH,
        "load":        load_phrases,
        "get_lesson":  get_lesson,
        "get_lessons": get_available_lessons,
        # Grammar topics come from the loaded DataFrame (optional topic_en/topic_uk)
        "topics":      "from_df",
        "label":       "Grammar",
        "icon":        "🗣️",
        "lang_suffix": "grammar",
        "lesson_word": "Lesson",
    }


def _current_module() -> str:
    return st.session_state.get("practice_module", "grammar")

# ═══════════════════════════════════════════════════════════════════════════
# Audio input — st.audio_input (Streamlit 1.31+) with fallback
# ═══════════════════════════════════════════════════════════════════════════

def audio_input(uid: str, label: str = "🎙️ Record") -> bytes | None:
    """
    Uses st.audio_input (built-in mic recorder, no JS iframe needed).
    Falls back to file_uploader if st.audio_input is not available.
    Returns raw audio bytes or None.
    """
    if hasattr(st, "audio_input"):
        recorded = st.audio_input(label, key=f"mic_{uid}")
        if recorded:
            return recorded.read()
        return None
    else:
        # Fallback for older Streamlit versions
        st.caption("⚠️ Upgrade Streamlit to 1.31+ for built-in mic recording.")
        f = st.file_uploader("Upload audio", type=["webm","wav","mp3","ogg","m4a"],
                             key=f"up_{uid}", label_visibility="collapsed")
        return f.read() if f else None





def autoplaylist_html(audio_paths, pause_secs):
    """JS component: plays a list of MP3s sequentially with custom pauses."""
    srcs = []
    for p in audio_paths:
        if p and Path(p).exists():
            with open(p, "rb") as f:
                srcs.append("data:audio/mp3;base64," + base64.b64encode(f.read()).decode())
        else:
            srcs.append("")
    srcs_js   = str(srcs).replace("'", '"')
    pauses_js = str([round(s, 2) for s in pause_secs])
    n = len(srcs)
    return f"""
<div style="background:#FFFFFF;border:1px solid #E8E2D8;border-radius:12px;padding:14px 18px;margin:8px 0;">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
    <button id="pl-btn" onclick="plToggle()"
      style="background:#ECEBFB;color:#4F46E5;border:1px solid #4F46E5;border-radius:8px;
             padding:7px 18px;cursor:pointer;font-family:JetBrains Mono,monospace;font-size:.88rem;">
      ▶ Play All
    </button>
    <span id="pl-stat" style="color:#7A7390;font-size:.8rem;font-family:JetBrains Mono,monospace;">ready</span>
  </div>
  <div id="pl-bar" style="margin-top:10px;display:flex;gap:4px;flex-wrap:wrap;"></div>
</div>
<script>
(function(){{
  const srcs={srcs_js}, pauses={pauses_js}, n={n};
  let cur=-1, playing=false, aud=null, tmr=null;
  const bar=document.getElementById('pl-bar');
  for(let i=0;i<n;i++){{const d=document.createElement('div');d.id='dot-'+i;
    d.style.cssText='width:10px;height:10px;border-radius:50%;background:#ECEBFB;transition:.2s;';
    bar.appendChild(d);}}
  function dot(i,c){{const d=document.getElementById('dot-'+i);if(!d)return;
    d.style.background=c==='active'?'#4F46E5':c==='done'?'#1FB888':'#ECEBFB';}}
  function stop(){{if(aud){{aud.pause();aud=null;}}if(tmr){{clearTimeout(tmr);tmr=null;}}
    playing=false;cur=-1;document.getElementById('pl-btn').textContent='▶ Play All';
    document.getElementById('pl-btn').style.color='#4F46E5';
    document.getElementById('pl-stat').textContent='stopped';
    for(let i=0;i<n;i++)dot(i,'');}}
  function playIdx(i){{if(i>=n){{stop();document.getElementById('pl-stat').textContent='done ✓';return;}}
    cur=i;playing=true;for(let j=0;j<i;j++)dot(j,'done');dot(i,'active');
    document.getElementById('pl-stat').textContent='phrase '+(i+1)+'/'+n;
    if(!srcs[i]){{tmr=setTimeout(()=>playIdx(i+1),pauses[i]*1000);return;}}
    aud=new Audio(srcs[i]);
    aud.onended=()=>{{dot(i,'done');tmr=setTimeout(()=>playIdx(i+1),pauses[i]*1000);}};
    aud.onerror=()=>{{tmr=setTimeout(()=>playIdx(i+1),500);}};
    aud.play().catch(()=>{{tmr=setTimeout(()=>playIdx(i+1),500);}});}}
  window.plToggle=function(){{if(playing){{stop();}}else{{
    document.getElementById('pl-btn').textContent='■ Stop';
    document.getElementById('pl-btn').style.color='#FF7B6B';playIdx(0);}}}};
}})();
</script>
"""

def autoplaylist_html_with_highlight(audio_paths, pause_secs, uid="pl"):
    """Autoplaylist that also updates a URL param so Python can highlight active phrase."""
    srcs = []
    for p in audio_paths:
        if p and Path(p).exists():
            with open(p, "rb") as f:
                srcs.append("data:audio/mp3;base64," + base64.b64encode(f.read()).decode())
        else:
            srcs.append("")
    srcs_js   = str(srcs).replace("'", '"')
    pauses_js = str([round(s, 2) for s in pause_secs])
    n = len(srcs)
    return f"""
<div style="background:#FFFFFF;border:1px solid #E8E2D8;border-radius:12px;padding:14px 18px;margin:8px 0;">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
    <button id="pl-btn-{uid}" onclick="plToggle_{uid}()"
      style="background:#ECEBFB;color:#4F46E5;border:1px solid #4F46E5;border-radius:8px;
             padding:7px 18px;cursor:pointer;font-family:JetBrains Mono,monospace;font-size:.88rem;">
      ▶ Play All
    </button>
    <span id="pl-stat-{uid}" style="color:#7A7390;font-size:.8rem;font-family:JetBrains Mono,monospace;">ready</span>
  </div>
  <div id="pl-bar-{uid}" style="margin-top:10px;display:flex;gap:4px;flex-wrap:wrap;"></div>
</div>
<script>
(function(){{
  const srcs={srcs_js},pauses={pauses_js},n={n},uid='{uid}';
  let cur=-1,playing=false,aud=null,tmr=null;
  const bar=document.getElementById('pl-bar-'+uid);
  for(let i=0;i<n;i++){{const d=document.createElement('div');d.id='dot-'+uid+'-'+i;
    d.style.cssText='width:10px;height:10px;border-radius:50%;background:#ECEBFB;transition:.2s;';
    bar.appendChild(d);}}
  function dot(i,c){{const d=document.getElementById('dot-'+uid+'-'+i);if(!d)return;
    d.style.background=c==='active'?'#4F46E5':c==='done'?'#1FB888':'#ECEBFB';}}
  function stop(){{if(aud){{aud.pause();aud=null;}}if(tmr){{clearTimeout(tmr);tmr=null;}}
    playing=false;cur=-1;
    document.getElementById('pl-btn-'+uid).textContent='▶ Play All';
    document.getElementById('pl-btn-'+uid).style.color='#4F46E5';
    document.getElementById('pl-stat-'+uid).textContent='done ✓';
    for(let i=0;i<n;i++)dot(i,'done');}}
  function playIdx(i){{
    if(i>=n){{stop();return;}}
    cur=i;playing=true;
    for(let j=0;j<i;j++)dot(j,'done');dot(i,'active');
    document.getElementById('pl-stat-'+uid).textContent='▶ phrase '+(i+1)+'/'+n;
    // Notify parent frame of active index for row highlighting
    try{{window.parent.postMessage({{type:'imlls_highlight',uid:uid,idx:i}},'*');}}catch(e){{}}
    if(!srcs[i]){{tmr=setTimeout(()=>playIdx(i+1),pauses[i]*1000);return;}}
    aud=new Audio(srcs[i]);
    aud.onended=()=>{{dot(i,'done');tmr=setTimeout(()=>playIdx(i+1),pauses[i]*1000);}};
    aud.onerror=()=>{{tmr=setTimeout(()=>playIdx(i+1),500);}};
    aud.play().catch(()=>{{tmr=setTimeout(()=>playIdx(i+1),500);}});}}
  window['plToggle_'+uid]=function(){{
    if(playing){{stop();document.getElementById('pl-stat-'+uid).textContent='stopped';}}
    else{{document.getElementById('pl-btn-'+uid).textContent='■ Stop';
          document.getElementById('pl-btn-'+uid).style.color='#FF7B6B';playIdx(0);}}}};
}})();
</script>
"""

def autoplaylist_with_table(phrases, audio_paths, pause_secs, uid="pl",
                            show_native=True, show_target=True):
    """All-in-one component: phrase table + audio player inside the same iframe.
    The currently playing phrase row gets a bright highlight so the user can
    see exactly which phrase is being spoken."""
    import json as _json

    # Build base64-encoded audio sources
    srcs = []
    for p in audio_paths:
        if p and Path(p).exists():
            with open(p, "rb") as f:
                srcs.append("data:audio/mp3;base64," + base64.b64encode(f.read()).decode())
        else:
            srcs.append("")
    srcs_js   = _json.dumps(srcs)
    pauses_js = _json.dumps([round(s, 2) for s in pause_secs])
    n = len(srcs)

    # Build the phrase table HTML rows
    def _esc(t):
        # Minimal HTML escape so the rows can't break the markup
        return (str(t).replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))

    rows_html = ""
    for i, p in enumerate(phrases):
        nat = _esc(p["native"]) if show_native else "—"
        tgt = _esc(p["target"]) if show_target else "—"
        rows_html += (
            f'<div class="ph-row" id="row-{uid}-{i}">'
            f'  <span class="ph-num">{i+1:02d}</span>'
            f'  <span class="ph-nat">{nat}</span>'
            f'  <span class="ph-tgt">{tgt}</span>'
            f'</div>'
        )

    return f"""
<style>
  .ph-table {{
    background:#FFFFFF; border:1px solid #DDD6CA; border-radius:12px;
    overflow:hidden; margin:10px 0;
  }}
  .ph-row {{
    display:flex; align-items:center; padding:11px 18px;
    border-bottom:1px solid #E8E2D8; gap:14px;
    transition: background .15s, border-left-color .15s;
    border-left:3px solid transparent;
  }}
  .ph-row:last-child {{ border-bottom:none; }}
  .ph-num {{ font-family:'JetBrains Mono',monospace; color:#2E27A8;
            font-size:.73rem; min-width:26px; }}
  .ph-nat {{ color:#7A7390; flex:1; font-size:.93rem; }}
  .ph-tgt {{ color:#4B4564; flex:1; font-size:.93rem; font-weight:500; }}
  .ph-row.active {{
    background:#ECEBFB; border-left-color:#4F46E5;
  }}
  .ph-row.active .ph-nat {{ color:#1B1730; }}
  .ph-row.active .ph-tgt {{ color:#1B1730; font-weight:600; }}
  .ph-row.done {{ background:#F4F0EB; }}
  .ph-row.done .ph-tgt {{ color:#0E6E50; }}
  .pl-wrap {{
    background:#FFFFFF; border:1px solid #E8E2D8; border-radius:12px;
    padding:14px 18px; margin:8px 0;
  }}
  .pl-btn {{
    background:#ECEBFB; color:#4F46E5; border:1px solid #4F46E5;
    border-radius:8px; padding:7px 18px; cursor:pointer;
    font-family:'JetBrains Mono',monospace; font-size:.88rem;
  }}
  .pl-stat {{
    color:#7A7390; font-size:.8rem; font-family:'JetBrains Mono',monospace;
    margin-left:12px;
  }}
  .pl-bar {{ margin-top:10px; display:flex; gap:4px; flex-wrap:wrap; }}
  .pl-dot {{
    width:10px; height:10px; border-radius:50%;
    background:#ECEBFB; transition:.2s;
  }}
</style>

<!-- Player FIRST so mobile users see the Play All button without scrolling -->
<div class="pl-wrap">
  <button id="pl-btn-{uid}" class="pl-btn" onclick="plToggle_{uid}()">▶ Play All</button>
  <span id="pl-stat-{uid}" class="pl-stat">ready</span>
  <div id="pl-bar-{uid}" class="pl-bar"></div>
</div>

<div class="ph-table">{rows_html}</div>

<script>
(function(){{
  const srcs={srcs_js}, pauses={pauses_js}, n={n}, uid='{uid}';
  let cur=-1, playing=false, aud=null, tmr=null;

  // Build dots
  const bar = document.getElementById('pl-bar-'+uid);
  for (let i=0; i<n; i++) {{
    const d = document.createElement('div');
    d.id = 'dot-'+uid+'-'+i;
    d.className = 'pl-dot';
    bar.appendChild(d);
  }}
  function dot(i, c) {{
    const d = document.getElementById('dot-'+uid+'-'+i);
    if (!d) return;
    d.style.background = c==='active' ? '#4F46E5'
                       : c==='done'   ? '#1FB888' : '#ECEBFB';
  }}

  // Highlight rows
  function setRow(i, cls) {{
    const r = document.getElementById('row-'+uid+'-'+i);
    if (!r) return;
    if (cls === 'clear') {{ r.classList.remove('active','done'); return; }}
    r.classList.remove('active','done');
    r.classList.add(cls);
  }}
  function clearAllRows() {{
    for (let i=0; i<n; i++) setRow(i, 'clear');
  }}

  function ensureAud() {{
    // Create ONE Audio element only inside a user-gesture handler.
    // iOS Safari grants playback permission to elements unlocked by a tap;
    // we reuse this element for every track so the permission persists.
    if (aud) return;
    aud = new Audio();
    aud.preload = 'auto';
    aud.addEventListener('ended', function() {{
      var i = cur;
      dot(i, 'done'); setRow(i, 'done');
      tmr = setTimeout(function() {{ playIdx(i + 1); }}, pauses[i] * 1000);
    }});
    aud.addEventListener('error', function() {{
      tmr = setTimeout(function() {{ playIdx(cur + 1); }}, 500);
    }});
  }}

  function stop() {{
    if (aud) {{ try {{ aud.pause(); }} catch(e) {{}} }}
    if (tmr) {{ clearTimeout(tmr); tmr = null; }}
    playing = false; cur = -1;
    document.getElementById('pl-btn-'+uid).textContent = '▶ Play All';
    document.getElementById('pl-btn-'+uid).style.color = '#4F46E5';
  }}

  function playIdx(i) {{
    if (i >= n) {{
      stop();
      document.getElementById('pl-stat-'+uid).textContent = 'done ✓';
      for (let j=0; j<n; j++) {{ dot(j,'done'); setRow(j,'done'); }}
      return;
    }}
    cur = i; playing = true;
    // Mark previous as done, current as active
    for (let j=0; j<i; j++) {{ dot(j,'done'); setRow(j,'done'); }}
    dot(i, 'active'); setRow(i, 'active');
    document.getElementById('pl-stat-'+uid).textContent = '▶ phrase ' + (i+1) + ' / ' + n;

    if (!srcs[i]) {{
      tmr = setTimeout(function() {{ playIdx(i+1); }}, pauses[i] * 1000);
      return;
    }}
    aud.src = srcs[i];
    var p = aud.play();
    if (p && typeof p.catch === 'function') {{
      p.catch(function() {{
        tmr = setTimeout(function() {{ playIdx(i+1); }}, 500);
      }});
    }}
  }}

  window['plToggle_'+uid] = function() {{
    if (playing) {{
      stop();
      document.getElementById('pl-stat-'+uid).textContent = 'stopped';
    }} else {{
      ensureAud();  // must run inside this user-gesture click handler
      clearAllRows();
      for (let i=0; i<n; i++) dot(i, '');
      document.getElementById('pl-btn-'+uid).textContent = '■ Stop';
      document.getElementById('pl-btn-'+uid).style.color = '#FF7B6B';
      playIdx(0);
    }}
  }};
}})();
</script>
"""


def phrase_pause(phrase):
    words = len(phrase.split())
    return min(max(round(words / 2, 1), 1.5), 4.0)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def play(path: str, auto=False):
    if not path or not Path(path).exists(): return
    with open(path,"rb") as f: d=base64.b64encode(f.read()).decode()
    a = "autoplay" if auto else ""
    st.markdown(f'<audio controls {a}><source src="data:audio/mp3;base64,{d}" type="audio/mp3"></audio>',
                unsafe_allow_html=True)


def phrase_table(phrases, show_native=True, show_target=True, scores=None, highlight=None, active_idx=None):
    html = ""
    for i, p in enumerate(phrases):
        num  = f'<span class="pnum">{i+1:02d}</span>'
        nat  = f'<span class="pnat">{p["native"]}</span>'  if show_native  else '<span class="phide">—</span>'
        tgt  = f'<span class="ptgt">{p["target"]}</span>'  if show_target  else '<span class="phide">—</span>'
        sc   = ""
        if scores and i in scores:
            s   = scores[i]
            cls = "spass" if s["passed"] else "sfail"
            sc  = f'<span class="{cls}">{int(s["score"]*100)}%</span>'
        # active_idx = currently playing phrase (bright highlight)
        # highlight  = legacy dimmer highlight
        if active_idx == i:
            row_cls = ' class="prow prow-active"'
        elif highlight == i:
            row_cls = ' class="prow" style="background:var(--mova-surface-2)"'
        else:
            row_cls = ' class="prow"'
        html += f'<div{row_cls}>{num}{nat}{tgt}{sc}</div>'
    st.markdown(f'<div class="ptable">{html}</div>', unsafe_allow_html=True)


def _try_first_msg(session: "LessonSession") -> str:
    """Return a localized 'try the exercise first' tooltip in the user's native language."""
    native_lang = session.state.native_lang if session else "English"
    return i18n.get(native_lang, "try_first")


def _lock_hint(session: "LessonSession"):
    """Render a visible mobile-friendly hint when the Next button is locked."""
    msg = _try_first_msg(session)
    st.markdown(
        f'<div style="color:var(--mova-amber-ink);font-size:.78rem;'
        f'text-align:center;margin:-6px 0 10px;opacity:.9">🔒 {msg}</div>',
        unsafe_allow_html=True,
    )


def step_hdr(step, title=None, desc=None, total=8, show_image=False):
    """Render the step header.

    Title and hint are read from engine.i18n based on the current session's
    native language. Adaptive step sequence (if active) is read from
    session_state so every step function gets correct pill rendering
    without changing its own signature.
    """
    # Look up the user's native language from the active session
    sess = st.session_state.get("session")
    native_lang = sess.state.native_lang if sess else "English"

    if title is None:
        title = i18n.get(native_lang, "titles", step)
    if desc is None:
        desc = i18n.get(native_lang, "hints", step)

    icon       = i18n.step_icon(step)
    s_type     = i18n.step_type(step)
    step_label = i18n.get(native_lang, "step_label")
    req_word   = i18n.get(native_lang, "required")

    # ── Adaptive-aware pill rendering ──────────────────────────────────────
    adp_steps = st.session_state.get("_adaptive_steps")
    adp_idx   = st.session_state.get("_adaptive_idx", 0)

    if adp_steps:
        seq       = adp_steps
        adp_total = len(seq)
        pos_label = adp_idx + 1        # 1-based position shown to user

        # Deduplicate while preserving order (handles EXTRA_REPEAT)
        seen_s: set = set()
        unique_seq = [s for s in seq if not (s in seen_s or seen_s.add(s))]  # type: ignore[func-returns-value]

        def _pcls(s: int) -> str:
            occurrences = [i for i, x in enumerate(seq) if x == s]
            if s == step and any(i == adp_idx for i in occurrences):
                return "pill-active"
            if max(occurrences) < adp_idx:
                return "pill-done"
            if s in REQUIRED_STEPS:
                return "pill-required"
            return ""

        def _plbl(s: int) -> str:
            occurrences = [i for i, x in enumerate(seq) if x == s]
            pending = max(occurrences) >= adp_idx and not any(i == adp_idx for i in occurrences)
            return "🔒" if (pending and s in REQUIRED_STEPS) else str(s)

        pills = "".join(
            f'<span class="pill {_pcls(s)}">{_plbl(s)}</span>'
            for s in unique_seq
        )
    else:
        adp_total = total
        pos_label = step
        pills = "".join(
            f'<span class="pill {"pill-active" if s==step else "pill-done" if s<step else "pill-required" if s in REQUIRED_STEPS and s>step else ""}">'
            f'{"🔒" if s in REQUIRED_STEPS and s > step else s}</span>'
            for s in range(1, total + 1)
        )

    req_note = (f' <span style="color:var(--mova-amber-ink);font-size:.72rem;">🔒 {req_word}</span>'
                if step in REQUIRED_STEPS else '')

    st.markdown(f"""
    <div class="step-header step-type-{s_type}">
      <div class="step-icon-row">
        <span class="step-icon-big">{icon}</span>
        <div style="flex:1">
          <div class="step-title">{title}</div>
          <div class="step-desc">{desc}</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    # Show lesson illustration if requested
    if show_image and sess:
        _mod = _current_module()
        if _mod == "vocab" and len(sess.df) > 0:
            topic = sess.df.iloc[0].get("topic", "")
            _show_vocab_image(topic)
        elif _mod == "grammar":
            _show_lesson_image(sess.state.lesson_id)
        elif _mod == "custom":
            _p = APP_IMG_DIR / "my_phrases_banner.jpg"
            if _p.exists():
                _, _mid, _ = st.columns([1, 2, 1])
                with _mid:
                    st.image(str(_p), use_container_width=True)


def _audio_duration_ms(audio_bytes: bytes) -> int:
    """Extract audio duration from WAV/WebM bytes. Returns ms, or 0 on failure."""
    try:
        import io, wave
        with wave.open(io.BytesIO(audio_bytes)) as wf:
            return int(wf.getnframes() / wf.getframerate() * 1000)
    except Exception:
        pass
    try:
        # Fallback: estimate from file size (~16kHz mono webm)
        return max(0, int(len(audio_bytes) / 32000 * 1000))
    except Exception:
        return 0


def do_score(session: LessonSession, audio: bytes, expected: str,
             lang: str, step: int, phrase_id: int = 0) -> dict | None:
    """Transcribe audio, score against expected, log with audio duration."""
    if not audio: return None
    if not whisper_available():
        st.warning("Whisper not installed — install `openai-whisper` for voice scoring.")
        return None
    duration_ms = _audio_duration_ms(audio)
    with st.spinner("Transcribing…"):
        text = transcribe_bytes(audio, language=lang)
    # Pass duration_ms so logger records actual recording length, not wall-clock
    result = session.score(text, expected, step=step, phrase_id=phrase_id,
                           duration_ms=duration_ms if duration_ms > 0 else None)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — Read all phrases (both languages visible)
# ═══════════════════════════════════════════════════════════════════════════
def step1(session: LessonSession, tts_lang, wh_lang):
    session.start_step(1)
    step_hdr(1, show_image=True)
    phrases = session.phrases()
    scores  = st.session_state.get("s1_scores", {})

    # Mic at the top so mobile users don't need to scroll past the phrase list
    audio = audio_input("s1")

    if audio and st.button("Submit & Check", type="primary",
                           use_container_width=True, key="s1_submit"):
        full = ". ".join(p["target"] for p in phrases)
        r    = do_score(session, audio, full, wh_lang, step=1, phrase_id=0)
        if r:
            scores = {i: r for i in range(len(phrases))}
            st.session_state["s1_scores"] = scores
            st.markdown(
                f"{'✓' if r['passed'] else '✗'} **{int(r['score']*100)}%** — "
                f"`{r['transcribed']}`"
            )

    # Character above phrases — shown once per step entry, not on button-click rerun
    if "s1_char_shown" not in st.session_state:
        st.session_state["s1_char_shown"] = True
        show_character("natalia", "motivation")

    # Phrase list
    phrase_table(phrases, show_native=True, show_target=True, scores=scores)

    # Next button — active only after the user has recorded at least once
    attempted = bool(audio) or bool(st.session_state.get("s1_scores"))
    if st.button("Next →", use_container_width=True, key="s1_next",
                 disabled=not attempted,
                 help=None if attempted else _try_first_msg(session)):
        st.session_state.pop("s1_char_shown", None)
        return True
    if not attempted:
        _lock_hint(session)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Listen & Repeat (auto-playlist with pause, both languages visible)
# ═══════════════════════════════════════════════════════════════════════════
def step2(session: LessonSession, tts_lang, wh_lang):
    session.start_step(2)
    step_hdr(2, show_image=True)
    phrases = session.phrases()
    paths   = [get_audio_path(p["target"], tts_lang) for p in phrases]
    pauses  = [phrase_pause(p["target"]) for p in phrases]

    # Caption removed — step_hdr shows the instruction in user's native language.
    # Combined table + player: the row of the currently playing phrase is highlighted
    height = 200 + 48 * len(phrases)
    components.html(
        autoplaylist_with_table(phrases, paths, pauses, uid="s2",
                                show_native=True, show_target=True),
        height=height, scrolling=True,
    )

    # Mark attempted as soon as the playlist renders (audio autoplays)
    st.session_state["s2_attempted"] = True
    attempted = st.session_state.get("s2_attempted", False)
    if st.button("Continue to Step 3 →", type="primary", use_container_width=True,
                 disabled=not attempted,
                 help=None if attempted else _try_first_msg(session)):
        st.session_state.pop("s2_active", None)
        st.session_state.pop("s2_attempted", None)
        return True
    if not attempted:
        _lock_hint(session)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — Listen & Match (hear target → pick correct native from shuffled list)
# ═══════════════════════════════════════════════════════════════════════════
def step3(session: LessonSession, tts_lang, wh_lang):
    session.start_step(3)
    step_hdr(3, show_image=True)
    phrases = session.phrases()

    if "s3_idx" not in st.session_state:
        st.session_state["s3_idx"]    = 0
        st.session_state["s3_scores"] = {}
        # pre-shuffle all choices per phrase
        for i in range(len(phrases)):
            opts = [p["native"] for p in phrases]
            random.shuffle(opts)
            st.session_state[f"s3_opts_{i}"] = opts

    idx    = st.session_state["s3_idx"]
    scores = st.session_state["s3_scores"]

    # Answered so far
    if scores:
        done_html = "".join(
            f'<div class="prow"><span class="pnum">{i+1:02d}</span>'
            f'<span style="color:{"var(--mova-mint-ink)" if v else "var(--mova-coral-ink)"};flex:1">'
            f'{"✓" if v else "✗"} {phrases[i]["target"]}</span></div>'
            for i, v in sorted(scores.items())
        )
        st.markdown(f'<div class="ptable">{done_html}</div>', unsafe_allow_html=True)

    if idx < len(phrases):
        p  = phrases[idx]
        ap = get_audio_path(p["target"], tts_lang)
        st.markdown(f"---\n**Phrase {idx+1} — listen and choose:**")
        if ap:
            # Use a unique key per phrase index so audio reloads on each new phrase
            with open(ap, "rb") as f: d = base64.b64encode(f.read()).decode()
            st.markdown(
                f'<audio controls autoplay key="{idx}" style="width:100%;border-radius:8px;margin:4px 0">'
                f'<source src="data:audio/mp3;base64,{d}" type="audio/mp3"></audio>',
                unsafe_allow_html=True,
            )

        st.markdown("**Select the correct translation:**")
        for ci, choice in enumerate(st.session_state[f"s3_opts_{idx}"]):
            if st.button(choice, key=f"s3_{idx}_{ci}", use_container_width=True):
                correct = (choice == p["native"])
                scores[idx] = correct
                st.session_state["s3_scores"] = scores
                st.session_state["s3_idx"]    = idx + 1
                session.score(
                    p["native"] if correct else choice,
                    p["native"],
                    step=3,
                    phrase_id=int(p.get("phrase_id", idx)),
                )
                if correct:
                    st.success("✓ Correct!")
                else:
                    st.error(f"✗ Wrong — answer: **{p['native']}**")
                time.sleep(0.4)
                st.rerun()

    if idx >= len(phrases):
        ok = sum(1 for v in scores.values() if v)
        st.success(f"Done! {ok}/{len(phrases)} correct.")
        show_character("sophie", "on_lesson_complete")
        if st.button("Continue to Step 4 →", type="primary"):
            for k in ["s3_idx","s3_scores"] + [f"s3_opts_{i}" for i in range(len(phrases))]:
                st.session_state.pop(k, None)
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — Speed Reading (target only, timer starts on Record)
# ═══════════════════════════════════════════════════════════════════════════
def step4(session: LessonSession, tts_lang, wh_lang):
    session.start_step(4)
    step_hdr(4, show_image=True)
    phrases = session.phrases()

    # Mic at the top so mobile users don't need to scroll past the phrase list
    audio = audio_input("s4")

    # Submit button appears only after the user records audio
    if audio and st.button("Submit & Score", type="primary",
                           use_container_width=True, key="s4_submit"):
        duration_s = max(1, round(_audio_duration_ms(audio) / 1000))
        full = ". ".join(p["target"] for p in phrases)
        r = do_score(session, audio, full, wh_lang, step=4, phrase_id=0)
        if r:
            st.session_state["s4_result"] = {
                "time":  duration_s,
                "score": r["score"],
                "text":  r["transcribed"],
            }

    if "s4_result" in st.session_state:
        res = st.session_state["s4_result"]
        st.success(f"🏁 Reading speed: **{res['time']}s** · **{int(res['score']*100)}%** match")
        st.caption(f"Transcribed: {res['text']}")

    # Phrase list
    phrase_table(phrases, show_native=False, show_target=True)

    # Done button — active only after the user has recorded at least once
    attempted = bool(audio) or "s4_result" in st.session_state
    if st.button("Done →", use_container_width=True, key="s4_done",
                 disabled=not attempted,
                 help=None if attempted else _try_first_msg(session)):
        st.session_state.pop("s4_result", None)
        return True
    if not attempted:
        _lock_hint(session)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 5 — Shadowing (auto-playlist, see native only, repeat target aloud)
# ═══════════════════════════════════════════════════════════════════════════
def step5(session: LessonSession, tts_lang, wh_lang):
    session.start_step(5)
    step_hdr(5, show_image=True)
    phrases = session.phrases()
    paths   = [get_audio_path(p["target"], tts_lang) for p in phrases]
    pauses  = [phrase_pause(p["target"]) for p in phrases]

    # Caption removed — step_hdr shows the instruction in user's native language.
    # Combined table + player: only native is shown, target row is highlighted as it plays
    height = 200 + 48 * len(phrases)
    components.html(
        autoplaylist_with_table(phrases, paths, pauses, uid="s5",
                                show_native=True, show_target=False),
        height=height, scrolling=True,
    )

    # Mark attempted as soon as the playlist renders (audio autoplays)
    st.session_state["s5_attempted"] = True
    attempted = st.session_state.get("s5_attempted", False)
    if st.button("Continue to Step 6 →", type="primary", use_container_width=True,
                 disabled=not attempted,
                 help=None if attempted else _try_first_msg(session)):
        st.session_state.pop("s5_active", None)
        st.session_state.pop("s5_attempted", None)
        return True
    if not attempted:
        _lock_hint(session)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 6 — Active Translation (all phrases at once, single recording)
# ═══════════════════════════════════════════════════════════════════════════
def step6(session: LessonSession, tts_lang, wh_lang):
    session.start_step(6)
    step_hdr(6, show_image=True)
    phrases = session.phrases()
    scores  = st.session_state.get("s6_scores", {})

    # Mic at the top so mobile users don't need to scroll past the phrase list
    audio = audio_input("s6")

    if audio and st.button("Submit & Score", type="primary", use_container_width=True, key="s6_submit"):
        full = ". ".join(p["target"] for p in phrases)
        r = do_score(session, audio, full, wh_lang, step=6, phrase_id=0)
        if r:
            scores = {i: r for i in range(len(phrases))}
            st.session_state["s6_scores"] = scores
            st.session_state["s6_done"] = True
            st.markdown(f"{'✓' if r['passed'] else '✗'} **{int(r['score']*100)}%** — `{r['transcribed']}`")

    # Character above phrases — shown once per step entry, not on button-click rerun
    if "s6_char_shown" not in st.session_state:
        st.session_state["s6_char_shown"] = True
        show_character("mark", "motivation")

    # Phrase list (native shown, target hidden)
    phrase_table(phrases, show_native=True, show_target=False, scores=scores)

    # Next button — active only after the user has recorded at least once
    attempted = bool(audio) or bool(st.session_state.get("s6_scores"))
    if st.button("Next →", use_container_width=True, key="s6_next",
                 disabled=not attempted,
                 help=None if attempted else _try_first_msg(session)):
        st.session_state["s6_idx"] = 0
        st.session_state.pop("s6_char_shown", None)
        return True
    if not attempted:
        _lock_hint(session)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 7 — Speed Translation (native only, timer, translate all)
# ═══════════════════════════════════════════════════════════════════════════
# Step 7 pass criteria — also used to inform the user up-front
_S7_SECONDS_PER_TWO_WORDS = 1.5   # ≤ 1 sec per 2 target-language words
_S7_MIN_SIMILARITY        = 0.80  # ≥ 80% similarity


def step7(session: LessonSession, tts_lang, wh_lang):
    session.start_step(7)
    step_hdr(7, show_image=True)
    phrases = session.phrases()

    # ── Pass criteria for this lesson ──
    # Speed target: 1 second per 2 target-language words across all phrases
    total_words = sum(len(p["target"].split()) for p in phrases)
    max_seconds = max(1, round(total_words / 2 * _S7_SECONDS_PER_TWO_WORDS))
    st.caption(
        f"Time: **≤ {max_seconds}s** "
        f"and **≥ {int(_S7_MIN_SIMILARITY*100)}%** accuracy."
    )

    # ── Record & Submit ──
    # No live timer: speed = actual audio recording length.
    st.markdown("#### 🎙️ Translate all phrases and record")
    audio = audio_input("s7")

    # Submit button appears only after the user records audio
    if audio and st.button("Submit & Score", type="primary",
                           use_container_width=True, key="s7_submit"):
        duration_s = max(1, round(_audio_duration_ms(audio) / 1000))
        full = ". ".join(p["target"] for p in phrases)
        r = do_score(session, audio, full, wh_lang, step=7, phrase_id=0)
        if r:
            st.session_state["s7_result"] = {
                "time":  duration_s,
                "score": r["score"],
            }

    if "s7_result" in st.session_state:
        res      = st.session_state["s7_result"]
        time_ok  = res["time"] <= max_seconds
        score_ok = res["score"] >= _S7_MIN_SIMILARITY
        passed   = time_ok and score_ok

        if passed:
            st.success(
                f"🎉 Passed! Translation speed: **{res['time']}s** · "
                f"**{int(res['score']*100)}%** accuracy."
            )
        else:
            problems = []
            if not time_ok:
                problems.append(
                    f"speed {res['time']}s > target {max_seconds}s"
                )
            if not score_ok:
                problems.append(
                    f"accuracy {int(res['score']*100)}% < "
                    f"{int(_S7_MIN_SIMILARITY*100)}% required"
                )
            st.warning(
                "Not quite there yet — " + " · ".join(problems) +
                ". You can still continue to Step 8."
            )

    # Character above phrases — shown once per step entry, not on button-click rerun
    if "s7_char_shown" not in st.session_state:
        st.session_state["s7_char_shown"] = True
        show_character("polyglot", "rare_bonus")

    # Phrase list in the middle (native shown, target hidden)
    phrase_table(phrases, show_native=True, show_target=False)

    # Navigation at the bottom — only after a recording was scored
    if "s7_result" in st.session_state:
        if st.button("Continue to Step 8 →", type="primary",
                     use_container_width=True, key="s7_continue"):
            st.session_state.pop("s7_result", None)
            st.session_state.pop("s7_char_shown", None)
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Lesson complete
# ═══════════════════════════════════════════════════════════════════════════
def _char_img_b64(character_key: str) -> str:
    """Повертає base64 PNG персонажа або порожній рядок."""
    from pathlib import Path as _Path
    import base64 as _b64
    p = ROOT / "assets" / "characters" / f"{character_key}.png"
    if p.exists():
        return _b64.b64encode(p.read_bytes()).decode()
    return ""


def render_complete(session: LessonSession):
    # ── Визначаємо персонажа і фразу ─────────────────────────────────────────
    from engine.characters import get_phrase as _get_phrase

    # Мова
    _nat_lang = session.state.native_lang or st.session_state.get("launcher_native", "English")

    # Прогрес streak — потрібен щоб вибрати правильну категорію фрази
    _streak = st.session_state.get("_cached_streak", 0)
    _category = "on_streak" if _streak > 1 else "on_lesson_complete"

    _char_data = _get_phrase("natalia", _category, lang=_nat_lang)
    _phrase    = _char_data["phrase"] if _char_data else "Great work! Keep it up 🎉"
    _char_name = _char_data["name"]   if _char_data else "Natalia"
    _img_b64   = _char_img_b64("natalia")
    _img_tag   = (
        '<img src="data:image/png;base64,' + _img_b64 + '" '
        'style="width:110px;height:110px;object-fit:cover;'
        'border-radius:50%;border:3px solid var(--mova-mint);'
        'box-shadow:0 4px 14px rgba(0,0,0,.15);margin-bottom:8px;" />'
        if _img_b64 else
        '<div style="font-size:4rem;margin-bottom:8px;">👩‍🏫</div>'
    )

    st.markdown(
        '<div class="cbanner" style="padding:32px 36px;">'
        '<div style="font-size:2.4rem;margin-bottom:6px;">🎉</div>'
        '<h2 style="color:var(--mova-ink);margin:0 0 20px 0;">Lesson Complete!</h2>'
        '<div style="display:flex;align-items:center;gap:22px;'
        'background:rgba(255,255,255,.45);border-radius:14px;'
        'padding:18px 22px;text-align:left;">'
        '<div style="flex-shrink:0;text-align:center;">'
        + _img_tag +
        '<div style="font-size:.75rem;font-weight:600;color:#E65100;margin-top:2px;">'
        + _char_name +
        '</div></div>'
        '<div style="font-size:1rem;color:#333;line-height:1.55;">'
        '&#128172; ' + _phrase +
        '</div></div></div>',
        unsafe_allow_html=True,
    )

    # ── Зберігаємо прогрес (один раз) ────────────────────────────────────────
    if not st.session_state.get("_progress_saved"):
        session.complete()
        st.session_state["_progress_saved"] = True
        try:
            _llang = {"English":"en","Ukrainian":"uk","Spanish":"es","Korean":"ko","French":"fr","German":"de","Japanese":"ja","Chinese":"zh","Portuguese":"pt","Italian":"it","Polish":"pl","Russian":"ru"}.get(
                st.session_state.get("launcher_native","English"), "en")
            _lres  = on_lesson_complete(session.state.user_id, _llang)
            _ltoasts = [f"🎉 Урок завершено! +{_lres['xp_earned']} XP бонус"]
            if _lres.get("leveled_up"):
                _ltoasts.append(f"⭐ Новий рівень {_lres['level_num']}: {_lres['level_name']}!")
            for _bid, _bem, _bname, _bdesc in _lres.get("new_badges", []):
                _ltoasts.append(f"{_bem} Бейдж «{_bname}»: {_bdesc}!")
            streak = _lres.get("streak_current", 0)
            st.session_state["_cached_streak"] = streak
            if streak > 1:
                _ltoasts.append(f"🔥 Серія {streak} {'день' if streak == 1 else 'днів'}!")
            # Поліглот кожні 5 уроків — окремо під банером
            _lessons_done = st.session_state.get("_total_lessons_done", 0) + 1
            st.session_state["_total_lessons_done"] = _lessons_done
            st.session_state["_pending_toasts"] = (
                st.session_state.get("_pending_toasts", []) + _ltoasts
            )
        except Exception:
            pass

    module = _current_module()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔄 Redo lesson", use_container_width=True, type="primary"):
            st.session_state.pop("_progress_saved", None)
            _clear_lesson()
            # Reset adaptive index so the sequence starts from step 1 again
            st.session_state.pop("_adaptive_lesson_id", None)
            st.session_state["lesson_step"] = 1
            st.rerun()
    with c2:
        # Custom mode has no fixed "next lesson" — show "Back to my phrases" instead
        if module == "custom":
            if st.button("📝 Back to my phrases", use_container_width=True):
                st.session_state.pop("_progress_saved", None)
                _clear_all()
                st.session_state["active_module"] = "custom"
                st.rerun()
        elif st.button("▶ Next lesson", use_container_width=True):
            # Load next lesson automatically — module-aware
            sess   = st.session_state["session"]
            state  = sess.state
            cfg    = _module_config(_current_module())
            try:
                df_all    = cfg["load"](str(cfg["db_path"]), state.native_lang, state.target_lang)
                lessons   = cfg["get_lessons"](df_all)
                next_id   = state.lesson_id + 1
                if next_id in lessons:
                    lang_pair = state.language_pair
                    lesson_df = cfg["get_lesson"](df_all, next_id)
                    st.session_state.pop("_progress_saved", None)
                    _clear_lesson()
                    # Clear adaptive so it reinitialises for the new lesson
                    st.session_state.pop("_adaptive_lesson_id", None)
                    from engine.recommender import unit_id_for
                    _next_topic = None
                    if cfg.get("lang_suffix") in ("vocab", "phrasebook"):
                        _next_topic = _recommender.vocab_topic_for_lesson(
                            next_id, state.target_lang, cfg["db_path"])
                    st.session_state.update({
                        "session":     LessonSession(state.user_id, lesson_df, next_id,
                                                     state.native_lang, state.target_lang,
                                                     language_pair=lang_pair,
                                                     unit_id=unit_id_for(cfg.get("lang_suffix"), next_id, _next_topic)),
                        "lesson_step": 1,
                    })
                    st.rerun()
                else:
                    st.info("This was the last lesson!")
            except Exception as e:
                st.error(f"Error loading next lesson: {e}")
    with c3:
        if st.button("📚 Choose lesson", use_container_width=True):
            st.session_state.pop("_progress_saved", None)
            _clear_all()
            st.rerun()




# ═══════════════════════════════════════════════════════════════════════════
# Setup screen
# ═══════════════════════════════════════════════════════════════════════════
def render_setup():
    module = _current_module()
    cfg    = _module_config(module)

    st.markdown(f"""
    <div style="text-align:center;padding:32px 0 16px">
      <h1 style="color:var(--mova-ink);font-weight:700;margin:0 0 2px;font-size:2rem">{cfg['label']}</h1>
    </div>""", unsafe_allow_html=True)

    _setup_img_name = "vocab_basic.jpg" if module == "vocab" else "vocab_school.jpg"
    _setup_img = APP_IMG_DIR / _setup_img_name
    if _setup_img.exists():
        _, _mid, _ = st.columns([1, 2, 1])
        with _mid:
            st.image(str(_setup_img), use_container_width=True)

    db_path = cfg["db_path"]
    if not db_path.exists():
        st.error(f"Database not found: `{db_path}`\n\nPlace the file in the `data/` folder.")
        st.stop()

    # ── Query-params bridge: wave clicked a lesson (all modules) ──────────────
    if cfg.get("load") is not None:
        _qp = st.query_params
        if "vnav_lesson" in _qp:
            try:
                from urllib.parse import unquote as _uq
                _qp_lid    = int(_qp["vnav_lesson"])
                _qp_native = _uq(_qp.get("vnav_native", "English"))
                _qp_target = _uq(_qp.get("vnav_target", "Ukrainian"))
                # Identity must come from the authenticated session, never from
                # the URL — vnav_user is only echoed there for the JS wave-nav
                # widget to round-trip navigation; trusting it directly would
                # let anyone edit the address bar to read/write another
                # user's progress.
                _qp_user   = st.session_state.get("launcher_user", "student1")
                if _qp_native not in LANGUAGES:
                    _qp_native = "English"
                if _qp_target not in LANGUAGES or _qp_target == _qp_native:
                    _qp_target = next(l for l in LANGUAGES if l != _qp_native)
                st.query_params.clear()
                # Vocab/Phrasebook: fetch the topic for unit_id_for below --
                # CEFR-J's one small CSV is always loaded whole, no topic
                # kwarg needed for the loader itself.
                _qp_topic = None
                if cfg.get("lang_suffix") in ("vocab", "phrasebook"):
                    _qp_topic = _recommender.vocab_topic_for_lesson(
                        _qp_lid, _qp_target, db_path)
                _qp_df        = cfg["load"](str(db_path), _qp_native, _qp_target)
                _qp_lesson_df = cfg["get_lesson"](_qp_df, _qp_lid)
                if not _qp_lesson_df.empty:
                    from engine.recommender import unit_id_for
                    _qp_lp = (f"{WHISPER_LANG.get(_qp_native,'?')}"
                              f"-{WHISPER_LANG.get(_qp_target,'?')}-{cfg['lang_suffix']}")
                    st.session_state.update({
                        "session":     LessonSession(_qp_user, _qp_lesson_df,
                                                     _qp_lid, _qp_native, _qp_target,
                                                     language_pair=_qp_lp,
                                                     unit_id=unit_id_for(cfg.get("lang_suffix"), _qp_lid, _qp_topic)),
                        "lesson_step": 1,
                        "tts_lang":    TTS_LANG.get(_qp_target, "en"),
                        "wh_lang":     WHISPER_LANG.get(_qp_target),
                        "lang_pair":   _qp_lp,
                    })
                    st.rerun()
            except Exception:
                st.query_params.clear()

    # Pre-fill from the launcher if the user picked language / username there
    default_native = st.session_state.get("launcher_native", "English")
    if default_native not in LANGUAGES:
        default_native = "English"
    default_target = st.session_state.get("launcher_target", "Ukrainian")

    c1, c2 = st.columns(2)
    with c1:
        native = st.selectbox(
            "🌐 Native language", LANGUAGES,
            index=LANGUAGES.index(default_native),
        )
    with c2:
        target_options = [l for l in LANGUAGES if l != native]
        target_idx     = (target_options.index(default_target)
                          if default_target in target_options else 0)
        target = st.selectbox("🎯 Target language", target_options,
                              index=target_idx)

    # ── Load lessons ──────────────────────────────────────────────────────────
    # Eager path for every module, including vocab: CEFR-J (CLAUDE.md
    # 2026-08-22) is one small CSV for every target_lang now, not the old
    # multi-sheet Word Bank workbook, so there's no per-sheet laziness to
    # gain from a separate lazy-index path anymore.
    try:
        df = cfg["load"](str(db_path), native, target)
    except Exception as e:
        st.error(f"Error: {e}"); st.stop()
    lessons       = cfg["get_lessons"](df)
    counts_by_lid = df.groupby("lesson_id").size().to_dict() if not df.empty else {}

    # Suffix language_pair with module so grammar/vocab progress are tracked separately
    lang_pair = f"{WHISPER_LANG.get(native,'?')}-{WHISPER_LANG.get(target,'?')}-{cfg['lang_suffix']}"
    user_id = st.session_state.get("launcher_user", "student1")

    if not lessons:
        st.warning(f"⚠️ No {cfg['label'].lower()} lessons available for {native} → {target}. "
                   "The Excel file might not have data for this language pair yet.")
        st.stop()

    # Auto-select lesson based on saved progress.
    # progress = {"last_completed_lesson": int, "last_step": int}
    # last_step convention: 1..8 = mid-lesson; 99 = lesson done
    progress      = _get_progress(user_id, target, cfg["lang_suffix"]) if user_id else None
    default_idx   = 0
    resume_step   = 1   # which step to start at when "Start" is pressed
    resume_msg    = None

    if progress:
        saved_lesson = progress["last_completed_lesson"]
        saved_step   = progress["last_step"]

        if saved_step >= 99:
            # Lesson fully done -> offer next lesson at step 1
            next_lesson = saved_lesson + 1
            if next_lesson in lessons:
                default_idx = lessons.index(next_lesson)
                resume_step = 1
                resume_msg  = f"▶ Continuing from {cfg['lesson_word']} {next_lesson} (last completed: {saved_lesson})"
            else:
                st.success(f"🎉 All {cfg['label'].lower()} lessons completed for this language pair!")
        else:
            # Mid-lesson -> resume at the same lesson + step
            if saved_lesson in lessons:
                default_idx = lessons.index(saved_lesson)
                resume_step = max(1, min(8, saved_step))
                resume_msg  = f"⏯ Resume {cfg['lesson_word']} {saved_lesson} at Step {resume_step}"
    # Apply a pending "jump to recommended lesson" click from the banner below
    # (one-shot: popped so it doesn't stick past this render).
    _jump_lid = st.session_state.pop("_jump_recommended_lid", None)
    if _jump_lid in lessons:
        default_idx = lessons.index(_jump_lid)
        resume_step = 1

    # ── Placement-quiz / mastery-based recommendation (CLAUDE.md item 3) ───
    # Shown alongside whatever the resume pointer picked above — NOT a silent
    # override — because a learner already mid-lesson shouldn't be yanked
    # elsewhere without asking. Runs regardless of whether `progress` exists,
    # so the quiz still has a visible, clickable effect even for a returning
    # user who already has some resume history (e.g. from an earlier lesson
    # started at a different level than the quiz estimated) — previously the
    # recommendation only ever applied when there was NO resume pointer at
    # all, which is why it silently did nothing here (2026-08-21, reported by
    # Natalia: quiz said A2, Grammar still opened at lesson 1).
    if user_id and _recommender.has_signal(user_id, target, cfg["lang_suffix"]):
        try:
            top = _recommender.get_next(user_id, target, module=cfg["lang_suffix"], limit=1)
        except Exception as e:
            st.caption(f"⚠️ Recommendation unavailable: {e}")
            top = None
        if top:
            rec_lid = _recommender.parse_unit_id(top[0]["unit_id"])["lesson_id"]
            if rec_lid in lessons and rec_lid != lessons[default_idx]:
                lvl = top[0].get("level") or ""
                c_rec, c_btn = st.columns([5, 2])
                with c_rec:
                    st.info(
                        f"💡 Based on your placement quiz / activity, "
                        f"{cfg['lesson_word']} {rec_lid} ({lvl}) might fit you better."
                    )
                with c_btn:
                    st.markdown("<div style='margin-top:1.6rem'></div>", unsafe_allow_html=True)
                    if st.button(f"Jump to {rec_lid} →", use_container_width=True,
                                 key=f"jump_btn_{cfg['lang_suffix']}"):
                        st.session_state["_jump_recommended_lid"] = rec_lid
                        st.rerun()

    # Build topics map: either from the workbook (grammar), a topic loader
    # (phrasebook/Word Bank), or straight from df (vocab/CEFR-J — a lesson is
    # 10 unrelated words at one CEFR level, no real theme to name it by, so
    # the label previews the lesson's own first few headwords instead of a
    # bare "Vocabulary 3" — lets a learner see at a glance what's inside
    # before opening it, closer to what a real topic name gave Word
    # Bank/Grammar. CLAUDE.md 2026-08-22: vocab is CEFR-J for every
    # target_lang now, so this branch is unconditional on module=="vocab",
    # not just target=="English". The CEFR band itself is added separately
    # by level_map below, so it isn't repeated here.)
    if cfg["topics"] == "from_df":
        # Grammar: optional topic_en / topic_uk columns in the workbook
        topics_map = get_grammar_topics(df, native_lang=native)
    elif module == "vocab":
        _cefrj_preview = (
            df.sort_values(["lesson_id", "phrase_id"])
              .groupby("lesson_id")["headword"]
              .apply(lambda s: ", ".join(s.head(3)))
        )
        topics_map = {int(lid): words for lid, words in _cefrj_preview.items()}
    elif cfg["topics"]:
        # Phrasebook/Word Bank: topic loader that takes the db path (index-only, fast)
        topics_map = cfg["topics"](str(db_path))
    else:
        topics_map = None

    # ── Grammar / Reading / Phrasebook / CEFR-J Vocabulary: flat wave nav ──
    # Vocabulary's old hierarchical Category→Topic nav (_render_vocab_nav)
    # only applied to Word Bank content, which CEFR-J has fully replaced for
    # every target_lang (CLAUDE.md 2026-08-22) -- CEFR-J has no thematic
    # categories to browse by (just a CEFR level), so it always uses the
    # flat wave nav below instead, same as grammar/reading; level_map gives
    # it the "· A1" annotation those already get (CLAUDE.md, 2026-08-21).
    # Level annotation on lesson names (e.g. "Lesson 42 · A2") so the CEFR
    # boundary is visible directly in the picker, not just in the recommendation
    # banner above (CLAUDE.md item 3 follow-up, 2026-08-21).
    try:
        level_map = _recommender.lesson_levels(cfg["lang_suffix"])
    except Exception:
        level_map = None
    _render_flat_wave_nav(
        df=df, cfg=cfg, lang_pair=lang_pair,
        native=native, target=target, user_id=user_id,
        lessons=lessons, default_idx=default_idx,
        resume_step=resume_step, resume_msg=resume_msg,
        progress=progress, counts_by_lid=counts_by_lid,
        topics_map=topics_map, level_map=level_map,
    )



# ═══════════════════════════════════════════════════════════════════════════
# Step 8 — Creative Generation (structure + semantic analysis)
# ═══════════════════════════════════════════════════════════════════════════
def step8(session: LessonSession, tts_lang, wh_lang):
    session.start_step(8)
    native_lang = session.state.native_lang

    # Step 8 description depends on practice module
    module = _current_module()
    if module == "vocab":
        title = "Compose Your Own Examples"
        desc  = ("Create your own sentences using the new words and phrases "
                 "from this lesson. The system will check grammar.")
    else:
        title = "Grammar Check — Create Your Own Phrases"
        desc  = "Say or type phrases in the target language. The system will correct grammar errors."

    step_hdr(8, total=8, show_image=True)

    phrases = session.phrases()

    # All languages now supported via Gemini (was previously limited to en/es/ko)
    gec_lang = wh_lang or "en"

    # Reference table
    with st.expander("📚 Lesson phrases for reference", expanded=False):
        phrase_table(phrases, show_native=True, show_target=True)

    st.markdown("---")
    n_phrases = st.slider("How many phrases to create?", 1, 5, 3, key="s8_n")

    input_mode = st.radio("Input method", ["🎙️ Voice", "⌨️ Text"],
                          horizontal=True, key="s8_mode")

    results = st.session_state.get("s8_results", [])

    # ── Voice input ───────────────────────────────────────────────────────
    if input_mode == "🎙️ Voice":
        st.markdown(f"Record yourself saying **{n_phrases} original phrase(s)**.")
        audio = audio_input("s8_voice")

        if st.button("Submit & Check Grammar", type="primary",
                     use_container_width=True, key="s8_submit_voice"):
            if not audio:
                st.warning("Please record audio first.")
            elif not whisper_available():
                st.warning("Whisper not installed.")
            else:
                with st.spinner("Transcribing…"):
                    import re
                    raw        = transcribe_bytes(audio, language=wh_lang)
                    candidates = [s.strip() for s in re.split(r"[.!?]", raw)
                                  if len(s.strip()) > 3][:n_phrases]

                if not candidates:
                    st.warning(f"Could not detect phrases. Transcribed: `{raw}`")
                else:
                    try:
                        with st.spinner("Checking grammar…"):
                            results = [{"original": p, "correction": _gemini.correct_grammar(
                                           p, _gemini.lang_name(gec_lang), native_lang)}
                                       for p in candidates]
                        st.session_state["s8_results"] = results
                        session.score(raw, raw, step=8, phrase_id=0)
                    except _gemini.PaidFeatureRequired:
                        _show_upsell("s8_voice")

    # ── Text input ────────────────────────────────────────────────────────
    else:
        # Language-specific placeholder examples, just demonstrating the
        # expected input shape (one phrase per line) -- CLAUDE.md 2026-08-23:
        # these used to be deliberately WRONG example sentences (e.g. "Yo
        # tiene un perro" instead of "tengo"), on the idea of showing what
        # a typical mistake looks like. Наталья flagged the real risk: a
        # placeholder sits in the box on every single Step 8 a student
        # opens, so an incorrect example risks being absorbed as correct
        # grammar through sheer repetition. Now grammatically correct.
        PLACEHOLDERS = {
            "en": "It's a big room.\nShe has a red pen.\nThey were happy.",
            "es": "Yo tengo un perro.\nElla es alta.\nNosotros vamos a la escuela.",
            "ko": "나는 학교에 가요.\n그는 책을 읽어요.\n우리는 친구예요.",
        }
        text_input = st.text_area(
            "Type your phrases (one per line):",
            placeholder=PLACEHOLDERS.get(gec_lang, ""),
            height=120, key="s8_text_input",
        )
        if st.button("Submit & Check Grammar", type="primary",
                     use_container_width=True, key="s8_submit_text"):
            lines = [l.strip() for l in text_input.strip().splitlines()
                     if l.strip()][:n_phrases]
            if not lines:
                st.warning("Please enter at least one phrase.")
            else:
                try:
                    with st.spinner("Checking grammar…"):
                        results = [{"original": p, "correction": _gemini.correct_grammar(
                                           p, _gemini.lang_name(gec_lang), native_lang)}
                                   for p in lines]
                    st.session_state["s8_results"] = results
                    session.score(text_input, text_input, step=8, phrase_id=0)
                except _gemini.PaidFeatureRequired:
                    _show_upsell("s8_text")

    # ── Results ───────────────────────────────────────────────────────────
    # Shows EVERY error found (not just one), in strikethrough/correct format,
    # and lets the student pick which ones to actually practice — reusing the
    # same interactive retry flow (_collect_error/_phase_error_review) the
    # other phases use, under the "step8" phase key (CLAUDE.md item 6, 2026-08-20).
    if results:
        reviewing = bool(_get_errors("step8")) or st.session_state.get("errors_step8_review_done")

        if not reviewing:
            st.markdown("---")
            st.markdown(f"### {i18n.get(native_lang, 'step8_errors_title')}")

            any_errors = False
            for i, item in enumerate(results):
                orig   = item["original"]
                errors = item["correction"].get("errors", [])
                st.markdown(f"**You:** {orig}")
                if not errors:
                    st.success("✓")
                else:
                    any_errors = True
                    for j, err in enumerate(errors):
                        col_chk, col_txt = st.columns([0.4, 5])
                        with col_chk:
                            st.checkbox("", value=True, key=f"s8_sel_{i}_{j}",
                                        label_visibility="collapsed")
                        with col_txt:
                            st.markdown(f"~~{err['original']}~~ → **{err['fixed']}**")
                            if err.get("explanation"):
                                st.caption(err["explanation"])

            if not any_errors:
                st.success(i18n.get(native_lang, "step8_no_errors"))
                show_character("ai_bot", "on_lesson_complete")
            else:
                if st.button(i18n.get(native_lang, "practice_selected_btn"),
                             type="primary", key="s8_practice_selected"):
                    for i, item in enumerate(results):
                        for j, err in enumerate(item["correction"].get("errors", [])):
                            if st.session_state.get(f"s8_sel_{i}_{j}", False):
                                _collect_error(
                                    err["original"], err["fixed"],
                                    err.get("explanation", ""), "step8",
                                    native_prompt=err.get("native_prompt", ""),
                                )
                    st.rerun()
                show_character("ai_bot", "feedback", score=70, corrections=sum(
                    len(it["correction"].get("errors", [])) for it in results
                ))
        else:
            st.markdown("---")
            _phase_error_review("step8", wh_lang, _gemini.lang_name(gec_lang), native_lang)

    # ── Navigation ────────────────────────────────────────────────────────
    st.markdown("---")
    attempted = bool(st.session_state.get("s8_results"))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Try again", use_container_width=True, key="s8_retry"):
            for k in list(st.session_state):
                if k.startswith("s8_sel_"):
                    del st.session_state[k]
            st.session_state.pop("s8_results", None)
            _clear_phase_errors("step8")
            st.rerun()
    with c2:
        if st.button("Complete Lesson ✓", type="primary",
                     use_container_width=True, key="s8_complete",
                     disabled=not attempted,
                     help=None if attempted else _try_first_msg(session)):
            st.session_state.pop("s8_results", None)
            return True
    if not attempted:
        _lock_hint(session)
    return False

# ═══════════════════════════════════════════════════════════════════════════
# State helpers
# ═══════════════════════════════════════════════════════════════════════════
def _clear_lesson():
    for k in list(st.session_state):
        if k.startswith(("s1_","s2_","s3_","s4_","s5_","s6_","s7_","s8_","up_",
                          "warmup_","p3_","p4_","errors_")):
            del st.session_state[k]

def _clear_all():
    _keep = {k: st.session_state[k] for k in
             ("launcher_user", "launcher_native", "launcher_target")
             if k in st.session_state}
    _curriculum = st.session_state.get("curriculum_mode", False)
    for k in list(st.session_state):
        del st.session_state[k]
    st.session_state.update(_keep)
    if _curriculum:
        st.session_state["active_module"] = "path"
        st.session_state["curriculum_mode"] = True
        st.session_state["curriculum_advance_pending"] = True
        st.query_params["module"] = "path"
    else:
        st.query_params.clear()


def _show_upsell(key: str) -> None:
    """Rendered wherever a free-tier user hits a paid-only Gemini call
    (engine.gemini.PaidFeatureRequired) — see engine/gemini.py's @_require_paid."""
    st.warning("⭐ This is a Premium feature — live AI generation isn't included in the free plan.")
    if st.button("⭐ Go to Upgrade", key=f"upsell_{key}"):
        st.session_state["_show_launcher"] = True
        st.rerun()


def _save_step_progress(sess: LessonSession, step: int):
    """Persist (lesson_id, step) so the user can resume right here next time.
    Saves at most once per (lesson_id, step) per session to avoid spamming the DB."""
    if not sess.state.unit_id:
        return
    key = (sess.state.lesson_id, step)
    if st.session_state.get("_last_saved_progress") == key:
        return
    try:
        module = sess.state.unit_id.split(":", 1)[0]
        _recommender.save_pointer(
            user_id     = sess.state.user_id,
            target_lang = sess.state.target_lang,
            module      = module,
            unit_id     = sess.state.unit_id,
            step        = int(step),
        )
        st.session_state["_last_saved_progress"] = key
    except Exception as e:
        print(f"[app] save_progress error: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
def _inject_css():
    st.markdown("""
<style>
/* Fonts loaded by app.py via _inject_mova_css — no extra @import needed */
html,body,[class*="css"]{font-family:'Plus Jakarta Sans','Inter',sans-serif;}
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

.step-header{background:var(--mova-card);border:1px solid var(--mova-line);border-radius:14px;padding:18px 26px;margin-bottom:18px;}
.step-num{font-family:'JetBrains Mono',monospace;color:var(--mova-indigo);font-size:.78rem;margin-bottom:4px;}
.step-title{color:var(--mova-ink);font-size:1.25rem;font-weight:600;}
.step-desc{color:var(--mova-ink-2);font-size:.88rem;margin-top:5px;}
.step-pills{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px;}
.pill{font-family:'JetBrains Mono',monospace;font-size:.7rem;padding:3px 9px;border-radius:20px;background:var(--mova-card);color:var(--mova-ink-3);border:1px solid var(--mova-line);}
.pill-active{background:var(--mova-indigo-soft);color:var(--mova-indigo);border-color:var(--mova-indigo);}
.pill-done{background:var(--mova-mint-soft);color:var(--mova-mint);border-color:var(--mova-mint);}

.ptable{background:var(--mova-card);border:1px solid var(--mova-line-2);border-radius:12px;overflow:hidden;margin:10px 0;}
.prow{display:flex;align-items:center;padding:11px 18px;border-bottom:1px solid var(--mova-line);gap:14px;}
.prow:last-child{border-bottom:none;}
.prow:hover{background:var(--mova-surface-3);}
.pnum{font-family:'JetBrains Mono',monospace;color:var(--mova-indigo);font-size:.78rem;min-width:26px;}
.pnat{color:var(--mova-ink);flex:1;font-size:.98rem;}
.ptgt{color:var(--mova-ink);flex:1;font-size:.98rem;font-weight:500;}
.phide{color:var(--mova-ink-4);flex:1;font-style:italic;font-size:.85rem;}
.spass{background:var(--mova-mint-soft);color:var(--mova-mint);border-radius:5px;padding:2px 9px;font-size:.8rem;font-family:'JetBrains Mono',monospace;}
.sfail{background:var(--mova-coral-soft);color:var(--mova-coral-ink);border-radius:5px;padding:2px 9px;font-size:.8rem;font-family:'JetBrains Mono',monospace;}

/* Color-coded step type — left border tells the user what kind of step it is */
.step-header.step-type-reading     { border-left: 4px solid var(--mova-indigo); }
.step-header.step-type-listening   { border-left: 4px solid #8050b0; }
.step-header.step-type-matching    { border-left: 4px solid #40a0a0; }
.step-header.step-type-translation { border-left: 4px solid #40a060; }
.step-header.step-type-composing   { border-left: 4px solid #c06080; }

/* Big icon next to the step title */
.step-icon-row { display:flex; align-items:center; gap:16px; margin-top:6px; }
.step-icon-big { font-size:2.4rem; line-height:1; flex-shrink:0; }

/* Subtle pulse so users notice the 'record yourself' control */
@keyframes pulse-soft {
    0%, 100% { box-shadow: 0 0 0 0 rgba(96,96,208,.35); }
    50%      { box-shadow: 0 0 0 10px rgba(96,96,208,0); }
}
.stApp [data-testid="stAudioInput"] button {
    animation: pulse-soft 2.6s ease-in-out infinite;
    border-radius: 50%;
}

/* Step 3 — make choice buttons readable (dark theme instead of light) */
.stApp .stButton > button[kind="secondary"]{
    background:var(--mova-card) !important;
    color:var(--mova-ink) !important;
    border:1px solid var(--mova-line) !important;
    font-weight:500 !important;
}
.stApp .stButton > button[kind="secondary"]:hover{
    background:var(--mova-indigo-soft) !important;
    border-color:var(--mova-indigo) !important;
    color:var(--mova-ink) !important;
}

.timer{font-family:'JetBrains Mono',monospace;font-size:2.4rem;color:var(--mova-indigo);text-align:center;padding:14px;background:var(--mova-card);border-radius:12px;border:1px solid var(--mova-line);margin:10px 0;}
.prow-active{background:var(--mova-indigo-soft) !important;border-left:3px solid var(--mova-indigo);}
.prow-active .pnat{color:var(--mova-ink) !important;}
.prow-active .ptgt{color:var(--mova-ink) !important;font-weight:600;}
.pill-required{background:var(--mova-amber-soft);color:var(--mova-amber-ink);border-color:var(--mova-amber);}
.progress-bar-wrap{background:var(--mova-card);border-radius:8px;height:8px;margin:6px 0;overflow:hidden;}
.progress-bar-fill{height:8px;border-radius:8px;background:linear-gradient(90deg, var(--mova-indigo), #6E66FF);transition:width .4s;}
.progress-info{display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:.72rem;color:var(--mova-ink-3);margin-bottom:2px;}
.cbanner{background:linear-gradient(135deg, var(--mova-mint-soft), var(--mova-indigo-soft));border:1px solid var(--mova-mint);border-radius:16px;padding:36px;text-align:center;}
audio{width:100%;border-radius:8px;margin:4px 0;}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# Phase helpers — error collection & interactive review
# ═══════════════════════════════════════════════════════════════════════════

def _init_errors(phase_key: str) -> None:
    if f"errors_{phase_key}" not in st.session_state:
        st.session_state[f"errors_{phase_key}"] = []


def _collect_error(
    original: str, corrected: str, explanation: str,
    phase_key: str, native_prompt: str = "",
) -> None:
    """Store one error silently during a phase for deferred review."""
    _init_errors(phase_key)
    if original.strip() != corrected.strip():
        st.session_state[f"errors_{phase_key}"].append({
            "original":      original,
            "corrected":     corrected,
            "explanation":   explanation,
            "native_prompt": native_prompt or corrected,
        })


def _get_errors(phase_key: str) -> list:
    return st.session_state.get(f"errors_{phase_key}", [])


def _clear_phase_errors(phase_key: str) -> None:
    for suffix in ("", "_review_idx", "_review_done"):
        st.session_state.pop(f"errors_{phase_key}{suffix}", None)


def _error_drill_step(
    err: dict, idx: int, total: int, phase_key: str,
    wh_lang: str, target_lang: str, native_lang: str,
) -> bool:
    """
    Per-error practice step used by _phase_error_review for every phase
    (warmup, practice, expression, step8): instead of asking the student to
    reproduce the ONE corrected sentence verbatim, ask them to write/say
    2-3 NEW phrases using the same word/phrase/structure that was wrong,
    then grammar-check whatever they produced as a whole (reusing
    engine.gemini.correct_grammar and the same strikethrough render Step 8
    already uses, rather than the single-sentence check_practice_answer).
    Returns True once the student has checked their phrases and clicked
    "Next" for this error (advances the caller's review_key index).
    """
    st.markdown("---")
    st.markdown(f"### {i18n.get(native_lang, 'error_drill_title')} — {idx + 1} / {total}")
    st.info(
        f"**{err['corrected']}**\n\n"
        + (f"{err['explanation']}\n\n" if err.get("explanation") else "")
        + i18n.get(native_lang, "error_drill_instruction")
    )

    _opt_text  = i18n.get(native_lang, "text_opt")
    _opt_voice = i18n.get(native_lang, "voice_opt")
    mode = st.radio(
        i18n.get(native_lang, "answer_method"), [_opt_text, _opt_voice],
        horizontal=True, key=f"errdrill_mode_{phase_key}_{idx}",
    )

    student_text: str | None = None
    submitted = False

    if mode == _opt_text:
        student_text = st.text_area(
            i18n.get(native_lang, "error_drill_input_label"),
            key=f"errdrill_text_{phase_key}_{idx}", height=90,
        )
        submitted = st.button(
            i18n.get(native_lang, "check_btn"), key=f"errdrill_submit_{phase_key}_{idx}"
        )
    else:
        audio = audio_input(f"errdrill_{phase_key}_{idx}")
        submitted = bool(audio) and st.button(
            i18n.get(native_lang, "check_btn"), key=f"errdrill_submit_{phase_key}_{idx}"
        )
        if submitted and audio:
            with st.spinner("Transcribing…"):
                student_text = transcribe_bytes(audio, language=wh_lang)
            st.markdown(f"**{student_text}**")

    result_key = f"errdrill_result_{phase_key}_{idx}"

    if submitted and student_text and student_text.strip():
        try:
            with st.spinner("…"):
                st.session_state[result_key] = _gemini.correct_grammar(
                    student_text, target_lang, native_lang
                )
        except _gemini.PaidFeatureRequired:
            _show_upsell(f"errdrill_check_{phase_key}_{idx}")
            return False

    if result_key in st.session_state:
        found = st.session_state[result_key].get("errors", [])
        if not found:
            st.success(i18n.get(native_lang, "step8_no_errors"))
        else:
            for e in found:
                st.markdown(f"~~{e['original']}~~ → **{e['fixed']}**")
                if e.get("explanation"):
                    st.caption(e["explanation"])
        if st.button(i18n.get(native_lang, "next_btn"), type="primary",
                     key=f"errdrill_next_{phase_key}_{idx}"):
            st.session_state.pop(result_key, None)
            return True

    return False


def _phase_error_review(
    phase_key: str, wh_lang: str, target_lang: str, native_lang: str
) -> bool:
    """
    Interactive correction round shown at the END of each phase.

    Step 1: Shows ALL errors with explanations (overview).
    Step 2: Asks student to write/say 2-3 NEW phrases using the same
            word/phrase/structure that was wrong (_error_drill_step),
            grammar-checked as a whole rather than reproducing one sentence.

    Returns True when all errors have been worked through (or there are none).
    """
    errors = _get_errors(phase_key)
    if not errors:
        return True

    done_key     = f"errors_{phase_key}_review_done"
    review_key   = f"errors_{phase_key}_review_idx"
    overview_key = f"errors_{phase_key}_overview_done"

    if st.session_state.get(done_key):
        return True

    # ── Step 1: overview of all errors ──────────────────────────────────────
    if not st.session_state.get(overview_key):
        st.markdown("---")
        st.markdown(f"### {i18n.get(native_lang, 'error_review_title')}")
        for err in errors:
            original  = err.get("original",  err.get("phrase", ""))
            corrected = err.get("corrected", err.get("fixed", ""))
            expl      = err.get("explanation", "")
            st.error(f"❌ **{original}** → ✅ **{corrected}**")
            if expl:
                st.caption(expl)
        if st.button(i18n.get(native_lang, "error_review_start"), type="primary", key=f"rev_overview_next_{phase_key}"):
            st.session_state[overview_key] = True
            st.rerun()
        return False

    idx = st.session_state.get(review_key, 0)
    if idx >= len(errors):
        st.session_state[done_key] = True
        st.session_state.pop(overview_key, None)
        _clear_phase_errors(phase_key)
        return True

    err   = errors[idx]
    total = len(errors)

    if _error_drill_step(err, idx, total, phase_key, wh_lang, target_lang, native_lang):
        st.session_state[review_key] = idx + 1
        st.rerun()
    return False


# ── CEFR level for the current lesson ─────────────────────────────────────
def _lesson_level(session: LessonSession) -> str:
    """
    Grammar lessons carry a real `difficulty` column (imlls_database's
    "phrases" sheet, 1-4) — mapped via engine.recommender.DIFFICULTY_TO_CEFR,
    the same mapping scripts/seed_content_units.py uses to tag content_units,
    so this now agrees with what the recommender already knows about a
    lesson's level. Fixed 2026-08-21 — this used to be crude lesson_id
    thresholds (<=30/<=70/else) capped at B1, which disagreed with it (e.g.
    lesson 139 is really B2, this returned "B1" — one level too low).

    Vocabulary/CEFR-J lessons (engine.cefr_j_vocab_loader) carry the real
    CEFR level directly in `topic` ("A1".."C2" — that IS the lesson's
    category there, see the loader's docstring) — checked before the
    lesson_id fallback below. Fixed 2026-08-22: without this, every CEFR-J
    lesson fell through to the old lesson_id heuristic, which was
    calibrated for Word Bank's 1-806 gid range — CEFR-J's are offset by
    +100000, so `lesson_id <= 70` is never true and EVERY CEFR-J lesson
    silently came out "B1" regardless of its real level (found live —
    an A1 lesson's bilingual-warmup checkbox wasn't checked by default).

    Phrasebook / Word Bank Vocabulary lessons have no CEFR level baked into
    the loaded phrases themselves (`topic` there is a real theme/sheet name,
    e.g. "Greetings, Basics & Courtesy", never a CEFR code) — but
    scripts/seed_content_units.py already tags each one from
    data/vocab_tags_template.csv into content_units.level (same source the
    lesson-picker's "· A1" annotation uses, engine.recommender.lesson_levels).
    Fixed 2026-08-22: look that up by unit_id before falling back to the
    lesson_id heuristic below, so Phrasebook lessons (previously always
    capped at B1 regardless of real level — the crude fallback was
    calibrated for the old Word Bank gid range, and Phrasebook never had
    real level data of its own) get their real tagged level like every
    other module. Untagged lessons (level IS NULL) and a missing/unavailable
    DB still land on the lesson_id heuristic, same as before.
    """
    phrases = session.phrases()
    if phrases and phrases[0].get("difficulty") is not None:
        try:
            return _recommender.DIFFICULTY_TO_CEFR.get(int(phrases[0]["difficulty"]), "A1")
        except (TypeError, ValueError):
            pass

    if phrases and phrases[0].get("topic") in _recommender.CEFR_RANK:
        return phrases[0]["topic"]

    if session.state.unit_id:
        try:
            from engine import db
            row = db.fetch_one(
                "SELECT level FROM content_units WHERE unit_id = :uid AND level IS NOT NULL",
                {"uid": session.state.unit_id},
            )
            if row:
                return row["level"]
        except Exception:
            pass

    lesson_id = session.state.lesson_id
    if lesson_id <= 30:
        return "A1"
    if lesson_id <= 70:
        return "A2"
    return "B1"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 — Розминка / Warmup
# ═══════════════════════════════════════════════════════════════════════════

def phase1_warmup(session: LessonSession, tts_lang: str, wh_lang: str) -> bool:
    """
    Gemini generates a proactive question in the target language.
    Student answers via audio or text.
    Errors collected silently; reviewed before advancing.
    Returns True when the phase is complete.
    """
    native_lang = session.state.native_lang
    target_lang = session.state.target_lang
    level       = _lesson_level(session)

    _init_errors("warmup")

    col_title, col_skip = st.columns([5, 1])
    with col_title:
        st.markdown(f"## {i18n.get(native_lang, 'warmup_title')}")
        st.caption(i18n.get(native_lang, "warmup_strategy"))
    with col_skip:
        if st.button(i18n.get(native_lang, "skip"), key="warmup_skip"):
            st.session_state.pop("warmup_q", None)
            st.session_state.pop("warmup_done", None)
            return True

    # Bilingual display defaults on for A1 (CLAUDE.md item 2, 2026-08-20) but
    # stays a toggle, not hardcoded — regenerating the question if it changes.
    if "warmup_bilingual" not in st.session_state:
        st.session_state["warmup_bilingual"] = (level == "A1")
    bilingual = st.checkbox(
        i18n.get(native_lang, "warmup_bilingual_toggle"),
        key="warmup_bilingual",
        disabled="warmup_q" in st.session_state,
    )

    # Generate question once per phase entry
    if "warmup_q" not in st.session_state:
        try:
            with st.spinner("Generating warmup question…"):
                st.session_state["warmup_q"] = _gemini.warmup_question(
                    level, target_lang, native_lang, bilingual=bilingual,
                )
        except _gemini.PaidFeatureRequired:
            _show_upsell("warmup_q")
            return False

    _wq = st.session_state["warmup_q"]
    st.markdown(f"### 💬 {_wq['target']}")
    if _wq.get("native"):
        st.caption(f"🌐 {_wq['native']}")

    # ── Error review + drill (same flow as practice/expression/step8) ──────
    if st.session_state.get("warmup_done"):
        if not _get_errors("warmup"):
            st.success(i18n.get(native_lang, "no_errors"))
        if _phase_error_review("warmup", wh_lang, target_lang, native_lang):
            if st.button(i18n.get(native_lang, "next"), type="primary", key="warmup_next"):
                st.session_state.pop("warmup_q", None)
                st.session_state.pop("warmup_done", None)
                return True
        return False

    # ── Input ─────────────────────────────────────────────────────────────
    _voice_opt = i18n.get(native_lang, "voice_opt")
    _text_opt  = i18n.get(native_lang, "text_opt")
    mode = st.radio(
        i18n.get(native_lang, "answer_method"), [_voice_opt, _text_opt],
        horizontal=True, key="warmup_mode",
    )
    answer: str | None = None

    if mode == _voice_opt:
        audio = audio_input("warmup")
        if audio and st.button("Submit", type="primary", key="warmup_submit"):
            with st.spinner("Transcribing…"):
                answer = transcribe_bytes(audio, language=wh_lang)
            if answer:
                st.markdown(f"**You said:** {answer}")
    else:
        answer_text = st.text_input(
            i18n.get(native_lang, "answer_label"), key="warmup_text_input"
        )
        if st.button("Submit", type="primary", key="warmup_text_submit"):
            answer = answer_text

    if answer:
        try:
            with st.spinner("Evaluating…"):
                result = _gemini.evaluate_warmup(
                    answer, st.session_state["warmup_q"]["target"],
                    target_lang, level, native_lang,
                )
        except _gemini.PaidFeatureRequired:
            _show_upsell("warmup_eval")
            return False
        if result.get("feedback"):
            st.info(result["feedback"])
        for err in result.get("errors", []):
            _collect_error(
                err["original"], err["corrected"],
                err.get("explanation", ""), "warmup",
                native_prompt=err.get("native_prompt", ""),
            )
        st.session_state["warmup_done"] = True
        st.rerun()

    return False


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — Практика / Practice  (Gemini-generated tests)
# ═══════════════════════════════════════════════════════════════════════════

def _extra_practice_phrases(
    session: LessonSession, module: str, target_lang: str, native_lang: str, n: int = 4,
) -> list[dict]:
    """
    Pull a few phrases from the user's weakest / most-overdue topics (via
    engine.recommender), beyond the current lesson — so practice tests aren't
    limited to session.phrases() alone (CLAUDE.md item 5, 2026-08-20).
    Best-effort: returns [] on any lookup failure rather than blocking the test.
    """
    if module not in ("grammar", "vocab"):
        return []
    try:
        cfg = _module_config(module)
        if cfg["load"] is None:
            return []
        candidates = _recommender.get_next(
            session.state.user_id, target_lang, module=module, limit=6,
        )
        df_all = cfg["load"](str(cfg["db_path"]), native_lang, target_lang)
        pool: list[dict] = []
        for cand in candidates:
            if cand["unit_id"] == session.state.unit_id:
                continue
            lesson_id  = _recommender.parse_unit_id(cand["unit_id"])["lesson_id"]
            lesson_df  = cfg["get_lesson"](df_all, lesson_id)
            pool.extend(lesson_df.to_dict("records"))
        random.shuffle(pool)
        return pool[:n]
    except Exception:
        return []


def phase3_practice(session: LessonSession, tts_lang: str, wh_lang: str) -> bool:
    """
    Gemini generates a short test (fill-in-blank / multiple choice / translation).
    Errors collected; reviewed before advancing.
    Returns True when the phase is complete.
    """
    native_lang = session.state.native_lang
    target_lang = session.state.target_lang
    topic       = getattr(session.state, "topic", "daily life") or "daily life"
    level       = _lesson_level(session)
    module      = _current_module()
    # construction_drill: Grammar-only (the construction/pattern concept is
    # specific to Grammar lessons), but works for any target language now —
    # English uses engine.cefr_wordlist's strict CEFR+POS word list, other
    # languages fall back to a plain "use simple vocabulary" instruction
    # (CLAUDE.md, 2026-08-22 — no open CEFR+POS list exists for uk/es/ko).
    _drill_available = module == "grammar"

    _init_errors("practice")

    st.markdown(f"## {i18n.get(native_lang, 'practice_title')}")

    # ── Error review (shown after test is checked) ────────────────────────
    if st.session_state.get("p3_checked"):
        for i, res in enumerate(st.session_state.get("p3_results", [])):
            icon = "✅" if res["correct"] else "❌"
            st.markdown(f"{icon} **{i + 1}.** {res.get('feedback', '')}")

        if _phase_error_review("practice", wh_lang, target_lang, native_lang):
            if st.button(
                i18n.get(native_lang, "next"), type="primary", key="p3_next"
            ):
                for k in ("p3_test", "p3_answers", "p3_results", "p3_checked"):
                    st.session_state.pop(k, None)
                return True
        return False

    # ── Test type picker ──────────────────────────────────────────────────
    # Order (and therefore the selectbox's default): multiple choice first,
    # then fill-in-the-blank, then translation (CLAUDE.md, 2026-08-23 —
    # Наталья's requested order).
    _test_types = ["multiple_choice", "fill_in_blank", "translation"]
    # Grammar-book sentence transformation (active/passive, statement/
    # question, reported speech...) only makes sense as a GRAMMAR drill —
    # works in any target language, unlike construction_drill which needs
    # cefr_wordlist's English-only pool (CLAUDE.md, 2026-08-22).
    if module == "grammar":
        _test_types.append("sentence_transformation")
    if _drill_available:
        _test_types.append("construction_drill")
    test_type = st.selectbox(
        i18n.get(native_lang, "test_type_label"),
        _test_types,
        format_func={
            "fill_in_blank":           i18n.get(native_lang, "fill_in_blank"),
            "multiple_choice":         i18n.get(native_lang, "multiple_choice"),
            "translation":             i18n.get(native_lang, "translation_type"),
            "sentence_transformation": i18n.get(native_lang, "sentence_transformation"),
            "construction_drill":      i18n.get(native_lang, "construction_drill"),
        }.get,
        key="p3_type",
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        generate_clicked = st.button(i18n.get(native_lang, "generate_exercise"), type="primary", key="p3_gen")
    with col2:
        regen_clicked = st.button(i18n.get(native_lang, "new_exercise"), key="p3_regen",
                                  disabled="p3_test" not in st.session_state)

    if generate_clicked or regen_clicked:
        try:
            with st.spinner(i18n.get(native_lang, "generating_ex")):
                if test_type == "construction_drill":
                    # Fresh sentences built from the lesson's own construction +
                    # level-appropriate vocabulary (engine.cefr_wordlist for
                    # English, a plain instruction for other languages — CLAUDE.md
                    # 2026-08-21/22), instead of imlls_database's fixed 7-8
                    # phrases. Reshaped into the same {question, answer, options}
                    # item shape generate_practice_test produces, as a translation
                    # exercise (native shown, target expected) — so the existing
                    # render/check loop below needs no changes for this mode.
                    drill = _gemini.generate_lesson_construction_drill(
                        session.state.lesson_id, topic,
                        [p["target"] for p in session.phrases()],
                        level, native_lang, target_lang,
                    )
                    st.session_state["p3_test"] = {
                        "instructions": i18n.get(native_lang, "translation_type"),
                        "items": [
                            {"question": it["native"], "answer": it["target"], "options": []}
                            for it in drill.get("items", [])
                        ],
                    }
                else:
                    combined_phrases = session.phrases() + _extra_practice_phrases(
                        session, module, target_lang, native_lang,
                    )
                    st.session_state["p3_test"] = _gemini.generate_practice_test(
                        level, topic, target_lang, native_lang, test_type,
                        phrases=combined_phrases, module=module,
                    )
                st.session_state["p3_answers"] = {}
                st.session_state["p3_checked"] = False
                st.session_state.pop("p3_results", None)
        except _gemini.PaidFeatureRequired:
            _show_upsell("p3_gen")
            return False

    if "p3_test" not in st.session_state:
        return False

    test = st.session_state["p3_test"]
    if test.get("instructions"):
        st.markdown(f"**{test['instructions']}**")

    # ── Render items ──────────────────────────────────────────────────────
    for i, item in enumerate(test.get("items", [])):
        st.markdown(f"**{i + 1}.** {item['question']}")
        if test_type == "multiple_choice" and item.get("options"):
            choice = st.radio(
                "", item["options"],
                key=f"p3_q{i}", label_visibility="collapsed",
            )
            st.session_state["p3_answers"][i] = choice
        else:
            ans = st.text_input(i18n.get(native_lang, "answer_label"), key=f"p3_q{i}")
            st.session_state["p3_answers"][i] = ans

    # ── Check button ──────────────────────────────────────────────────────
    if st.button(i18n.get(native_lang, "check_btn"), type="primary", key="p3_check"):
        results = []
        try:
            for i, item in enumerate(test.get("items", [])):
                student_ans = st.session_state["p3_answers"].get(i, "")
                if test_type == "multiple_choice":
                    passed = evaluate(student_ans, item["answer"])["passed"]
                    res = {
                        "correct": passed,
                        "feedback": i18n.get(native_lang, "correct") if passed
                                    else f"{i18n.get(native_lang, 'try_again')} {item['answer']}",
                    }
                else:
                    res = _gemini.check_practice_answer(
                        item["question"], student_ans, item["answer"],
                        target_lang, native_lang,
                    )
                results.append(res)
                if not res["correct"]:
                    _collect_error(
                        student_ans, item["answer"],
                        res.get("feedback", ""), "practice",
                        native_prompt=item["question"],
                    )
        except _gemini.PaidFeatureRequired:
            _show_upsell("p3_check")
            return False
        st.session_state["p3_results"] = results
        st.session_state["p3_checked"] = True
        st.rerun()

    return False


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — Висловлювання / Expression

def phase4_expression(session: LessonSession, tts_lang: str, wh_lang: str) -> bool:
    native_lang = session.state.native_lang
    target_lang = session.state.target_lang
    topic       = getattr(session.state, "topic", "daily life") or "daily life"
    level       = _lesson_level(session)

    _init_errors("expression")

    st.markdown(f"## {i18n.get(native_lang, 'speaking_title')}")
    st.info(i18n.get(native_lang, "speaking_strategy"))

    # Bilingual display defaults on for A1, same convention as warmup
    # (CLAUDE.md item 2, 2026-08-20) — stays a toggle, not hardcoded.
    if "p4_bilingual" not in st.session_state:
        st.session_state["p4_bilingual"] = (level == "A1")
    st.checkbox(
        i18n.get(native_lang, "warmup_bilingual_toggle"),
        key="p4_bilingual",
        disabled="p4_task" in st.session_state,
    )

    def _gen_p4_task() -> bool:
        seed = [p["target"] for p in session.phrases()]
        random.shuffle(seed)
        try:
            with st.spinner("Generating speaking task..."):
                st.session_state["p4_task"] = _gemini.generate_open_question(
                    topic, seed, level, target_lang, native_lang,
                    bilingual=st.session_state.get("p4_bilingual", False),
                )
                st.session_state["p4_chat_history"] = []
                st.session_state["p4_submitted"]    = False
            return True
        except _gemini.PaidFeatureRequired:
            _show_upsell("p4_gen")
            return False

    if "p4_task" not in st.session_state:
        col_p4a, col_p4b = st.columns([3, 1])
        with col_p4a:
            if st.button(i18n.get(native_lang, "generate_task"), type="primary", key="p4_gen"):
                if _gen_p4_task():
                    st.rerun()
        return False

    col_p4task, col_p4rnw = st.columns([5, 1])
    with col_p4rnw:
        if not st.session_state.get("p4_submitted"):
            if st.button(i18n.get(native_lang, "new_btn"), key="p4_regen"):
                for _k in ("p4_task","p4_chat_history","p4_submitted","p4_answer"):
                    st.session_state.pop(_k, None)
                if _gen_p4_task():
                    st.rerun()
    _p4q = st.session_state["p4_task"]
    st.markdown(f"### 💭 {_p4q['target']}")
    if _p4q.get("native"):
        st.caption(f"🌐 {_p4q['native']}")
    st.markdown("---")

    # ── SOS & HELP — always visible ──────────────────────────────────────
    with st.expander(i18n.get(native_lang, "sos_label")):
        _h_text_opt = i18n.get(native_lang, "text_opt")
        _h_voice_opt = i18n.get(native_lang, "voice_opt")
        help_mode = st.radio(
            i18n.get(native_lang, "mode_label"), [_h_text_opt, _h_voice_opt],
            horizontal=True, key="p4_help_mode"
        )
        help_query: str | None = None
        if help_mode == _h_text_opt:
            help_query = st.text_input(
                i18n.get(native_lang, "how_to_say"), key="p4_help_text",
                placeholder=i18n.get(native_lang, "enter_phrase_hint"),
            )
            if st.button(i18n.get(native_lang, "translate_btn"), key="p4_help_submit") and help_query:
                try:
                    with st.spinner("..."):
                        hint = _gemini.translate_phrase(help_query, native_lang, target_lang)
                    st.session_state["p4_help_reply"] = hint
                except _gemini.PaidFeatureRequired:
                    _show_upsell("p4_help_text")
        else:
            audio_h = audio_input("p4_help")
            if audio_h:
                st.session_state["p4_help_audio"] = audio_h
            if st.button(i18n.get(native_lang, "translate_btn"), key="p4_help_submit_v"):
                saved = st.session_state.get("p4_help_audio")
                if saved:
                    # SOS: user speaks in native lang, not target lang
                    _LANG_NAME_TO_CODE = {
                        "english": "en", "ukrainian": "uk", "german": "de",
                        "spanish": "es", "korean": "ko", "french": "fr",
                        "japanese": "ja", "chinese": "zh", "portuguese": "pt",
                        "italian": "it", "polish": "pl", "russian": "ru",
                        "catalan": "ca", "dutch": "nl",
                    }
                    _native_stt = _LANG_NAME_TO_CODE.get(native_lang.lower(), "uk")
                    with st.spinner("..."):
                        help_query = transcribe_bytes(saved, language=_native_stt)
                    if help_query:
                        st.caption(f"{i18n.get(native_lang, 'you_asked')} {help_query}")
                        try:
                            with st.spinner("..."):
                                hint = _gemini.translate_phrase(help_query, native_lang, target_lang)
                            st.session_state["p4_help_reply"] = hint
                            st.session_state.pop("p4_help_audio", None)
                        except _gemini.PaidFeatureRequired:
                            _show_upsell("p4_help_voice")
                else:
                    st.warning(i18n.get(native_lang, "no_audio_warning"))
        if "p4_help_reply" in st.session_state:
            st.success(st.session_state["p4_help_reply"])

    if not st.session_state.get("p4_submitted"):
        _p4_text_opt  = i18n.get(native_lang, "text_opt")
        _p4_voice_opt = i18n.get(native_lang, "voice_opt")
        mode = st.radio(
            i18n.get(native_lang, "mode_label"), [_p4_text_opt, _p4_voice_opt],
            horizontal=True, key="p4_mode",
        )
        if mode == _p4_text_opt:
            answer_text = st.text_area(i18n.get(native_lang, "write_answer"), key="p4_text")
            if st.button("Submit & Chat with tutor", type="primary", key="p4_text_go"):
                if answer_text.strip():
                    st.session_state["p4_answer"] = answer_text.strip()
        else:
            audio = audio_input("p4_voice")
            if audio and st.button("Submit voice", type="primary", key="p4_voice_go"):
                with st.spinner("Transcribing..."):
                    transcribed = transcribe_bytes(audio, language=wh_lang)
                st.markdown(f"**You said:** {transcribed}")
                st.session_state["p4_answer"] = transcribed

        if "p4_answer" in st.session_state and not st.session_state.get("p4_submitted"):
            try:
                with st.spinner("Checking grammar..."):
                    correction = _gemini.correct_grammar(
                        st.session_state["p4_answer"], target_lang, native_lang
                    )
            except _gemini.PaidFeatureRequired:
                _show_upsell("p4_correct")
                return False
            for err in correction.get("errors", []):
                _collect_error(
                    err["original"], err["fixed"],
                    err.get("explanation", ""), "expression",
                    native_prompt=err.get("native_prompt", ""),
                )
            st.caption("Grammar checked - errors saved for review.")
            st.session_state["p4_submitted"] = True
            st.rerun()

    if st.session_state.get("p4_submitted"):
        st.markdown("### Chat with your tutor")
        st.caption("Continue in the target language. The tutor will gently correct you.")

        for msg in st.session_state.get("p4_chat_history", []):
            role = "You" if msg["role"] == "user" else "Tutor"
            st.markdown(f"**{role}:** {msg['parts'][0]}")

        _last_tutor = next(
            (m["parts"][0] for m in reversed(
                st.session_state.get("p4_chat_history", [])
            ) if m["role"] == "model"),
            st.session_state.get("p4_task", {}).get("target", ""),
        )
        user_input = st.chat_input("Your message...", key="p4_chat")
        if user_input:
            try:
                with st.spinner("Tutor is typing..."):
                    reply = _gemini.chat_with_tutor(
                        st.session_state["p4_chat_history"],
                        user_input, target_lang, level, native_lang,
                    )
                st.session_state["p4_chat_history"] += [
                    {"role": "user",  "parts": [user_input]},
                    {"role": "model", "parts": [reply]},
                ]
                st.rerun()
            except _gemini.PaidFeatureRequired:
                _show_upsell("p4_chat")

        st.markdown("---")
        if _phase_error_review("expression", wh_lang, target_lang, native_lang):
            if st.button("Finish lesson", type="primary", key="p4_finish"):
                for k in ("p4_task", "p4_answer", "p4_chat_history", "p4_submitted"):
                    st.session_state.pop(k, None)
                return True

    return False


# =============================================================================
# Phase 5 - Pidsumok / Summary
# =============================================================================

def phase5_video(session: LessonSession) -> bool:
    """
    Phase 5: curated YouTube channels for the student's target language and
    CEFR level. Reads data/youtube_channels.csv — no live API calls.

    CLAUDE.md 2026-08-23: previously showed 1-3 specific curated videos
    (data/youtube_links.csv, still intact and still readable via
    youtube_links.get_videos() -- just not called here anymore) matched to
    exactly this lesson's level. Наталья live-tested it and the same one
    video kept reappearing across every lesson at that level, which read as
    stale -- a channel LIST lets the student actually explore instead of
    hitting the same single clip every time. Returns True when the user
    clicks "До головного меню →".
    """
    state       = session.state
    level       = _lesson_level(session)
    target_lang = state.target_lang or st.session_state.get("launcher_target", "English")
    native_lang = st.session_state.get("launcher_native", "Ukrainian")

    st.markdown(f"## {i18n.get(native_lang, 'video_title')}")
    st.caption(
        f"{i18n.get(native_lang, 'level_label')}: **{level}** · "
        f"{i18n.get(native_lang, 'lang_label')}: **{target_lang}**"
    )

    # B2+ (CLAUDE.md 2026-08-22, Наталья's call): curated channel
    # recommendations only make sense up through B1 -- past that, real
    # native-speaker content (a show/movie/video the student actually wants
    # to watch) is the better practice than anything we could curate.
    beyond_curated = _recommender.CEFR_RANK.get(level, 0) >= _recommender.CEFR_RANK["B2"]
    channels = [] if beyond_curated else youtube_links.get_channels(target_lang)

    if beyond_curated:
        st.info(i18n.get(native_lang, "video_beyond_curated"))
    elif not channels:
        st.warning(i18n.get(native_lang, "video_not_found"))
    else:
        st.markdown(i18n.get(native_lang, "video_channels_intro"))
        for c in channels:
            st.markdown(f"- [{c['name']}]({c['url']})")

    st.markdown("---")
    if st.button(i18n.get(native_lang, "to_main_menu"), type="primary", key="p5_done"):
        return True
    return False


def phase5_summary(session: LessonSession) -> bool:
    st.markdown("## Pidsumok urok")
    st.success("Urok zavershenyi! Vsi pomylky vzhe opratsiuvano pislia kozhnoi fazy.")

    state     = session.state
    n_phrases = len(session.phrases())
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Urok", f"#{state.lesson_id}")
    with col2:
        st.metric("Fraz opratsiuvano", n_phrases)
    with col3:
        best = getattr(state, "best_score", None)
        if best is not None:
            st.metric("Naikrashchyi rezultat", f"{int(best * 100)}%")

    st.markdown("---")

    try:
        on_lesson_complete(state.user_id)
    except Exception:
        pass

    if st.button("Back to main menu", type="primary", key="p5_done"):
        return True
    return False


# =============================================================================

TOTAL_LESSONS = 173

STEPS = {1: step1, 2: step2, 3: step3, 4: step4, 5: step5, 6: step6, 7: step7, 8: step8}
# Steps that cannot be skipped
REQUIRED_STEPS = {1, 3, 6, 7}


# =============================================================================
# Adaptive session initialiser
# =============================================================================
def _init_adaptive_session(sess) -> None:
    """
    Initialise the step sequence for this lesson. Always the full 8-step
    sequence — the old per-session RandomForest step-skipping (engine/adaptive.py)
    was retired: it only kicked in after 25 interactions within a single
    lesson's local log (rarely reached in practice) and wasn't part of what
    Phase C's recommender was asked to solve (topic/level selection, not
    within-lesson step count). See CLAUDE.md decision #4.
    """
    if (st.session_state.get("_adaptive_lesson_id") == sess.state.lesson_id
            and "_adaptive_steps" in st.session_state):
        return

    st.session_state.update({
        "_adaptive_steps":     _FULL_SEQ.copy(),
        "_adaptive_idx":       0,
        "_adaptive_mode":      "cold_start",
        "_adaptive_lesson_id": sess.state.lesson_id,
    })
def main(module: str = "grammar"):
    """Entry point. `module` may be "grammar" or "vocab"."""
    # Remember the chosen module for downstream functions
    st.session_state["practice_module"] = module
    cfg = _module_config(module)
    _inject_css()

    with st.sidebar:
        # ── Gamification widget (streak / XP / level) ────────────────────────
        _gami_user = (st.session_state["session"].state.user_id
                      if "session" in st.session_state else
                      st.session_state.get("launcher_user", "student1"))
        sidebar_widget(_gami_user)

        # ── Module navigator ─────────────────────────────────────────────────
        _SIDEBAR_MODULES = [
            ("grammar",    "🗣️", "Grammar"),
            ("vocab",      "📖", "Vocabulary"),
            ("phrasebook", "💬", "Phrasebook"),
            ("reading",    "🔤", "Reading"),
            ("custom",     "📝", "My Phrases"),
        ]
        st.markdown(
            '<div style="font-size:.7rem;color:var(--mova-ink-3);'
            'text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">'
            'Module</div>',
            unsafe_allow_html=True,
        )
        for _mod_key, _mod_icon, _mod_name in _SIDEBAR_MODULES:
            _is_current = (module == _mod_key)
            if st.button(
                f"{_mod_icon} {_mod_name}",
                key=f"sb_mod_{_mod_key}",
                use_container_width=True,
                type="primary" if _is_current else "secondary",
                disabled=_is_current,
            ):
                _u = st.session_state.get("launcher_user", "student1")
                _n = st.session_state.get("launcher_native", "Ukrainian")
                _t = st.session_state.get("launcher_target", "English")
                for _k in list(st.session_state):
                    del st.session_state[_k]
                st.session_state["active_module"]   = _mod_key
                st.session_state["launcher_user"]   = _u
                st.session_state["launcher_native"] = _n
                st.session_state["launcher_target"] = _t
                st.query_params["module"] = _mod_key
                st.rerun()

        st.markdown("---")
        st.markdown(f"**{cfg['icon']} {cfg['label']}**")
        if "lesson_step" in st.session_state and "session" in st.session_state:
            sess  = st.session_state["session"]
            state = sess.state
            cur_step = st.session_state['lesson_step']
            try:
                if module == "custom":
                    # Custom: count this user's saved lessons for the pair
                    from engine.custom_store import list_user_lessons
                    cu_df = list_user_lessons(state.user_id,
                                              native_lang=state.native_lang,
                                              target_lang=state.target_lang)
                    total_lessons = max(len(cu_df), 1)
                else:
                    df_all_for_total = cfg["load"](str(cfg["db_path"]),
                                                   state.native_lang, state.target_lang)
                    total_lessons = max(len(cfg["get_lessons"](df_all_for_total)), 1)
            except Exception:
                total_lessons = TOTAL_LESSONS

            # ── User path: which exercise out of all, % to finish ──
            # "Completed" = fully-finished lessons (lesson_id - 1).
            # We still show "lesson N / M" so the user knows which one is open.
            completed_lessons = max(state.lesson_id - 1, 0)
            lesson_pct = round(completed_lessons / total_lessons * 100, 1)
            st.markdown(
                f'<div style="background:var(--mova-card);border:1px solid var(--mova-line);'
                f'border-radius:10px;padding:10px 12px;margin:4px 0 10px">'
                f'<div style="color:var(--mova-ink-2);font-size:.7rem;'
                f'font-family:\'JetBrains Mono\',monospace;'
                f'text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">'
                f'Your path · {cfg["label"]}</div>'
                f'<div style="color:var(--mova-ink);font-size:1.05rem;font-weight:600">'
                f'{cfg["lesson_word"]} {state.lesson_id} / {total_lessons}'
                f'</div>'
                f'<div class="progress-info" style="margin-top:6px">'
                f'<span>{completed_lessons} done · {total_lessons - completed_lessons} to go</span>'
                f'<span>{lesson_pct}%</span></div>'
                f'<div class="progress-bar-wrap">'
                f'<div class="progress-bar-fill" style="width:{lesson_pct}%"></div></div>'
                f'</div>',
                unsafe_allow_html=True
            )
            _adp_steps = st.session_state.get("_adaptive_steps", list(range(1, 9)))
            _adp_idx   = st.session_state.get("_adaptive_idx", cur_step - 1)
            _adp_total = len(_adp_steps)
            _adp_pos   = _adp_idx + 1
            step_pct   = round(_adp_idx / max(_adp_total, 1) * 100, 0)
            _adp_mode  = st.session_state.get("_adaptive_mode", "cold_start")
            _adp_badge = (
                ' <span style="background:#1a3a1a;color:#34d0a0;font-size:.62rem;'
                'padding:1px 6px;border-radius:10px;font-family:\'JetBrains Mono\',monospace;'
                'vertical-align:middle">adaptive</span>'
                if _adp_mode == "adaptive" else ""
            )
            st.markdown(
                f'<div class="progress-info">'
                f'<span>Step {_adp_pos} / {_adp_total}{_adp_badge}</span>'
                f'<span>{"🔒" if cur_step in REQUIRED_STEPS else ""}</span></div>'
                f'<div class="progress-bar-wrap">'
                f'<div class="progress-bar-fill" style="width:{step_pct}%;background:linear-gradient(90deg, var(--mova-mint), #34D0A0)"></div></div>',
                unsafe_allow_html=True
            )
            st.caption(f"`{state.language_pair}`")

            # Step navigation — back / repeat
            st.markdown("---")
            st.caption("Step navigation")
            nav_c1, nav_c2 = st.columns(2)
            with nav_c1:
                _adp_idx_nav  = st.session_state.get("_adaptive_idx", 0)
                back_disabled = _adp_idx_nav <= 0
                if st.button("← Previous", disabled=back_disabled,
                             use_container_width=True, key="nav_back",
                             help="Go to the previous step"):
                    _clear_lesson()
                    _prev_idx = max(0, _adp_idx_nav - 1)
                    _prev_seq = st.session_state.get("_adaptive_steps", list(range(1, 9)))
                    st.session_state["_adaptive_idx"] = _prev_idx
                    st.session_state["lesson_step"]   = _prev_seq[_prev_idx]
                    st.rerun()
            with nav_c2:
                if st.button("🔄 Repeat", use_container_width=True,
                             key="nav_repeat",
                             help="Restart the current step"):
                    _clear_lesson()
                    # lesson_step stays the same, but per-step state is wiped
                    st.rerun()

            # Quick-jump dropdown — all 8 steps always visible;
            # steps skipped by adaptive are marked "(+ optional)"
            _adp_seq_nav  = st.session_state.get("_adaptive_steps", list(range(1, 9)))
            _adp_idx_jump = st.session_state.get("_adaptive_idx", 0)
            # Deduplicate adaptive seq (EXTRA_REPEAT may repeat step 2)
            _seen_j: set = set()
            _adp_unique = [s for s in _adp_seq_nav
                           if not (s in _seen_j or _seen_j.add(s))]  # type: ignore
            # Always offer all 8 steps; skipped ones go at end with "(+ optional)" label
            _all_8 = list(range(1, 9))
            _optional_steps = [s for s in _all_8 if s not in _adp_unique]
            _full_options = _adp_unique + _optional_steps

            def _step_label(s):
                base = f"Step {s}"
                if s in REQUIRED_STEPS:
                    base += " \U0001f512"
                if s in _optional_steps:
                    base += "  (+ optional)"
                return base

            jump_default = min(_adp_idx_jump, len(_full_options) - 1)
            jump_to = st.selectbox(
                "Jump to step",
                options=_full_options,
                index=jump_default,
                format_func=_step_label,
                key="nav_jump",
            )
            if jump_to != cur_step:
                if st.button(f"Go to Step {jump_to}",
                             use_container_width=True,
                             key="nav_go"):
                    _clear_lesson()
                    if jump_to in _adp_seq_nav:
                        # Step is in adaptive sequence -- use its index normally
                        _new_idx = _adp_seq_nav.index(jump_to)
                        st.session_state["_adaptive_idx"] = _new_idx
                    else:
                        # Optional step (skipped by adaptive) -- insert it after
                        # current position so adaptive flow continues after it
                        _cur_pos = st.session_state.get("_adaptive_idx", 0)
                        _new_seq = (
                            _adp_seq_nav[:_cur_pos] +
                            [jump_to] +
                            _adp_seq_nav[_cur_pos:]
                        )
                        st.session_state["_adaptive_steps"] = _new_seq
                        st.session_state["_adaptive_idx"]   = _cur_pos
                    st.session_state["lesson_step"] = jump_to
                    st.rerun()


            # -- Jump to lesson ----------------------------------------------------
            if module != "custom":
                st.markdown("---")
                st.caption("Jump to lesson")
                try:
                    _df_jmp = cfg["load"](str(cfg["db_path"]),
                                          state.native_lang, state.target_lang)
                    _all_lids = cfg["get_lessons"](_df_jmp)
                    _cur_idx  = (_all_lids.index(state.lesson_id)
                                 if state.lesson_id in _all_lids else 0)
                    _jump_lid = st.selectbox(
                        "lesson_jump_sel",
                        options=_all_lids,
                        index=_cur_idx,
                        format_func=lambda lid: f"{cfg['lesson_word']} {lid}",
                        key="sb_jump_lid",
                        label_visibility="collapsed",
                    )
                    if _jump_lid != state.lesson_id:
                        if st.button(
                            f"Go to {cfg['lesson_word']} {_jump_lid}",
                            use_container_width=True,
                            key="sb_go_lid",
                        ):
                            _ldf = cfg["get_lesson"](_df_jmp, _jump_lid)
                            _lp  = (f"{WHISPER_LANG.get(state.native_lang,'?')}"
                                    f"-{WHISPER_LANG.get(state.target_lang,'?')}"
                                    f"-{cfg['lang_suffix']}")
                            _clear_lesson()
                            st.session_state.pop("_progress_saved", None)
                            # Clear adaptive so it reinitialises for the new lesson
                            st.session_state.pop("_adaptive_lesson_id", None)
                            from engine.recommender import unit_id_for, vocab_topic_for_lesson
                            _jump_topic = None
                            if cfg.get("lang_suffix") in ("vocab", "phrasebook"):
                                _jump_topic = vocab_topic_for_lesson(
                                    _jump_lid, state.target_lang, cfg["db_path"])
                            st.session_state.update({
                                "session": LessonSession(
                                    state.user_id, _ldf, _jump_lid,
                                    state.native_lang, state.target_lang,
                                    language_pair=_lp,
                                    unit_id=unit_id_for(cfg.get("lang_suffix"), _jump_lid, _jump_topic),
                                ),
                                "lesson_step": 1,
                                "tts_lang":    TTS_LANG.get(state.target_lang, "en"),
                                "wh_lang":     WHISPER_LANG.get(state.target_lang),
                                "lang_pair":   _lp,
                            })
                            st.rerun()
                except Exception:
                    pass

            st.markdown("---")
            _sb_native = st.session_state.get("launcher_native", "English")
            _mm_label  = i18n.get(_sb_native, "main_menu")
            if st.button(_mm_label, use_container_width=True, key="sb_home"):
                _clear_all()
                st.rerun()

    if "lesson_step" not in st.session_state:
        if module == "custom":
            import custom_app
            custom_app.render_setup()
            return
        render_setup()
        return

    sess = st.session_state["session"]
    tts  = st.session_state["tts_lang"]
    wh   = st.session_state["wh_lang"]

    # ── Phase header ──────────────────────────────────────────────────────
    _nl = st.session_state.get("launcher_native", "English")
    _PHASE_LABELS = {
        1: i18n.get(_nl, "phase_warmup"),
        2: i18n.get(_nl, "phase_material"),
        3: i18n.get(_nl, "phase_practice"),
        4: i18n.get(_nl, "phase_speaking"),
        5: i18n.get(_nl, "phase_video"),
    }
    _phase = st.session_state.get("lesson_phase", 1)
    # Clickable phase navigation
    _nav_cols = st.columns(len(_PHASE_LABELS))
    for col, (k, v) in zip(_nav_cols, _PHASE_LABELS.items()):
        with col:
            if k == _phase:
                st.markdown(f"**{v}**", help=None)
            else:
                if st.button(v, key=f"phase_nav_{k}", use_container_width=True):
                    st.session_state["lesson_phase"] = k
                    st.rerun()

    # ── Phase 1: Rozminka ─────────────────────────────────────────────────────
    if _phase == 1:
        if phase1_warmup(sess, tts, wh):
            st.session_state["lesson_phase"] = 2
            st.rerun()
        return

    # ── Phase 2: Novyi material (existing 8-step flow) ────────────────────
    if _phase == 2:
        step = st.session_state["lesson_step"]

        if step > 8 or sess.state.lesson_complete:
            _save_step_progress(sess, 99)
            st.session_state["lesson_phase"] = 3
            st.session_state["lesson_step"]  = 1
            st.rerun()
            return

        _save_step_progress(sess, step)
        _init_adaptive_session(sess)

        for _toast_msg in st.session_state.pop("_pending_toasts", []):
            st.toast(_toast_msg, icon="\U0001f389")

        fn = STEPS.get(step)
        if fn:
            done = fn(sess, tts, wh)
            if done:
                try:
                    _sim  = float(st.session_state.get("_last_similarity", 0.0))
                    _lang = {
                        "en": "English", "uk": "Ukrainian",
                        "es": "Spanish",  "ko": "Korean",
                    }.get(st.session_state.get("launcher_native", "English"), "en")
                    _gres   = on_step_complete(sess.state.user_id, step, _sim, _lang)
                    _toasts = []
                    if _gres.get("leveled_up"):
                        _toasts.append(f"\u2b50 +{_gres['xp_earned']} XP")
                    for _bid, _bem, _bname, _bdesc in _gres.get("new_badges", []):
                        _toasts.append(f"{_bem} {_bname}: {_bdesc}!")
                    if not _gres.get("leveled_up") and not _gres.get("new_badges"):
                        _toasts.append(f"⭐ +{_gres['xp_earned']} XP")
                    st.session_state["_pending_toasts"] = (
                        st.session_state.get("_pending_toasts", []) + _toasts
                    )
                except Exception:
                    pass
                _adp_seq = st.session_state.get("_adaptive_steps", [])
                _adp_idx = st.session_state.get("_adaptive_idx", 0)
                if _adp_idx + 1 < len(_adp_seq):
                    st.session_state["_adaptive_idx"] = _adp_idx + 1
                st.session_state["lesson_step"] = step + 1
                st.rerun()
        return

    # ── Phase 3: Praktyka ─────────────────────────────────────────────────────
    if _phase == 3:
        if phase3_practice(sess, tts, wh):
            st.session_state["lesson_phase"] = 4
            st.rerun()
        return

    # ── Phase 4: Vyslovliuvannia ──────────────────────────────────────────────
    if _phase == 4:
        if phase4_expression(sess, tts, wh):
            st.session_state["lesson_phase"] = 5
            st.rerun()
        return

    # ── Phase 5: YouTube Video ────────────────────────────────────────────────
    if _phase == 5:
        if phase5_video(sess):
            # Whole-lesson gamification (bonus XP, streak, lessons_completed,
            # badges) — CLAUDE.md 2026-08-23: on_lesson_complete() existed
            # and worked (engine/gamification.py, same call reading_app.py
            # already makes live) but nothing in this Phase 1-5 flow ever
            # called it -- its only callers here were render_complete() and
            # phase5_summary(), both orphaned, unreachable from this
            # dispatch. Per-step XP (on_step_complete, Phase 2 above) still
            # fired fine; only the once-per-lesson bonus/streak/badge check
            # was silently dead -- almost certainly why the sidebar streak
            # always read "0 days" regardless of actual usage.
            _ltoasts: list[str] = []
            try:
                _llang = {
                    "English": "en", "Ukrainian": "uk", "Spanish": "es", "Korean": "ko",
                }.get(st.session_state.get("launcher_native", "English"), "en")
                _lres = on_lesson_complete(sess.state.user_id, _llang)
                _ltoasts.append(f"🎉 Lesson complete! +{_lres['xp_earned']} XP bonus")
                if _lres.get("leveled_up"):
                    _ltoasts.append(f"⭐ New level {_lres['level_num']}: {_lres['level_name']}!")
                for _bid, _bem, _bname, _bdesc in _lres.get("new_badges", []):
                    _ltoasts.append(f"{_bem} Badge «{_bname}»: {_bdesc}!")
                streak = _lres.get("streak_current", 0)
                if streak > 1:
                    _ltoasts.append(f"🔥 Streak {streak} days!")
            except Exception as e:
                print(f"[app] on_lesson_complete error: {e}")

            st.session_state.pop("lesson_phase", None)
            st.session_state.pop("p5_topic", None)
            st.session_state.pop("p5_topic_display", None)
            _clear_all()
            # _clear_all() wipes session_state -- queue toasts AFTER it so
            # they survive to be shown next time Phase 2's step loop runs
            # (same "shown on next lesson start" pattern reading_app.py
            # already uses for its own _pending_r_toasts).
            if _ltoasts:
                st.session_state["_pending_toasts"] = _ltoasts
            st.rerun()
        return


if __name__ == "__main__":
    main()
