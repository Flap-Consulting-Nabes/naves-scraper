#!/bin/bash
# Detiene y reinicia API y dashboard.

cd "$(dirname "$0")"
bash stop.sh
sleep 1
bash start.sh
