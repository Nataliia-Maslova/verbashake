"""
engine/license.py — LemonSqueezy license key management for IMLLS.

Each installation gets a unique instance_id derived from the machine hardware.
The license key + instance_id are stored in ~/.imlls/license.json so the user
doesn't have to re-enter the key every launch.

LemonSqueezy Licenses API docs:
  https://docs.lemonsqueezy.com/help/licensing/license-api
"""
from __future__ import annotations

import hashlib
import json
import platform
import time
import urllib.request
import urllib.error
from pathlib import Path

import streamlit as st

# ── Constants ─────────────────────────────────────────────────────────────────

_CACHE_DIR  = Path.home() / ".imlls"
_CACHE_FILE = _CACHE_DIR / "license.json"
_BASE_URL   = "https://api.lemonsqueezy.com/v1/licenses"

# How often to re-validate a cached license (seconds).  24 h by default.
_REVALIDATE_INTERVAL = 86_400


# ── Machine fingerprint ───────────────────────────────────────────────────────

def _machine_id() -> str:
    """Stable per-device identifier, hashed so it's not personally identifiable."""
    raw = (
        platform.node()
        + platform.machine()
        + platform.processor()
    )
    return hashlib.md5(raw.encode()).hexdigest()


_INSTANCE_NAME = f"imlls-{_machine_id()[:8]}"


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _post(endpoint: str, payload: dict) -> dict:
    """POST JSON to a LemonSqueezy license endpoint. Returns parsed response."""
    try:
        api_key = st.secrets.get("LEMON_API_KEY", "")
    except Exception:
        api_key = ""

    body  = json.dumps(payload).encode()
    req   = urllib.request.Request(
        f"{_BASE_URL}/{endpoint}",
        data=body,
        headers={
            "Accept":        "application/json",
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return {"error": body.get("message", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def _write_cache(data: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_cache() -> dict | None:
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_cached_license() -> dict | None:
    """Return the cached license record, or None if no cache exists."""
    return _read_cache()


def clear_license() -> None:
    """Delete the local license cache (deactivate flow)."""
    try:
        _CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def activate_license(license_key: str) -> dict:
    """
    Activate a license key for this device.

    Returns:
        {"ok": True,  "instance_id": "...", "customer_email": "..."} on success
        {"ok": False, "error": "human-readable message"}              on failure
    """
    resp = _post("activate", {
        "license_key":   license_key,
        "instance_name": _INSTANCE_NAME,
    })

    if resp.get("error"):
        return {"ok": False, "error": resp["error"]}

    # LemonSqueezy returns {"activated": true, "instance": {...}, ...}
    if not resp.get("activated"):
        msg = resp.get("error") or "Activation failed — check the key and try again."
        return {"ok": False, "error": msg}

    instance_id = (resp.get("instance") or {}).get("id", "")
    customer    = (resp.get("meta") or {}).get("customer_email", "")

    record = {
        "license_key":     license_key,
        "instance_id":     instance_id,
        "machine_id":      _machine_id(),
        "activated_at":    time.time(),
        "last_validated":  time.time(),
        "valid":           True,
        "customer_email":  customer,
    }
    _write_cache(record)
    return {"ok": True, "instance_id": instance_id, "customer_email": customer}


def validate_license(force: bool = False) -> dict:
    """
    Validate the cached license against LemonSqueezy.

    Skips the network call if the cache is fresh (< _REVALIDATE_INTERVAL seconds
    old) unless ``force=True``.

    Returns:
        {"ok": True}                     — license is valid
        {"ok": False, "error": "..."}    — invalid or no cache
    """
    cache = _read_cache()
    if not cache:
        return {"ok": False, "error": "No license found."}

    # Fast path — cache is fresh
    if not force:
        age = time.time() - float(cache.get("last_validated", 0))
        if age < _REVALIDATE_INTERVAL and cache.get("valid"):
            return {"ok": True}

    resp = _post("validate", {
        "license_key": cache["license_key"],
        "instance_id": cache.get("instance_id", ""),
    })

    if resp.get("error") or not resp.get("valid"):
        cache["valid"] = False
        _write_cache(cache)
        msg = resp.get("error") or "License is no longer valid."
        return {"ok": False, "error": msg}

    cache["valid"]          = True
    cache["last_validated"] = time.time()
    _write_cache(cache)
    return {"ok": True}


def deactivate_license() -> dict:
    """
    Deactivate this device's instance so the seat can be used elsewhere.

    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    cache = _read_cache()
    if not cache:
        return {"ok": False, "error": "No cached license to deactivate."}

    resp = _post("deactivate", {
        "license_key": cache["license_key"],
        "instance_id": cache.get("instance_id", ""),
    })

    clear_license()

    if resp.get("error"):
        return {"ok": False, "error": resp["error"]}
    return {"ok": True}
