"""
license_gate.py — License activation screen for IMLLS.

Shown as the first screen if no valid local license is found.
On success, sets st.session_state["license_ok"] = True so app.py proceeds.
"""
from __future__ import annotations

import streamlit as st

from engine.license import activate_license, validate_license, deactivate_license


_GATE_CSS = """
<style>
.gate-wrap {
    max-width: 480px;
    margin: 80px auto 0;
    text-align: center;
}
.gate-logo {
    font-size: 3.5rem;
    margin-bottom: 8px;
}
.gate-title {
    font-size: 1.9rem;
    font-weight: 800;
    color: var(--mova-ink);
    margin-bottom: 4px;
}
.gate-sub {
    color: var(--mova-ink-2);
    font-size: 1rem;
    margin-bottom: 32px;
}
.gate-hint {
    font-size: .82rem;
    color: var(--mova-ink-3);
    margin-top: 20px;
    line-height: 1.6;
}
.gate-hint a {
    color: var(--mova-indigo);
    text-decoration: none;
}
</style>
"""


def show() -> None:
    """
    Render the license gate.  Returns without doing anything if the license
    is already confirmed valid in session state.
    """
    st.markdown(_GATE_CSS, unsafe_allow_html=True)

    # Centre everything with a narrow column trick
    _, mid, _ = st.columns([1, 2, 1])

    with mid:
        st.markdown(
            '<div class="gate-logo">🎓</div>'
            '<div class="gate-title">IMLLS</div>'
            '<div class="gate-sub">Enter your license key to get started</div>',
            unsafe_allow_html=True,
        )

        license_key = st.text_input(
            "License key",
            placeholder="XXXX-XXXX-XXXX-XXXX",
            label_visibility="collapsed",
            key="gate_license_key_input",
        )

        btn_col, _ = st.columns([3, 1])
        with btn_col:
            activate_clicked = st.button(
                "Activate",
                type="primary",
                use_container_width=True,
                key="gate_activate_btn",
            )

        if activate_clicked:
            key = license_key.strip()
            if not key:
                st.error("Please enter your license key.")
            else:
                with st.spinner("Activating…"):
                    result = activate_license(key)
                if result["ok"]:
                    st.session_state["license_ok"] = True
                    st.success("✅ License activated!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

        st.markdown(
            '<div class="gate-hint">'
            'Don\'t have a license? '
            '<a href="https://verbasake.lemonsqueezy.com" target="_blank">'
            'Buy at verbasake.lemonsqueezy.com</a><br>'
            'Each license works on up to 2 devices simultaneously.'
            '</div>',
            unsafe_allow_html=True,
        )


def check_and_gate() -> bool:
    """
    Call this at the top of app.py main().

    Returns True  → license is valid, proceed normally.
    Returns False → license gate is being shown, stop rendering.
    """
    # Already confirmed this session
    if st.session_state.get("license_ok"):
        return True

    # Try the local cache (fast path — no network unless stale)
    result = validate_license()
    if result["ok"]:
        st.session_state["license_ok"] = True
        return True

    # Show the activation screen
    show()
    return False
