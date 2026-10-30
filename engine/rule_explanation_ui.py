"""
engine/rule_explanation_ui.py — renders gemini.explain_lesson_rule's result,
shared by lesson Step 1 (grammar.py::_render_rule_explanation) and the
"Explain this topic" panel on My Path (path_app.py).

Situations first (Наталья, 2026-10-30): each scene the student imagines and
tries to say themselves, with the answer behind a click — then the rule,
examples and exceptions as before. Explanations cached under the old prompt
have no "situations" and render exactly as they used to.
"""
from __future__ import annotations

import streamlit as st

from engine import i18n


def render(explanation: dict, native_lang: str) -> None:
    situations = explanation.get("situations") or []
    for s in situations:
        with st.container(border=True):
            st.markdown(f"🎬 {s.get('situation', '')}")
            with st.expander(i18n.get(native_lang, "rule_situation_show")):
                st.markdown(f"**{s.get('target', '')}**")
                if s.get("native"):
                    st.caption(s["native"])
    if situations:
        st.markdown(f"**{i18n.get(native_lang, 'rule_rule_header')}**")
    st.markdown(explanation.get("rule", ""))
    for ex in explanation.get("examples", []):
        st.markdown(f"- **{ex.get('target', '')}** — {ex.get('native', '')}")
    if explanation.get("exceptions"):
        st.markdown(f"**{i18n.get(native_lang, 'rule_exceptions_label')}**")
        for exc in explanation["exceptions"]:
            st.markdown(f"- {exc}")
