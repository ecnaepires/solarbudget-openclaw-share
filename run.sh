#!/usr/bin/env bash
# Run the SolarBudget dashboard from the repo root.
# Usage: ./run.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/budget_dashboard"

if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

echo "Starting SolarBudget Dashboard..."
echo "Root:   $SCRIPT_DIR"
echo "App:    $(pwd)"
echo "Python: $PYTHON"
echo

"$PYTHON" -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
