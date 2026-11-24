"""Speech Studio: a small Flask app for text-to-speech and speech-to-text."""
from __future__ import annotations

import io
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from dotenv import load_dotenv
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from modules import database as db
from modules.audio_processor import ALLOWED_EXTENSIONS, allowed_file, check_ffmpeg, convert_to_wav, extension_of
from modules.documents import build_pdf, conversion_text
from modules.errors import SpeechError
from modules.stt_engine import LANGUAGE_LOCALES, transcribe_audio
from modules.tts_engine import MAX_TEXT_LENGTH, SUPPORTED_LANGUAGES, generate_speech

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_NOTICE = "Public demo: data is shared and resets, don't enter personal information."
DEMO_FILE_MAX_AGE = 60 * 60  # seconds; demo-mode audio files are pruned after an hour
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
STORED_PREFIX = re.compile(r"^(?:upload|record)_\d{8}_\d{6}_[0-9a-f]{6}_")
RECORDING_TYPES = (("wav", "wav"), ("ogg", "ogg"), ("mp4", "m4a"), ("webm", "webm"))

logger = logging.getLogger(__name__)


def configure_logging(log_file: Optional[str]) -> None:
    """Log to the console and, if ``log_file`` is given, to a rotating file."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def create_app(test_config: Optional[dict[str, Any]] = None) -> Flask:
    """Application factory. ``test_config`` overrides settings (used by the tests)."""
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    app = Flask(__name__)
    app.config.update(
        # A random key per start is a safe default; set SECRET_KEY to keep sessions across restarts.
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "16")) * 1024 * 1024,
        UPLOAD_FOLDER=os.path.join(BASE_DIR, "uploads"),
        GENERATED_AUDIO_FOLDER=os.path.join(BASE_DIR, "generated_audio"),
        DATABASE=os.path.join(BASE_DIR, "speech_studio.db"),
        LOG_FILE=os.path.join(BASE_DIR, "speech_studio.log"),
        CSRF_ENABLED=True,
    )
    on_render = bool(os.environ.get("RENDER"))
    if on_render:
        # Behind Render's HTTPS proxy: trust one hop of X-Forwarded-* headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["LOG_FILE"] = None  # log to the console; Render collects it
    app.config["DEMO_DATA"] = os.environ.get("DEMO_DATA") == "1"
    if test_config:
        app.config.update(test_config)

    if not app.config.get("TESTING"):
        configure_logging(app.config["LOG_FILE"])
    for folder in (app.config["UPLOAD_FOLDER"], app.config["GENERATED_AUDIO_FOLDER"]):
        os.makedirs(folder, exist_ok=True)
    db.init_db(app.config["DATABASE"])

    register_hooks(app)
    register_routes(app)
    return app


# --------------------------------------------------------------------------- helpers

def wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path == "/record"


def fail(message: str, status: int = 400, endpoint: str = "index"):
    """Answer a failed request as JSON (AJAX) or as a flash message plus redirect."""
    if wants_json():
        return jsonify(success=False, error=message), status
    flash(message, "danger")
    return redirect(url_for(endpoint))


def new_name(prefix: str, ext: str, original: str = "") -> str:
    """Unique, filesystem-safe name such as ``upload_20260101_120000_ab12cd_song.mp3``."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [prefix, stamp, uuid.uuid4().hex[:6]]
    if original:
        parts.append(secure_filename(os.path.splitext(original)[0])[:60] or "audio")
    return "_".join(parts) + f".{ext}"


def prune_old_files(app: Flask) -> None:
    """Demo mode only: delete uploads and generated audio older than an hour."""
    cutoff = time.time() - DEMO_FILE_MAX_AGE
    for key in ("UPLOAD_FOLDER", "GENERATED_AUDIO_FOLDER"):
        for entry in os.scandir(app.config[key]):
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    os.remove(entry.path)
            except OSError:
                logger.warning("Could not prune %s", entry.path)


def remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not delete %s", path, exc_info=True)


def audio_path(app: Flask, row) -> str:
    folder = app.config["GENERATED_AUDIO_FOLDER" if row["operation_type"] == "TTS" else "UPLOAD_FOLDER"]
    return os.path.join(folder, db.audio_filename(row))


def result_urls(filename: str, audio_type: str) -> dict[str, str]:
    return {
        "audio_url": url_for("download_file", file_type=audio_type, filename=filename),
        "txt_url": url_for("download_file", file_type="txt", filename=filename),
        "pdf_url": url_for("download_file", file_type="pdf", filename=filename),
        "filename": filename,
    }


def transcribe_saved_file(app: Flask, input_path: str, lang: str) -> str:
    """Convert ``input_path`` to WAV, transcribe it and always clean up the temp WAV."""
    wav_path = os.path.join(app.config["UPLOAD_FOLDER"], f"tmp_{uuid.uuid4().hex}.wav")
    try:
        convert_to_wav(input_path, wav_path)
        return transcribe_audio(wav_path, lang)
    finally:
        remove_quietly(wav_path)


# --------------------------------------------------------------------------- hooks

def register_hooks(app: Flask) -> None:
    @app.template_filter("display_name")
    def display_name(stored: str) -> str:
        """Strip the generated prefix from a stored upload name for display."""
        return STORED_PREFIX.sub("", stored)

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {
            "languages": SUPPORTED_LANGUAGES,
            "ffmpeg_available": check_ffmpeg(),
            "csrf_token": session["csrf"],
            "max_text_length": MAX_TEXT_LENGTH,
            "demo_mode": app.config["DEMO_DATA"],
            "demo_notice": DEMO_NOTICE,
            "max_upload_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        }

    @app.before_request
    def prune_demo_files():
        if app.config["DEMO_DATA"] and request.method == "POST":
            prune_old_files(app)

    @app.before_request
    def check_csrf():
        if request.method != "POST" or not app.config["CSRF_ENABLED"]:
            return None
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        expected = session.get("csrf", "")
        if not expected or not secrets.compare_digest(sent, expected):
            return fail("Your session expired. Reload the page and try again.", 400)
        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return fail(f"File too large. Maximum allowed size is {limit} MB.", 413, "stt")

    @app.errorhandler(SpeechError)
    def speech_error(error: SpeechError):
        page = request.endpoint if request.endpoint in ("tts", "stt") else "index"
        return fail(error.message, error.status, page)

    @app.errorhandler(Exception)
    def unexpected(error: Exception):
        if isinstance(error, HTTPException):
            if wants_json():
                return jsonify(success=False, error=error.description), error.code
            return error
        logger.exception("Unhandled error")
        return fail("Something went wrong on the server. Please try again.", 500)


# --------------------------------------------------------------------------- routes

def register_routes(app: Flask) -> None:
    dbpath = lambda: app.config["DATABASE"]  # noqa: E731

    @app.route("/")
    def index():
        return render_template("index.html", stats=db.stats(dbpath()))

    @app.route("/tts", methods=["GET", "POST"])
    def tts():
        if request.method == "GET":
            return render_template("tts.html", text="", selected_lang="en")

        text = request.form.get("text", "").strip()
        lang = request.form.get("language", "en")
        if not text:
            return fail("Please enter some text.", 400, "tts")
        if len(text) > MAX_TEXT_LENGTH:
            return fail(f"Text is too long (maximum {MAX_TEXT_LENGTH} characters).", 400, "tts")
        if lang not in SUPPORTED_LANGUAGES:
            return fail("Unsupported language selected.", 400, "tts")

        filename = new_name("tts", "mp3")
        generate_speech(text, lang, os.path.join(app.config["GENERATED_AUDIO_FOLDER"], filename))
        db.add_conversion(dbpath(), "TTS", text, filename, lang)

        if wants_json():
            return jsonify(success=True, text=text, language=SUPPORTED_LANGUAGES[lang],
                           **result_urls(filename, "audio"))
        flash("Speech generated successfully.", "success")
        return render_template("tts.html", text=text, selected_lang=lang, audio_file=filename)

    @app.route("/stt", methods=["GET", "POST"])
    def stt():
        if request.method == "GET":
            return render_template("stt.html", selected_lang="en")

        file = request.files.get("audio_file")
        lang = request.form.get("language", "en")
        if file is None or not file.filename:
            return fail("Please choose an audio file.", 400, "stt")
        if not allowed_file(file.filename):
            return fail("Unsupported format. Allowed: " + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".", 400, "stt")
        if lang not in LANGUAGE_LOCALES:
            return fail("Unsupported language selected.", 400, "stt")

        stored = new_name("upload", extension_of(file.filename), file.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
        file.save(path)
        try:
            transcription = transcribe_saved_file(app, path, lang)
        except Exception:
            remove_quietly(path)
            raise
        db.add_conversion(dbpath(), "STT", stored, transcription, lang)

        if wants_json():
            return jsonify(success=True, transcription=transcription,
                           language=SUPPORTED_LANGUAGES[lang], **result_urls(stored, "upload"))
        flash("Audio transcribed successfully.", "success")
        return render_template("stt.html", transcription=transcription, selected_lang=lang, audio_file=stored)

    @app.route("/record", methods=["POST"])
    def record():
        """Receive a browser MediaRecorder blob and transcribe it."""
        file = request.files.get("audio_data")
        lang = request.form.get("language", "en")
        if file is None:
            return fail("No recording was received.")
        if lang not in LANGUAGE_LOCALES:
            return fail("Unsupported language selected.")

        mime = (file.content_type or "").lower()
        ext = next((e for key, e in RECORDING_TYPES if key in mime), "webm")
        stored = new_name("record", ext)
        path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
        file.save(path)
        if os.path.getsize(path) == 0:
            remove_quietly(path)
            return fail("The recording was empty. Please try again.")
        try:
            transcription = transcribe_saved_file(app, path, lang)
        except Exception:
            remove_quietly(path)
            raise
        db.add_conversion(dbpath(), "STT", stored, transcription, lang)
        return jsonify(success=True, transcription=transcription,
                       language=SUPPORTED_LANGUAGES[lang], **result_urls(stored, "upload"))

    @app.route("/history")
    def history():
        search = request.args.get("search", "").strip()
        operation = request.args.get("operation", "").strip()
        rows = db.search(dbpath(), search, operation)
        return render_template("history.html", history=rows, search=search, operation_filter=operation)

    @app.route("/delete/<int:item_id>", methods=["POST"])
    def delete_item(item_id: int):
        row = db.get(dbpath(), item_id)
        if row is None:
            flash("History item not found.", "danger")
        else:
            remove_quietly(audio_path(app, row))
            db.delete(dbpath(), item_id)
            flash("Record deleted.", "success")
        return redirect(url_for("history"))

    @app.route("/clear-history", methods=["POST"])
    def clear_history():
        for row in db.search(dbpath()):
            remove_quietly(audio_path(app, row))
        db.delete_all(dbpath())
        flash("History cleared.", "success")
        return redirect(url_for("history"))

    @app.route("/download/<string:file_type>/<string:filename>")
    def download_file(file_type: str, filename: str):
        # Only plain file names are accepted; this rejects any path component.
        if not SAFE_NAME.fullmatch(filename) or secure_filename(filename) != filename:
            return "Invalid file name.", 400

        if file_type in ("audio", "upload"):
            folder = app.config["GENERATED_AUDIO_FOLDER" if file_type == "audio" else "UPLOAD_FOLDER"]
            if not os.path.isfile(os.path.join(folder, filename)):
                return "File not found.", 404
            return send_from_directory(folder, filename, as_attachment=True)

        if file_type not in ("txt", "pdf"):
            return "Invalid download type.", 400
        row = db.find_by_filename(dbpath(), filename)
        if row is None:
            return "No record found for this file.", 404

        if file_type == "txt":
            data = io.BytesIO(conversion_text(row).encode("utf-8"))
            return send_file(data, mimetype="text/plain; charset=utf-8", as_attachment=True,
                             download_name=f"transcription_{row['id']}.txt")
        language = SUPPORTED_LANGUAGES.get(row["language"], row["language"])
        return send_file(io.BytesIO(build_pdf(row, language)), mimetype="application/pdf",
                         as_attachment=True, download_name=f"transcription_{row['id']}.pdf")


if __name__ == "__main__":
    create_app().run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
