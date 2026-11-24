"""Text-to-speech using Google Translate's TTS endpoint via gTTS (needs internet)."""
from __future__ import annotations

import logging
import os

from gtts import gTTS

from .errors import SpeechError

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 2000

#: Languages offered in the UI (code -> display name).
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "ta": "Tamil",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "zh-CN": "Chinese (Simplified)",
}


def generate_speech(text: str, lang: str, output_path: str) -> None:
    """Synthesise ``text`` in ``lang`` and write an MP3 to ``output_path``.

    Raises:
        SpeechError: for invalid input or when the online service is unreachable.
    """
    text = (text or "").strip()
    if not text:
        raise SpeechError("Please enter some text.")
    if len(text) > MAX_TEXT_LENGTH:
        raise SpeechError(f"Text is too long (maximum {MAX_TEXT_LENGTH} characters).")
    if lang not in SUPPORTED_LANGUAGES:
        raise SpeechError("Unsupported language selected.")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        gTTS(text=text, lang=lang, slow=False).save(output_path)
    except Exception:  # gTTS raises assorted requests/gTTSError types
        logger.exception("gTTS failed for lang=%s", lang)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise SpeechError(
            "The text-to-speech service could not be reached. "
            "Check your internet connection and try again.",
            status=502,
        )
    logger.info("Generated %s (%d chars, lang=%s)", os.path.basename(output_path), len(text), lang)
