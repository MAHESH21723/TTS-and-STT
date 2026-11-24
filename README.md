# Speech Studio

A small Flask web app that converts **text to speech** and **speech to text**. Type text and hear it spoken in ten languages, or upload / record audio in the browser and get a transcription. Every conversion is saved to a searchable history with MP3, TXT and PDF downloads.

Built by Maheshwaran as a Python showcase project.

## Features

- **Text-to-speech**: up to 2,000 characters, 10 languages (English, Spanish, French, German, Hindi, Tamil, Italian, Portuguese, Japanese, Chinese), in-page player, download as MP3, TXT or PDF.
- **Speech-to-text from a file**: WAV, MP3, M4A, WebM, OGG and FLAC up to 16 MB (configurable). Non-WAV formats are converted with FFmpeg.
- **Speech-to-text from the microphone**: record in the browser (MediaRecorder API), with a timer, a 3-minute cap and clear recording / transcribing / error states.
- **History**: SQLite log with search, filter by type, quick play, details view and delete (files are removed from disk too).
- **Safe by default**: CSRF protection, server-side validation of size, type, language and text length, unique sanitised file names, path-traversal-proof downloads, escaped output, no debug mode, localhost-only binding, and generic messages instead of stack traces.
- **Graceful failures**: if the online speech services or FFmpeg are unavailable, the UI shows a clear message instead of an error page.

## Tech stack

Python 3.10+, Flask, SQLite, [gTTS](https://pypi.org/project/gTTS/) (text-to-speech), [SpeechRecognition](https://pypi.org/project/SpeechRecognition/) with the Google Web Speech API (speech-to-text), pydub + FFmpeg (audio conversion), fpdf2 (PDF export), Bootstrap 5 and vanilla JavaScript. Tests use pytest.

> Both speech engines call free online Google endpoints, so an internet connection is required for conversions. Audio and text you convert are sent to those services.

## Setup

Requirements: Python 3.10 or newer, and [FFmpeg](https://ffmpeg.org/download.html) on your `PATH` (needed for everything except `.wav` uploads; the app shows a notice if it is missing).

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Optional configuration: copy `.env.example` to `.env` and edit it (secret key, port, upload limit). Everything has a safe default.

## Run

```bash
python app.py
```

Open <http://127.0.0.1:5000>. The `uploads/` and `generated_audio/` folders and the SQLite database are created on first start.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests mock gTTS, the Google recogniser and FFmpeg, so they run offline and need no microphone.

## Project structure

```
app.py                  Flask application factory, routes, security hooks
modules/
  tts_engine.py         gTTS wrapper and the supported-language table
  stt_engine.py         SpeechRecognition wrapper
  audio_processor.py    extension checks, FFmpeg detection, conversion to WAV
  database.py           SQLite history queries
  documents.py          TXT / PDF export
  errors.py             SpeechError: failures with user-safe messages
templates/              Jinja2 pages (dashboard, TTS, STT, history)
static/                 CSS and JavaScript (main.js, recorder.js)
tests/                  pytest suite
```

## Notes and limitations

- The PDF export uses a built-in font that covers Latin characters only; other scripts (for example Tamil) appear as `?` in the PDF. The TXT export keeps the full text.
- This is a local, single-user tool and has no user accounts.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Maheshwaran.
