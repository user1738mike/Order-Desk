#!/bin/bash
# Supervise the redactor and Nginx together: losing private logging stops serving.
set -euo pipefail
umask 077
log_directory=$(mktemp -d /tmp/orderdesk-proxy.XXXXXXXX)
error_pipe="$log_directory/errors"
filter_pid=''
nginx_pid=''
cleanup() {
    trap - EXIT TERM INT
    if [[ -n "$nginx_pid" ]]; then
        kill -TERM "$nginx_pid" 2>/dev/null || true
        wait "$nginx_pid" 2>/dev/null || true
    fi
    if [[ -n "$filter_pid" ]]; then
        kill -TERM "$filter_pid" 2>/dev/null || true
        wait "$filter_pid" 2>/dev/null || true
    fi
    rm -f -- "$error_pipe"
    rmdir -- "$log_directory"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
mkfifo -- "$error_pipe"
/usr/bin/awk -f /etc/nginx/redact-errors.awk < "$error_pipe" >&2 &
filter_pid=$!
/usr/sbin/nginx "$@" 2> "$error_pipe" &
nginx_pid=$!
status=0
wait -n -p finished "$nginx_pid" "$filter_pid" || status=$?
if [[ "$finished" == "$filter_pid" ]]; then
    # Do not serve without the redactor, including an unexpected clean exit.
    exit 1
fi
wait "$filter_pid" || status=$?
exit "$status"
