"""
Web dashboard for Joule — predictions, charts, and manual runs.

Run locally:
  python dashboard/app.py

Docker exposes port 8080 (see docker-compose.yml).
"""
from __future__ import annotations

import os
import sys
import threading
from functools import wraps
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request, Response

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dashboard.data_loader import (
    dashboard_status,
    load_accuracy_summary,
    load_inventory,
    load_market_context,
    load_news,
    load_predictions,
    load_price_history,
)

app = Flask(__name__, template_folder="templates", static_folder="static")

_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {"running": False, "last_result": None, "last_error": None}


def _check_auth() -> bool:
    password = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not password:
        return True
    auth = request.authorization
    user = os.getenv("DASHBOARD_USER", "admin")
    return bool(auth and auth.username == user and auth.password == password)


def _requires_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _check_auth():
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="Joule Dashboard"'},
            )
        return fn(*args, **kwargs)

    return wrapper


@app.route("/")
@_requires_auth
def index():
    return render_template("index.html")


@app.route("/api/status")
@_requires_auth
def api_status():
    return jsonify(dashboard_status())


@app.route("/api/predictions")
@_requires_auth
def api_predictions():
    return jsonify(load_predictions())


@app.route("/api/prices")
@_requires_auth
def api_prices():
    days = int(request.args.get("days", 90))
    return jsonify(load_price_history(days=days))


@app.route("/api/accuracy")
@_requires_auth
def api_accuracy():
    return jsonify(load_accuracy_summary())


@app.route("/api/news")
@_requires_auth
def api_news():
    limit = int(request.args.get("limit", 40))
    return jsonify(load_news(limit=limit))


@app.route("/api/inventory")
@_requires_auth
def api_inventory():
    return jsonify(load_inventory())


@app.route("/api/market")
@_requires_auth
def api_market():
    return jsonify(load_market_context())


@app.route("/api/run", methods=["POST"])
@_requires_auth
def api_run():
    with _run_lock:
        if _run_state["running"]:
            return jsonify({"ok": False, "message": "Pipeline already running"}), 409
        _run_state["running"] = True
        _run_state["last_error"] = None

    def _job():
        try:
            from prediction_engine import PredictionEngine

            engine = PredictionEngine()
            preds = engine.run_full_pipeline()
            _run_state["last_result"] = {
                "ok": bool(preds),
                "generated_at": load_predictions().get("generated_at"),
            }
        except Exception as exc:
            _run_state["last_error"] = str(exc)
            _run_state["last_result"] = {"ok": False}
        finally:
            _run_state["running"] = False

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"ok": True, "message": "Pipeline started"})


@app.route("/api/run/status")
@_requires_auth
def api_run_status():
    return jsonify(_run_state)


def main():
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    debug = os.getenv("DASHBOARD_DEBUG", "false").lower() == "true"
    print(f"Joule Dashboard -> http://{host}:{port}")
    if os.getenv("DASHBOARD_PASSWORD"):
        print("Dashboard password protection: ON")
    else:
        print("Dashboard password protection: OFF (set DASHBOARD_PASSWORD for public deploy)")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()
