# ---------- Backend: FastAPI + faster-whisper (CPU) ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/modelos

WORKDIR /app

# 1) Dependencias primero: esta capa se reutiliza mientras requirements no cambie.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

# 2) Modelo de Whisper horneado en la imagen (opcional, ver PRECARGAR_WHISPER en .env).
ARG WHISPER_MODEL=small
ARG PRECARGAR_WHISPER=true
COPY scripts/precargar_whisper.py scripts/precargar_whisper.py
RUN mkdir -p /modelos && if [ "$PRECARGAR_WHISPER" = "true" ]; then \
      python scripts/precargar_whisper.py "$WHISPER_MODEL"; \
    else echo "Whisper no precargado: se descargará en la primera transcripción local."; fi

# 3) Código. Se ejecuta con un usuario sin privilegios.
COPY . .
RUN useradd --create-home --uid 10001 app && chown -R app:app /app /modelos
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
