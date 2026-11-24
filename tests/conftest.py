import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "CSRF_ENABLED": False,
        "SECRET_KEY": "test",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "GENERATED_AUDIO_FOLDER": str(tmp_path / "audio"),
        "DATABASE": str(tmp_path / "test.db"),
        "LOG_FILE": None,
    })
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_tts(monkeypatch):
    """Replace gTTS with a stub that writes a few bytes."""
    def _fake(text, lang, output_path):
        with open(output_path, "wb") as fh:
            fh.write(b"ID3fake")
    monkeypatch.setattr("app.generate_speech", _fake)


@pytest.fixture
def fake_stt(monkeypatch):
    """Skip ffmpeg and the Google API: conversion copies bytes, transcription is canned."""
    def _convert(src, dst):
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
    monkeypatch.setattr("app.convert_to_wav", _convert)
    monkeypatch.setattr("app.transcribe_audio", lambda path, lang: "hello world")
