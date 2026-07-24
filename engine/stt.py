"""
engine/stt.py - Google Cloud Speech-to-Text (replaces OpenAI Whisper).

Same public API: transcribe_bytes(), transcribe_file(), whisper_available().
Credentials: reuses st.secrets["gcp_service_account"] already configured for gspread.
"""
from __future__ import annotations
import os
import streamlit as st

_LANG_CODES: dict[str, str] = {
    "en": "en-US", "uk": "uk-UA", "de": "de-DE", "es": "es-ES",
    "ko": "ko-KR", "fr": "fr-FR", "ja": "ja-JP", "zh": "zh-CN",
    "pt": "pt-BR", "it": "it-IT", "pl": "pl-PL", "ru": "ru-RU",
}


@st.cache_resource(show_spinner=False)
def _get_client():
    from google.cloud import speech
    from google.oauth2.service_account import Credentials
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return speech.SpeechClient(credentials=creds)
    except Exception:
        return speech.SpeechClient()


def _detect_encoding(audio_bytes: bytes):
    """Return (encoding, sample_rate) based on audio header."""
    from google.cloud import speech
    if audio_bytes[:4] == b"RIFF":
        # WAV — read sample rate from header bytes 24-27
        import struct
        rate = struct.unpack_from("<I", audio_bytes, 24)[0]
        return speech.RecognitionConfig.AudioEncoding.LINEAR16, rate
    # Default: browser MediaRecorder → WEBM/OPUS
    return speech.RecognitionConfig.AudioEncoding.WEBM_OPUS, 48000


def transcribe_bytes(audio_bytes: bytes, language: str | None = None) -> str:
    try:
        from google.cloud import speech
        client = _get_client()
        bcp47 = _LANG_CODES.get(language or "en", "en-US")
        encoding, sample_rate = _detect_encoding(audio_bytes)
        audio_obj = speech.RecognitionAudio(content=audio_bytes)
        config = speech.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=sample_rate,
            language_code=bcp47,
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio_obj)
        texts = [r.alternatives[0].transcript for r in response.results if r.alternatives]
        return " ".join(texts).strip()
    except Exception as e:
        st.warning(f"STT error: {e}")
        return ""


def transcribe_file(file_path: str, language: str | None = None) -> str:
    with open(file_path, "rb") as f:
        return transcribe_bytes(f.read(), language)


def whisper_available() -> bool:
    return True
