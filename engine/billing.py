"""
engine/billing.py — Stripe Checkout + polling-based subscription status.

V1 has no webhook endpoint (Streamlit can't expose one without extra
infrastructure — see CLAUDE.md Phase D notes), so subscription status is
re-verified against the Stripe API instead of pushed by Stripe events:
  - Right after a successful Checkout (handle_checkout_return()).
  - Whenever the cached row is older than _STALE_AFTER (is_paid()/get_status()).

This means a cancellation/failed payment can take up to _STALE_AFTER to be
reflected — acceptable for V1, see CLAUDE.md for the webhook upgrade path.

Requires STRIPE_SECRET_KEY and STRIPE_PRICE_ID in st.secrets/env, and the
`subscriptions` table from schema.sql.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import streamlit as st

from engine import db

_STALE_AFTER = timedelta(hours=1)
# Beyond this, a cached "active" status is no longer trusted even if Stripe
# sync keeps failing (revoked key, rate limiting, outage) -- without this,
# get_status() would keep serving a stale "active" row indefinitely, the
# false-positive-paid direction, instead of just for the ~1h a healthy
# re-sync would normally take.
_HARD_STALE_AFTER = timedelta(hours=24)

_DEFAULT_STATUS = {
    "status": "free",
    "stripe_customer_id": None,
    "stripe_subscription_id": None,
    "plan": None,
    "current_period_end": None,
}


def _secret(name: str) -> str:
    try:
        val = st.secrets.get(name)
    except Exception:
        val = None
    return val or os.environ.get(name, "")


def _stripe():
    import stripe
    stripe.api_key = _secret("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY not found in secrets.toml or environment")
    return stripe


# ── Status cache ─────────────────────────────────────────────────────────────

def get_status(user_id: str) -> dict:
    """Cached subscription status, refreshed from Stripe if stale."""
    row = db.fetch_one("SELECT * FROM subscriptions WHERE user_id = :uid", {"uid": user_id})
    if row is None:
        return dict(_DEFAULT_STATUS)

    checked_at = row["checked_at"]
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - checked_at

    if age > _STALE_AFTER and row.get("stripe_customer_id"):
        try:
            return _sync_from_stripe(user_id, row["stripe_customer_id"])
        except Exception:
            pass  # Stripe unreachable — fall through to the staleness check below

    if age > _HARD_STALE_AFTER and row.get("status") == "active":
        # Sync has been failing for a long time (checked_at is only ever
        # updated on a *successful* sync) -- stop trusting a possibly-
        # cancelled subscription just because Stripe is unreachable. Not
        # persisted: once sync succeeds again it overwrites this normally.
        row = dict(row)
        row["status"] = "unknown"
    return row


def is_paid(user_id: str | None) -> bool:
    if not user_id:
        return False
    return get_status(user_id).get("status") == "active"


def _sync_from_stripe(user_id: str, customer_id: str) -> dict:
    stripe = _stripe()
    subs = stripe.Subscription.list(customer=customer_id, status="all", limit=1)
    values = dict(_DEFAULT_STATUS)
    values["stripe_customer_id"] = customer_id
    if subs.data:
        sub = subs.data[0]
        item = sub["items"]["data"][0] if sub["items"]["data"] else None
        values["stripe_subscription_id"] = sub.id
        values["status"] = "active" if sub.status in ("active", "trialing") else sub.status
        # Both of these read into the same Stripe API item object, whose
        # nested shape has already changed between API versions once
        # (current_period_end moved from the Subscription to each item) --
        # guard both the same way so a future reshape degrades one field to
        # None instead of throwing and aborting the whole sync (which used
        # to mean db.upsert() below never ran and a real charge went
        # unrecorded, see CLAUDE.md's current_period_end incident).
        try:
            values["plan"] = item["price"]["id"] if item else None
        except (KeyError, TypeError):
            values["plan"] = None
        try:
            end_ts = item["current_period_end"] if item else None
        except (KeyError, TypeError):
            end_ts = None
        if end_ts:
            values["current_period_end"] = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    db.upsert("subscriptions", keys={"user_id": user_id},
              values={**values, "checked_at": datetime.now(timezone.utc)})
    return db.fetch_one("SELECT * FROM subscriptions WHERE user_id = :uid", {"uid": user_id})


# ── Checkout ─────────────────────────────────────────────────────────────────

def create_checkout_session(user_id: str, email: str, return_url: str) -> str:
    """Create a Stripe Checkout Session, return the URL to redirect the user to."""
    stripe = _stripe()
    price_id = _secret("STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID not found in secrets.toml or environment")

    existing = db.fetch_one(
        "SELECT stripe_customer_id FROM subscriptions WHERE user_id = :uid", {"uid": user_id}
    )
    customer_id = existing["stripe_customer_id"] if existing else None

    kwargs = {"customer": customer_id} if customer_id else {"customer_email": email}
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        client_reference_id=user_id,
        success_url=f"{return_url}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{return_url}?checkout=cancelled",
        **kwargs,
    )
    return session.url


def handle_checkout_return() -> None:
    """Call once near the top of app.py's main() — finalises a successful Checkout."""
    params = st.query_params
    if params.get("checkout") != "success" or "session_id" not in params:
        return
    try:
        stripe = _stripe()
        session = stripe.checkout.Session.retrieve(params["session_id"])
        user_id = session.client_reference_id
        if user_id and session.customer:
            _sync_from_stripe(user_id, session.customer)
            st.session_state["_billing_just_upgraded"] = True
            st.session_state.pop("_checkout_url", None)
    except Exception as e:
        print(f"[billing] checkout return error: {e}")
    finally:
        st.query_params.clear()
