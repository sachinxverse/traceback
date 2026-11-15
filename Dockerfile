FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Optional heavy AI extras: --build-arg INSTALL_AI=false for a slim image
ARG INSTALL_AI=true

WORKDIR /app

# B1: the PyTorch index must only apply to torch, never to the base
# requirements (the previous single command broke Flask/SQLAlchemy installs).
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_AI" = "true" ]; then \
        pip install torch --index-url https://download.pytorch.org/whl/cpu \
          || echo "torch skipped (platform wheels unavailable)"; \
        pip install open_clip_torch sentence-transformers \
          || echo "AI extras skipped"; \
    fi

COPY . .

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "4", "-b", "0.0.0.0:8000", "wsgi:app"]
