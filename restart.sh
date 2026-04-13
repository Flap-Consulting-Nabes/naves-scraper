#!/bin/bash
# Stops and restarts API + dashboard.

cd "$(dirname "$0")"
bash stop.sh

# Wait for port 8000 to be free (max 10s)
for i in $(seq 1 20); do
    if ! lsof -iTCP:8000 -sTCP:LISTEN -t &>/dev/null 2>&1 && \
       ! ss -tlnp 2>/dev/null | grep -q ':8000 '; then
        break
    fi
    sleep 0.5
done

bash start.sh
