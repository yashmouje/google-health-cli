#!/bin/bash
# Refreshes ghealth's OAuth token and warns if auth is broken.
# Run this on a cron (see below) as a safety net -- the real fix for
# token expiry is publishing the OAuth app in GCP Console (Testing
# mode tokens die after 7 days; Published tokens don't).
cd "$(dirname "$0")" || exit 1

if ! ./ghealth auth refresh >/tmp/ghealth_refresh.log 2>&1; then
    echo "[ghealth] token refresh FAILED at $(date). Run './ghealth auth login' to re-authenticate." >&2
    cat /tmp/ghealth_refresh.log >&2
    exit 1
fi
