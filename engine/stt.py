"""
engine/stt.py - local speech-to-text via faster-whisper (replaces Google Cloud
Speech-to-Text — no per-call API cost, no GCP credentials needed).

Same public API: transcribe_bytes(), transcribe_file(), whisper_available().
Model size is configurable via st.secrets["WHISPER_MODEL"] or env WHISPER_MODEL
(default: "small" — better accuracy than "base" for uk/ko, still CPU-friendly
with int8 quantization). Downloaded from Hugging Face Hub on first use.
"""
from __future__ import annotations
import io
import os

import streamlit as st

_DEFAULT_MODEL = "small"


@st.cache_resource(show_spinner=False)
def _get_model():
    from faster_whisper import WhisperModel
    try:
        secret_model = st.secrets.get("WHISPER_MODEL")
    except Exception:
        secret_model = None
    model_size = secret_model or os.environ.get("WHISPER_MODEL", _DEFAULT_MODEL)
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe_bytes(audio_bytes: bytes, language: str | None = None) -> str:
    try:
        model = _get_model()
        segments, _info = model.transcribe(
            io.BytesIO(audio_bytes),
            language=language or None,
            vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        st.warning(f"STT error: {e}")
        return ""


def transcribe_file(file_path: str, language: str | None = None) -> str:
    try:
        model = _get_model()
        segments, _info = model.transcribe(
            file_path,
            language=language or None,
            vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        st.warning(f"STT error: {e}")
        return ""


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False
