"""Audio file validation and conversion to WAV."""
from __future__ import annotations

import logging
import os
import shutil

from .errors import SpeechError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = frozenset({"wav", "mp3", "m4a", "webm", "ogg", "flac"})


def extension_of(filename: str) -> str:
    """Return the lower-case extension of ``filename`` without the dot ('' if none)."""
    return os.path.splitext(filename)[1].lstrip(".").lower()


def allowed_file(filename: str) -> bool:
    """True if ``filename`` has a supported audio extension."""
    return extension_of(filename) in ALLOWED_EXTENSIONS


def check_ffmpeg() -> bool:
    """True if an ``ffmpeg`` executable is on the PATH."""
    return shutil.which("ffmpeg") is not None


def convert_to_wav(input_path: str, output_path: str) -> None:
    """Convert an audio file to 16 kHz mono WAV, or copy it if it already is a WAV.

    Raises:
        SpeechError: if ffmpeg is needed but missing, or the file cannot be decoded.
    """
    ext = extension_of(input_path)
    if ext == "wav":
        shutil.copyfile(input_path, output_path)
        return

    if not check_ffmpeg():
        raise SpeechError(
            "FFmpeg is not installed, so only .wav files can be transcribed. "
            "Install FFmpeg or upload a WAV file.",
            status=503,
        )

    from pydub import AudioSegment  # imported lazily: needs audioop on newer Pythons

    try:
        sound = AudioSegment.from_file(input_path, format=ext)
        sound.set_frame_rate(16000).set_channels(1).export(output_path, format="wav")
    except Exception:
        logger.exception("Failed to convert %s", input_path)
        raise SpeechError("The audio file could not be decoded. Is it a valid audio file?")
