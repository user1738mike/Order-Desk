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
# A live error stream does not reach EOF between requests. Require prompt output
# with its input pipe still open; an EOF-only test misses mawk input buffering.
coproc REDACTOR { exec /usr/bin/awk -W interactive -f /etc/nginx/redact-errors.awk; }
redactor_pid=$REDACTOR_PID
printf '%s\n' '[error] client intended to send too large body PRIVATE-MARKER' >&"${REDACTOR[1]}"
IFS= read -r -t 5 first_line <&"${REDACTOR[0]}"
[[ "$first_line" == '{"event":"proxy_diagnostic","level":"error","category":"request_body_limit"}' ]]
kill -TERM "$redactor_pid"
wait "$redactor_pid" || true
printf '%s\n' 'PASS: diagnostic redaction preserves only allowlisted fields.'
