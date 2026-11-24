import io
import os

import pytest

from app import create_app
from modules import database as db
from modules.errors import SpeechError

AJAX = {"X-Requested-With": "XMLHttpRequest"}


def wav_upload(name="clip.wav", data=b"RIFFfake"):
    return {"audio_file": (io.BytesIO(data), name), "language": "en"}


# ---------------------------------------------------------------- pages

@pytest.mark.parametrize("path", ["/", "/tts", "/stt", "/history"])
def test_pages_render(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b"Speech Studio" in response.data


def test_unknown_page_is_404(client):
    assert client.get("/nope").status_code == 404


def test_security_headers(client):
    headers = client.get("/").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"


# ---------------------------------------------------------------- TTS

def test_tts_success_json(client, app, fake_tts):
    r = client.post("/tts", data={"text": "hello", "language": "en"}, headers=AJAX)
    body = r.get_json()
    assert r.status_code == 200 and body["success"]
    assert os.path.isfile(os.path.join(app.config["GENERATED_AUDIO_FOLDER"], body["filename"]))
    assert body["txt_url"].endswith(body["filename"])
    assert db.stats(app.config["DATABASE"])["tts"] == 1


def test_tts_success_html_form(client, fake_tts):
    r = client.post("/tts", data={"text": "hello", "language": "en"})
    assert r.status_code == 200
    assert b"Speech Output Generated" in r.data


@pytest.mark.parametrize("data, message", [
    ({"text": "   ", "language": "en"}, "enter some text"),
    ({"text": "x" * 2001, "language": "en"}, "too long"),
    ({"text": "hi", "language": "xx"}, "Unsupported language"),
])
def test_tts_validation(client, fake_tts, data, message):
    r = client.post("/tts", data=data, headers=AJAX)
    assert r.status_code == 400
    assert message in r.get_json()["error"]


def test_tts_validation_redirects_without_ajax(client):
    r = client.post("/tts", data={"text": "", "language": "en"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/tts")


def test_tts_service_failure_is_graceful(client, app, monkeypatch):
    def boom(text, lang, path):
        raise SpeechError("The text-to-speech service could not be reached.", status=502)
    monkeypatch.setattr("app.generate_speech", boom)
    r = client.post("/tts", data={"text": "hi", "language": "en"}, headers=AJAX)
    assert r.status_code == 502
    assert "could not be reached" in r.get_json()["error"]
    assert db.stats(app.config["DATABASE"])["total"] == 0


def test_unexpected_error_does_not_leak_details(client, monkeypatch):
    def boom(text, lang, path):
        raise RuntimeError("secret internal path C:\\private")
    monkeypatch.setattr("app.generate_speech", boom)
    r = client.post("/tts", data={"text": "hi", "language": "en"}, headers=AJAX)
    assert r.status_code == 500
    assert "private" not in r.get_json()["error"]


# ---------------------------------------------------------------- STT

def test_stt_upload_success(client, app, fake_stt):
    r = client.post("/stt", data=wav_upload(), headers=AJAX, content_type="multipart/form-data")
    body = r.get_json()
    assert r.status_code == 200 and body["transcription"] == "hello world"
    stored = os.listdir(app.config["UPLOAD_FOLDER"])
    assert stored == [body["filename"]]  # temp WAV was cleaned up
    assert body["filename"].startswith("upload_") and body["filename"].endswith("_clip.wav")


def test_stt_rejects_bad_extension(client, fake_stt):
    r = client.post("/stt", data=wav_upload("evil.exe"), headers=AJAX, content_type="multipart/form-data")
    assert r.status_code == 400 and "Unsupported format" in r.get_json()["error"]


def test_stt_rejects_missing_file(client):
    r = client.post("/stt", data={"language": "en"}, headers=AJAX)
    assert r.status_code == 400


def test_stt_rejects_bad_language(client, fake_stt):
    data = wav_upload()
    data["language"] = "xx"
    r = client.post("/stt", data=data, headers=AJAX, content_type="multipart/form-data")
    assert r.status_code == 400


def test_stt_filename_is_sanitised(client, app, fake_stt):
    r = client.post("/stt", data=wav_upload("../../etc/pass wd.wav"), headers=AJAX,
                    content_type="multipart/form-data")
    name = r.get_json()["filename"]
    assert "/" not in name and ".." not in name and " " not in name
    assert os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], name))


def test_stt_failure_removes_upload(client, app, fake_stt, monkeypatch):
    def nope(path, lang):
        raise SpeechError("No speech detected.", status=422)
    monkeypatch.setattr("app.transcribe_audio", nope)
    r = client.post("/stt", data=wav_upload(), headers=AJAX, content_type="multipart/form-data")
    assert r.status_code == 422
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == []
    assert db.stats(app.config["DATABASE"])["total"] == 0


def test_stt_too_large(tmp_path):
    app = create_app({"TESTING": True, "CSRF_ENABLED": False, "MAX_CONTENT_LENGTH": 1024,
                      "UPLOAD_FOLDER": str(tmp_path / "u"), "GENERATED_AUDIO_FOLDER": str(tmp_path / "g"),
                      "DATABASE": str(tmp_path / "d.db"), "LOG_FILE": None})
    r = app.test_client().post("/stt", data=wav_upload(data=b"x" * 5000), headers=AJAX,
                               content_type="multipart/form-data")
    assert r.status_code == 413
    assert "too large" in r.get_json()["error"]


# ---------------------------------------------------------------- recording

def test_record_success(client, app, fake_stt):
    data = {"audio_data": (io.BytesIO(b"webmdata"), "recording.webm", "audio/webm;codecs=opus"),
            "language": "ta"}
    r = client.post("/record", data=data, content_type="multipart/form-data")
    body = r.get_json()
    assert r.status_code == 200 and body["success"]
    assert body["filename"].startswith("record_") and body["filename"].endswith(".webm")


def test_record_empty_and_missing(client, fake_stt):
    assert client.post("/record", data={"language": "en"}).status_code == 400
    empty = {"audio_data": (io.BytesIO(b""), "recording.webm", "audio/webm"), "language": "en"}
    r = client.post("/record", data=empty, content_type="multipart/form-data")
    assert r.status_code == 400 and "empty" in r.get_json()["error"]


# ---------------------------------------------------------------- downloads

def make_tts(client):
    return client.post("/tts", data={"text": "Hello world", "language": "en"}, headers=AJAX).get_json()


def test_downloads(client, fake_tts):
    body = make_tts(client)
    audio = client.get(body["audio_url"])
    assert audio.status_code == 200 and audio.data == b"ID3fake"
    txt = client.get(body["txt_url"])
    assert txt.data == b"Hello world"
    pdf = client.get(body["pdf_url"])
    assert pdf.data.startswith(b"%PDF")


def test_pdf_handles_non_latin_text(client, fake_tts):
    body = client.post("/tts", data={"text": "வணக்கம் " * 50, "language": "ta"}, headers=AJAX).get_json()
    assert client.get(body["pdf_url"]).data.startswith(b"%PDF")


@pytest.mark.parametrize("url", [
    "/download/audio/..%2F..%2Fapp.py",
    "/download/upload/..%5C..%5Capp.py",
    "/download/audio/.env",
    "/download/audio/a%00b.mp3",
])
def test_download_path_traversal_blocked(client, url):
    assert client.get(url).status_code in (400, 404)


def test_download_missing_and_invalid(client):
    assert client.get("/download/audio/nothing.mp3").status_code == 404
    assert client.get("/download/txt/nothing.mp3").status_code == 404
    assert client.get("/download/zip/file.mp3").status_code == 400


# ---------------------------------------------------------------- history

def test_history_search_filter_and_xss_escaping(client, fake_tts):
    client.post("/tts", data={"text": "<script>alert(1)</script> apple", "language": "en"}, headers=AJAX)
    client.post("/tts", data={"text": "banana", "language": "en"}, headers=AJAX)
    page = client.get("/history").data
    assert b"<script>alert(1)</script>" not in page
    assert b"&lt;script&gt;" in page
    only = client.get("/history?search=banana").data
    assert b"banana" in only and b"apple" not in only
    assert b"banana" not in client.get("/history?operation=STT").data


def test_history_search_wildcards_are_literal(app):
    db.add_conversion(app.config["DATABASE"], "TTS", "100% sure", "a.mp3", "en")
    db.add_conversion(app.config["DATABASE"], "TTS", "other", "b.mp3", "en")
    assert len(db.search(app.config["DATABASE"], "%")) == 1
    assert len(db.search(app.config["DATABASE"], "_")) == 0


def test_delete_item_removes_file(client, app, fake_tts):
    body = make_tts(client)
    path = os.path.join(app.config["GENERATED_AUDIO_FOLDER"], body["filename"])
    assert os.path.exists(path)
    item = db.search(app.config["DATABASE"])[0]
    r = client.post(f"/delete/{item['id']}")
    assert r.status_code == 302
    assert not os.path.exists(path)
    assert db.stats(app.config["DATABASE"])["total"] == 0


def test_delete_unknown_item(client):
    assert client.post("/delete/999").status_code == 302


def test_clear_history(client, app, fake_tts):
    make_tts(client)
    make_tts(client)
    client.post("/clear-history")
    assert db.stats(app.config["DATABASE"])["total"] == 0
    assert os.listdir(app.config["GENERATED_AUDIO_FOLDER"]) == []


# ---------------------------------------------------------------- CSRF

def test_csrf_enforced(tmp_path):
    app = create_app({"TESTING": True, "CSRF_ENABLED": True,
                      "UPLOAD_FOLDER": str(tmp_path / "u"), "GENERATED_AUDIO_FOLDER": str(tmp_path / "g"),
                      "DATABASE": str(tmp_path / "d.db"), "LOG_FILE": None})
    client = app.test_client()
    assert client.post("/clear-history", headers=AJAX).status_code == 400
    page = client.get("/history").data.decode()
    token = page.split('name="csrf-token" content="')[1].split('"')[0]
    ok = client.post("/clear-history", data={"csrf_token": token})
    assert ok.status_code == 302
