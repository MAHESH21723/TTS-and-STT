"""Render / public-demo mode."""
import os
import time

from app import DEMO_NOTICE, create_app


def make(tmp_path):
    return create_app({
        "TESTING": True,
        "CSRF_ENABLED": False,
        "SECRET_KEY": "t",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "GENERATED_AUDIO_FOLDER": str(tmp_path / "audio"),
        "DATABASE": str(tmp_path / "r.db"),
        "LOG_FILE": None,
    })


def test_render_env_sets_secure_cookies(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER", "1")
    app = make(tmp_path)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.test_client().get("/", headers={"X-Forwarded-Proto": "https"}).status_code == 200


def test_demo_banner_only_in_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DATA", "1")
    html = make(tmp_path).test_client().get("/").get_data(as_text=True)
    assert DEMO_NOTICE.replace("'", "&#39;") in html
    monkeypatch.delenv("DEMO_DATA")
    assert "Public demo" not in make(tmp_path).test_client().get("/").get_data(as_text=True)


def test_demo_mode_prunes_old_files_on_post(tmp_path, monkeypatch, fake_tts):
    monkeypatch.setenv("DEMO_DATA", "1")
    app = make(tmp_path)
    old = tmp_path / "audio" / "old.mp3"
    old.write_bytes(b"x")
    stale = time.time() - 7200
    os.utime(old, (stale, stale))
    resp = app.test_client().post("/tts", data={"text": "hi", "language": "en"})
    assert resp.status_code == 200
    assert not old.exists()