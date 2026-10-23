# Never emit raw diagnostic text: Nginx can include URI, query, referrer and paths.
# Docker supplies timestamps; sanitized access logs retain request IDs/status/time.
{
    level = "unknown"
    if (match($0, /\[(emerg|alert|crit|error|warn|notice|info|debug)\]/))
        level = substr($0, RSTART + 1, RLENGTH - 2)
    text = tolower($0)
    category = "unclassified"
    if (text ~ /client intended to send too large body/) category = "request_body_limit"
    else if (text ~ /upstream timed out/) category = "upstream_timeout"
    else if (text ~ /connect\(\) failed/) category = "upstream_connect_failure"
    else if (text ~ /permission denied/) category = "permission_denied"
    else if (text ~ /no space left on device/) category = "storage_exhausted"
    else if (text ~ /ssl_do_handshake\(\) failed/) category = "tls_handshake_failure"
    else if (level == "emerg") category = "startup_failure"
    printf "{\"event\":\"proxy_diagnostic\",\"level\":\"%s\",\"category\":\"%s\"}\n", level, category
    fflush()
}
