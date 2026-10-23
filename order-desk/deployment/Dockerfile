FROM ghcr.io/astral-sh/uv:0.13.5 AS uv
FROM python:3.14.9-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN UV_HTTP_TIMEOUT=60 UV_HTTP_RETRIES=1 uv sync --frozen --no-dev --no-install-project

FROM dependencies AS assets
COPY backend /app
COPY frontend/assets /frontend/assets
COPY frontend/templates /frontend/templates
RUN python manage.py collectstatic --noinput --settings=config.settings.static_build

FROM assets AS quality
RUN UV_HTTP_TIMEOUT=60 UV_HTTP_RETRIES=1 uv sync --frozen --group dev --no-install-project
COPY backend/pyproject.toml /backend/pyproject.toml
COPY scripts /scripts
COPY deployment /deployment
COPY frontend /frontend
CMD ["ruff", "check", "/app", "/frontend"]

FROM python:3.14.9-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10001 orderdesk && useradd --uid 10001 --gid orderdesk --create-home orderdesk
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=assets /app /app
COPY --from=assets /frontend/templates /frontend/templates
COPY --from=assets /frontend/assets /frontend/assets
COPY --from=assets /static-output /app/var/static
COPY deployment /deployment
USER 10001:10001
CMD ["python", "/deployment/serve.py"]

FROM nginx:1.30.6 AS proxy
COPY deployment/nginx.conf /etc/nginx/nginx.conf
COPY --from=assets /static-output /srv/static
USER 101:101
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]

FROM python:3.14.9-slim-bookworm AS initialize
COPY deployment/certificates.py /certificates.py
CMD ["python", "/certificates.py"]
