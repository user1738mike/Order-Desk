# Release pins are deliberate. Update them together with uv.lock and verification.
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.14.8-slim-bookworm AS development

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# Fail if the committed lock is stale. No dependency resolution during startup.
RUN uv sync --locked --no-install-project

RUN groupadd --gid 10001 orderdesk \
    && useradd --uid 10001 --gid orderdesk --create-home orderdesk
COPY --chown=10001:10001 . .
USER 10001:10001
EXPOSE 8000

# This target is for local development. Production serving comes in a later step.
CMD ["python", "scripts/run_dev_server.py"]
