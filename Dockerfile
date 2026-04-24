# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .

# All pinned packages ship manylinux wheels (psycopg2-binary, PyMuPDF,
# pillow, pydantic_core), so we don't need gcc/libpq-dev. BuildKit cache
# mount keeps downloaded wheels between builds.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

EXPOSE 8001
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
