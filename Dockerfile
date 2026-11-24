FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg is required by pydub to decode uploaded/recorded audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser . .
RUN mkdir -p uploads generated_audio && chown -R appuser:appuser /app
USER appuser

EXPOSE 10000
# Render injects PORT; 10000 is its default and the local fallback.
CMD gunicorn "app:create_app()" --bind 0.0.0.0:${PORT:-10000} --workers 1 --timeout 120