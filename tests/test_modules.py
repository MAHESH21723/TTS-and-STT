import sqlite3
import wave

import pytest
import speech_recognition as sr

from modules import audio_processor, database as db, stt_engine, tts_engine
from modules.documents import build_pdf, conversion_text
from modules.errors import SpeechError


def make_wav(path, seconds=0.1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return str(path)


# ---------------------------------------------------------------- audio_processor

@pytest.mark.parametrize("name, ok", [
    ("a.wav", True), ("A.MP3", True), ("x.tar.webm", True),
    ("a.exe", False), ("noext", False), (".wav", False), ("a.wav.txt", False),
])
def test_allowed_file(name, ok):
    assert audio_processor.allowed_file(name) is ok


def test_convert_wav_is_copied(tmp_path):
    src = make_wav(tmp_path / "in.wav")
    dst = str(tmp_path / "out.wav")
    audio_processor.convert_to_wav(src, dst)
    assert open(src, "rb").read() == open(dst, "rb").read()


def test_convert_requires_ffmpeg(tmp_path, monkeypatch):
    src = tmp_path / "in.mp3"
    src.write_bytes(b"x")
    monkeypatch.setattr(audio_processor, "check_ffmpeg", lambda: False)
    with pytest.raises(SpeechError) as exc:
        audio_processor.convert_to_wav(str(src), str(tmp_path / "out.wav"))
    assert exc.value.status == 503 and "FFmpeg" in exc.value.message


def test_convert_decode_failure_is_wrapped(tmp_path, monkeypatch):
    src = tmp_path / "in.mp3"
    src.write_bytes(b"not audio")
    monkeypatch.setattr(audio_processor, "check_ffmpeg", lambda: True)
    import pydub
    monkeypatch.setattr(pydub.AudioSegment, "from_file",
                        staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError("bad"))))
    with pytest.raises(SpeechError, match="could not be decoded"):
        audio_processor.convert_to_wav(str(src), str(tmp_path / "out.wav"))


# ---------------------------------------------------------------- tts_engine

def test_generate_speech_calls_gtts(tmp_path, monkeypatch):
    calls = {}

    class FakeGTTS:
        def __init__(self, text, lang, slow):
            calls.update(text=text, lang=lang)

        def save(self, path):
            open(path, "wb").write(b"mp3")

    monkeypatch.setattr(tts_engine, "gTTS", FakeGTTS)
    out = tmp_path / "sub" / "o.mp3"
    tts_engine.generate_speech("  hi  ", "fr", str(out))
    assert calls == {"text": "hi", "lang": "fr"} and out.read_bytes() == b"mp3"


@pytest.mark.parametrize("text, lang", [("", "en"), ("x" * 2001, "en"), ("hi", "xx")])
def test_generate_speech_validation(tmp_path, text, lang):
    with pytest.raises(SpeechError):
        tts_engine.generate_speech(text, lang, str(tmp_path / "o.mp3"))


def test_generate_speech_network_failure(tmp_path, monkeypatch):
    class Broken:
        def __init__(self, **kw):
            pass

        def save(self, path):
            open(path, "wb").write(b"partial")
            raise ConnectionError("offline")

    monkeypatch.setattr(tts_engine, "gTTS", Broken)
    out = tmp_path / "o.mp3"
    with pytest.raises(SpeechError) as exc:
        tts_engine.generate_speech("hi", "en", str(out))
    assert exc.value.status == 502
    assert not out.exists()  # partial file removed


# ---------------------------------------------------------------- stt_engine

def test_language_tables_are_consistent():
    assert set(stt_engine.LANGUAGE_LOCALES) == set(tts_engine.SUPPORTED_LANGUAGES)


def test_transcribe_success(tmp_path, monkeypatch):
    wav = make_wav(tmp_path / "a.wav")
    seen = {}

    def fake(self, audio, language):
        seen["lang"] = language
        return "hello there"

    monkeypatch.setattr(sr.Recognizer, "recognize_google", fake)
    assert stt_engine.transcribe_audio(wav, "ta") == "hello there"
    assert seen["lang"] == "ta-IN"


@pytest.mark.parametrize("raised, status", [(sr.UnknownValueError(), 422), (sr.RequestError("down"), 502)])
def test_transcribe_service_errors(tmp_path, monkeypatch, raised, status):
    wav = make_wav(tmp_path / "a.wav")

    def fake(self, audio, language):
        raise raised

    monkeypatch.setattr(sr.Recognizer, "recognize_google", fake)
    with pytest.raises(SpeechError) as exc:
        stt_engine.transcribe_audio(wav, "en")
    assert exc.value.status == status


def test_transcribe_rejects_corrupt_and_bad_input(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"this is not a wav file")
    with pytest.raises(SpeechError, match="could not be read"):
        stt_engine.transcribe_audio(str(bad), "en")
    with pytest.raises(SpeechError):
        stt_engine.transcribe_audio(str(tmp_path / "missing.wav"), "en")
    with pytest.raises(SpeechError, match="Unsupported language"):
        stt_engine.transcribe_audio(make_wav(tmp_path / "a.wav"), "xx")


# ---------------------------------------------------------------- database / documents

def test_database_roundtrip(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    db.init_db(path)  # idempotent
    tts_id = db.add_conversion(path, "TTS", "hello", "a.mp3", "en")
    db.add_conversion(path, "STT", "up_1.wav", "spoken words", "ta")
    s = db.stats(path)
    assert (s["total"], s["tts"], s["stt"]) == (2, 1, 1)
    assert db.find_by_filename(path, "a.mp3")["id"] == tts_id
    assert db.find_by_filename(path, "up_1.wav")["output_data"] == "spoken words"
    assert db.find_by_filename(path, "hello") is None
    db.delete(path, tts_id)
    assert db.get(path, tts_id) is None


def test_database_rejects_bad_operation(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_conversion(path, "XXX", "a", "b", "en")


def test_search_is_parameterised(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    db.add_conversion(path, "TTS", "safe", "a.mp3", "en")
    assert db.search(path, "' OR 1=1 --") == []
    assert len(db.search(path)) == 1


def test_documents(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    db.add_conversion(path, "STT", "f.wav", "transcribed ☃ text", "en")
    row = db.search(path)[0]
    assert conversion_text(row) == "transcribed ☃ text"
    assert build_pdf(row, "English").startswith(b"%PDF")
