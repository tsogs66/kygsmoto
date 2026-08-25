# KYGS POS — container image.
#
# The database lives on a volume at /data so it survives image rebuilds; the
# app reads that path from KYGS_DB.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KYGS_DB=/data/kygs.db \
    PORT=8000

WORKDIR /app

# Dependencies first, so code edits do not invalidate the pip layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# Uses the stdlib rather than adding curl to the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
