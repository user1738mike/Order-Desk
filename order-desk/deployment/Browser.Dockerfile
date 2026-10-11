# Acceptance tooling only; never included in the serving image.
FROM node:24.15.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium libnss3-tools ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /checks
COPY deployment/browser.mjs /checks/browser.mjs
COPY frontend /frontend
ENV HOME=/tmp/browser-home
USER 1000:1000
CMD ["node", "/checks/browser.mjs"]
