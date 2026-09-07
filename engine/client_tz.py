"""
engine/client_tz.py — capture the student's own browser timezone once per
account, so features that compare against "now" (currently just
engine.schedule.today_status()'s on-time badge) use the STUDENT's clock, not
the server's (2026-09-07 fix — wrong whenever the deployed server and the
student aren't in the same timezone, the normal production case).

Uses st.context.timezone (Streamlit >= 1.something -- this app runs 1.61),
the browser's own IANA zone name reported over the websocket handshake, no
custom JS needed. An earlier version of this module tried the JS-redirect
trick this app's dark-mode toggle/PWA-injection use elsewhere
(components.html -> window.parent) to bounce the value through a URL query
param, but Streamlit's components.html iframe sandbox here is missing
allow-top-navigation -- window.parent.location.replace() is silently
blocked by the browser (DOM access to window.parent is still fine, which is
why the dark-mode/PWA tricks work; actual top-frame navigation isn't).
st.context.timezone sidesteps all of that.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import streamlit as st


def _valid_tz(name: str | None) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def ensure_client_tz(user_id: str | None) -> str | None:
    """Returns the student's IANA zone name if known, else None. Persists
    to user_prefs once per (session, user_id) so it's available even
    outside an active Streamlit context (e.g. a future batch job) --
    st.context.timezone itself needs no persistence to keep working within
    a session, this is just belt-and-suspenders."""
    from engine import user_prefs

    tz = st.session_state.get("_client_tz")
    if tz is None:
        tz = st.context.timezone
        if _valid_tz(tz):
            st.session_state["_client_tz"] = tz
        else:
            tz = None

    if tz and user_id and st.session_state.get("_client_tz_saved_for") != user_id:
        user_prefs.save_timezone(user_id, tz)
        st.session_state["_client_tz_saved_for"] = user_id

    return tz
