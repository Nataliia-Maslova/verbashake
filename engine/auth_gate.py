"""
engine/auth_gate.py — Google login gate (Streamlit native st.login()/st.user).

Replaces license_gate.py's LemonSqueezy machine-ID gate. Logging in is
required to use the app at all (real accounts are what make cross-device
mastery/SRS/gamification data meaningful) — being logged in does NOT imply a
paid subscription; that's a separate, narrower check (engine.billing.is_paid)
applied only at the specific live-generation call sites in engine/gemini.py.

Requires an [auth] section in .streamlit/secrets.toml (redirect_uri,
cookie_secret, client_id, client_secret, server_metadata_url) — see CLAUDE.md
for the exact keys and how to get them from Google Cloud Console.
"""
from __future__ import annotations

import streamlit as st

from engine import signup_gate

_GATE_CSS = """
<style>
.gate-wrap { max-width: 480px; margin: 80px auto 0; text-align: center; }
.gate-logo { font-size: 3.5rem; margin-bottom: 8px; }
.gate-title { font-size: 1.9rem; font-weight: 800; color: var(--mova-ink); margin-bottom: 4px; }
.gate-sub { color: var(--mova-ink-2); font-size: 1rem; margin-bottom: 32px; }
</style>
"""


def _show_waitlist() -> None:
    """Shown to a logged-in Google account that missed this week's signup cap."""
    st.markdown(_GATE_CSS, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        left = signup_gate.spots_left_this_week()
        spots_line = f" ({left} spots left right now)" if left else ""
        st.markdown(
            '<div class="gate-logo">⏳</div>'
            '<div class="gate-title">You\'re on the list!</div>'
            f'<div class="gate-sub">This week\'s free spots are full{spots_line} — '
            'we open more every Monday. Come back soon!</div>',
            unsafe_allow_html=True,
        )
        if st.button("Try again", use_container_width=True):
            st.rerun()


def show() -> None:
    st.markdown(_GATE_CSS, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            '<div class="gate-logo">🗣️</div>'
            '<div class="gate-title">VerbaShake</div>'
            '<div class="gate-sub">Sign in to start learning</div>',
            unsafe_allow_html=True,
        )
        # Consent gate: the login button stays disabled until this is
        # checked, so nobody's account/progress data is created before they
        # could see the Privacy Policy — not just a link next to the button.
        st.markdown(
            '<div style="text-align:center;margin-bottom:6px;font-size:.9rem">'
            '📄 <a href="app/static/legal/privacy.html" target="_blank">Privacy Policy</a>'
            '</div>',
            unsafe_allow_html=True,
        )
        agreed = st.checkbox("I have read and agree to the Privacy Policy", key="_consent_privacy")
        if st.button("Continue with Google", type="primary", use_container_width=True, disabled=not agreed):
            st.login()


def _auth_configured() -> bool:
    """Whether an [auth] section exists in secrets.toml at all."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def check_and_gate() -> bool:
    """
    Call at the top of app.py's main().
    Returns True  → user is logged in, proceed normally.
    Returns False → the login gate is being shown, stop rendering.
    """
    if not _auth_configured():
        # [auth] not configured in secrets.toml yet (e.g. local dev before
        # setup) — nobody could log in anyway, so don't lock out the
        # developer working on the app before OAuth is wired up.
        return True
    try:
        logged_in = st.user.is_logged_in
    except Exception as e:
        # [auth] IS configured but the check itself blew up (bad secrets,
        # transient Streamlit/OIDC error, ...) — fail CLOSED, not open.
        # Silently treating a broken check as "logged in" would open the
        # whole app to anyone the moment auth misbehaves in production.
        print(f"[auth_gate] st.user check failed while [auth] is configured: {e}")
        show()
        return False
    if not logged_in:
        show()
        return False
    user_id = current_user_id()
    if user_id and not signup_gate.check_and_admit(user_id):
        _show_waitlist()
        return False
    return True


def current_user_id() -> str | None:
    """The logged-in user's stable identity (Google account email), or None."""
    try:
        if st.user.is_logged_in:
            return st.user.email
    except Exception:
        pass
    return None


def current_user_name() -> str:
    """Display name for the logged-in user — falls back to the email."""
    try:
        if st.user.is_logged_in:
            return st.user.get("name") or st.user.email
    except Exception:
        pass
    return "student1"
