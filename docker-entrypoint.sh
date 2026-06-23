#!/bin/bash
# Docker entrypoint script for Energy AI Agent

set -e

echo "=========================================="
echo "Energy AI Agent - Starting Container"
echo "=========================================="
echo "Timezone: ${TZ:-America/New_York}"
echo "Schedule: ${PREDICTION_TIMES:-06:00,09:00,12:00,18:00} EST"
echo "=========================================="
echo ""

# Wait a bit for system to be ready
sleep 2

# Run initial data collection (if needed)
if [ ! -f "data/prices.csv" ] || [ ! -s "data/prices.csv" ]; then
    echo "Initializing data collection..."
    python scripts/backfill_eia_history.py --days 730 || true
    python scripts/fetch_prices.py || true
    python scripts/fetch_inventory.py || true
fi

# Run the scheduler
echo "Starting web dashboard..."
gunicorn --bind "0.0.0.0:${DASHBOARD_PORT:-8080}" \
  --workers 2 --threads 4 --timeout 300 \
  --chdir /app dashboard.app:app &
DASHBOARD_PID=$!
echo "Web dashboard started (PID $DASHBOARD_PID) → http://0.0.0.0:${DASHBOARD_PORT:-8080}"
echo "Starting prediction scheduler..."

exec python prediction_scheduler.py
