FROM postgres:18.6-bookworm
# Debian-maintained age package, authenticated by signed APT metadata.
# Use only the standard X25519 recipient; no plugins or SSH identities.
RUN rm -f /etc/apt/sources.list.d/pgdg.list /etc/apt/sources.list.d/pgdg.sources && apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=30 update && apt-get install -y --no-install-recommends python3 age=1.1.1-1+b3 && rm -rf /var/lib/apt/lists/*
COPY deployment/recovery.py /recovery.py
ENTRYPOINT ["python3", "/recovery.py"]
