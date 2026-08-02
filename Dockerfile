# Health Guard API.
#
# The base image is Microsoft's Playwright image rather than a plain python one: it already
# contains Chromium and the ~80 shared libraries it needs (libnss3, libatk, libgbm, …). Installing
# those by hand on python:3.12-slim is the single most common way this deployment fails.
#
# Keep the tag in step with the `playwright` pin in apps/api/pyproject.toml. A browser built for a
# different client version fails at launch, not at build, so a mismatch only shows up at checkout.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so application edits don't invalidate the install layer.
COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/app/__init__.py /app/apps/api/app/__init__.py
RUN pip install --no-cache-dir -e /app/apps/api

COPY apps/api /app/apps/api

# Chromium is already present in the base image; this only verifies the client can find it, so a
# mismatch fails the build instead of the first real payment.
RUN python -m playwright install --dry-run chromium > /dev/null

EXPOSE 8000

# Migrations run at start rather than at build: the database is not reachable during the build.
# Bind 0.0.0.0 — the platform's router cannot reach 127.0.0.1. $PORT is injected by Railway.
CMD ["sh", "-c", "cd /app/apps/api && alembic upgrade head && cd /app && exec uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port ${PORT:-8000}"]
