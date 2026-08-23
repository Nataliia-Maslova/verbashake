"""
engine/youtube_links.py — curated static YouTube links, no live API calls.

Reads data/youtube_links.csv (columns: url, language, level, topic, title),
curated manually by whoever maintains the lesson content. Matching falls back
progressively: language+level+topic -> language+level -> language only.

Also reads data/youtube_channels.csv (columns: language, channel_name,
channel_url) -- CLAUDE.md 2026-08-23: Phase 5 shows this channel list now,
not a single video, since the same one video repeating across every lesson
at a level read as stale (Наталья live-tested it). Each channel here was
verified real by visiting it directly (its handle captured from the page,
not guessed) while curating the video list above -- get_videos() itself is
kept as-is (still correct, still tested) even though phase5_video() no
longer calls it, in case a future "featured video" pairing wants it back.
"""
from __future__ import annotations

import csv
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CSV_PATH = os.path.join(_DATA_DIR, "youtube_links.csv")
_CHANNELS_CSV_PATH = os.path.join(_DATA_DIR, "youtube_channels.csv")


def _load_rows() -> list[dict]:
    if not os.path.exists(_CSV_PATH):
        return []
    with open(_CSV_PATH, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def get_channels(language: str) -> list[dict]:
    """Return curated channels for a language as [{"name": str, "url": str}, ...]."""
    if not os.path.exists(_CHANNELS_CSV_PATH):
        return []
    language = (language or "").strip().lower()
    with open(_CHANNELS_CSV_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [
        {"name": r.get("channel_name", ""), "url": r["channel_url"]}
        for r in rows
        if r.get("language", "").strip().lower() == language
    ]


def get_videos(language: str, level: str, topic: str = "", limit: int = 3) -> list[dict]:
    """Return up to `limit` curated videos as [{"title": str, "url": str}, ...]."""
    rows = _load_rows()
    language = (language or "").strip().lower()
    level = (level or "").strip()
    topic = (topic or "").strip().lower()

    def _pick(need_level: bool, need_topic: bool) -> list[dict]:
        matches = [
            r for r in rows
            if r.get("language", "").strip().lower() == language
            and (not need_level or r.get("level", "").strip() == level)
            and (not need_topic or r.get("topic", "").strip().lower() == topic)
        ]
        return [{"title": r.get("title", ""), "url": r["url"]} for r in matches[:limit]]

    for need_level, need_topic in ((True, True), (True, False), (False, False)):
        if need_topic and not topic:
            continue
        videos = _pick(need_level, need_topic)
        if videos:
            return videos
    return []
