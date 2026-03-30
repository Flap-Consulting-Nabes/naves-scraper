#!/bin/bash
# Lanza el dashboard Streamlit.

cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
