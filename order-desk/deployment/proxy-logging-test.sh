#!/bin/bash
set -euo pipefail
actual=$(printf '%s\n' \
    '2026/10/24 [error] client intended to send too large body, request: PRIVATE-MARKER' \
    '2026/10/24 [warn] upstream timed out, referrer: PRIVATE-MARKER' \
    'PRIVATE-MARKER including quotes " and line controls' \
    | /usr/bin/awk -f /etc/nginx/redact-errors.awk)
expected='{"event":"proxy_diagnostic","level":"error","category":"request_body_limit"}
{"event":"proxy_diagnostic","level":"warn","category":"upstream_timeout"}
{"event":"proxy_diagnostic","level":"unknown","category":"unclassified"}'
[[ "$actual" == "$expected" ]]
printf '%s\n' 'PASS: diagnostic redaction preserves only allowlisted fields.'
