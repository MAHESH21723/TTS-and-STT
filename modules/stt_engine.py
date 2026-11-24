"""Speech-to-text using the Google Web Speech API via SpeechRecognition (needs internet)."""
from __future__ import annotations

import logging
import os

import speech_recognition as sr

from .errors import SpeechError

logger = logging.getLogger(__name__)

#: Language code -> BCP-47 locale understood by the recogniser.
LANGUAGE_LOCALES: dict[str, str] = {
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "it": "it-IT",
    "pt": "pt-PT",
    "ja": "ja-JP",
    "zh-CN": "zh-CN",
}


def transcribe_audio(wav_path: str, lang: str = "en") -> str:
    """Transcribe a PCM WAV file and return the recognised text.

    Raises:
        SpeechError: if the file is unreadable, contains no recognisable speech,
            or the online recogniser cannot be reached.
    """
    if lang not in LANGUAGE_LOCALES:
        raise SpeechError("Unsupported language selected.")
    if not os.path.exists(wav_path):
        raise SpeechError("Audio file not found.", status=500)

    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
    except (ValueError, EOFError, OSError):
        logger.warning("Unreadable audio: %s", wav_path, exc_info=True)
        raise SpeechError("The audio file could not be read. Is it a valid, uncorrupted recording?")

    try:
        text = recognizer.recognize_google(audio, language=LANGUAGE_LOCALES[lang])
    except sr.UnknownValueError:
        raise SpeechError(
            "No speech detected. The audio may be silent, noisy, or in a different language.",
            status=422,
        )
    except sr.RequestError:
        logger.exception("Speech recognition service error")
        raise SpeechError(
            "The speech recognition service is unavailable. "
            "Check your internet connection and try again.",
            status=502,
        )
    logger.info("Transcribed %d words (lang=%s)", len(text.split()), lang)
    return text
