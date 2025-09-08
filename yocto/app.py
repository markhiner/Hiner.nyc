#!/usr/bin/env python3
import os
import logging
from datetime import date
from typing import Optional

from flask import Flask, request, jsonify, abort, Response

try:
    import requests  # only used if you enable proxying to an upstream
except Exception:  # pragma: no cover
    requests = None  # we’ll guard usage

# ------------------------------------------------------------------------------
# Config
# ------------------------------------------------------------------------------

PORT = int(os.getenv("PORT", "5050"))
HOST = os.getenv("HOST", "0.0.0.0")

# Toggle app-level Basic Auth (edge auth via ngrok is usually cleaner).
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "false").lower() in {"1", "true", "yes"}
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS", "password")

# Public endpoints that never require auth (add/remove as needed)
PUBLIC_PATHS = {
    "/", "/health", "/favicon.ico",
    "/fly/run", "/hotels/run",
}

# Optional upstream proxying. If set, /fly/run will forward to this URL with the
# same query params; same for hotels. Leave unset to return stub JSON.
FLY_PROXY_URL = os.getenv("FLY_PROXY_URL")         # e.g. https://real.api/fly/run
HOTELS_PROXY_URL = os.getenv("HOTELS_PROXY_URL")   # e.g. https://real.api/hotels/run
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "15"))

# ------------------------------------------------------------------------------
# App + Logging
# ------------------------------------------------------------------------------

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("yocto")

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    # allow static files if you ever add a static blueprint
    if path.startswith("/static/"):
        return True
    return False

def _check_basic_auth() -> bool:
    """Return True if Authorization header matches our BASIC_AUTH creds."""
    auth = request.authorization
    if not auth:
        return False
    return auth.username == BASIC_AUTH_USER and auth.password == BASIC_AUTH_PASS

def _require_auth_if_configured():
    """Global gate, but whitelist PUBLIC_PATHS so the UI can hit the APIs."""
    if not REQUIRE_AUTH:
        return
    if _is_public(request.path):
        return
    if _check_basic_auth():
        return
    # Ask client to present Basic auth
    return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="yocto"'})

def _proxy_get(upstream: str) -> Response:
    """Forward the current GET (query params only) to the given upstream URL."""
    if not requests:
        abort(501, description="Proxying requires 'requests' package installed.")
    try:
        r = requests.get(upstream, params=request.args, timeout=UPSTREAM_TIMEOUT)
    except Exception as e:
        log.exception("Upstream request failed")
        abort(502, description=f"Upstream error: {e}")
    # Mirror status + body + content-type
    resp = Response(r.content, r.status_code)
    ct = r.headers.get("Content-Type", "application/json; charset=utf-8")
    resp.headers["Content-Type"] = ct
    return resp

def _int_arg(name: str, default: int, min_value: int = 1) -> int:
    v = request.args.get(name, None)
    if v is None or v == "":
        return default
    try:
        i = int(v)
        if i < min_value:
            raise ValueError
        return i
    except ValueError:
        abort(400, description=f"Invalid '{name}'")

# ------------------------------------------------------------------------------
# Global gates & error handlers
# ------------------------------------------------------------------------------

@app.before_request
def _gate():
    maybe = _require_auth_if_configured()
    if maybe is not None:
        return maybe  # 401

@app.errorhandler(400)
def _bad_req(e):
    return jsonify(ok=False, error="bad_request", detail=getattr(e, "description", "")), 400

@app.errorhandler(401)
def _unauth(e):
    return jsonify(ok=False, error="unauthorized", detail="credentials required"), 401

@app.errorhandler(404)
def _not_found(e):
    return jsonify(ok=False, error="not_found", path=request.path), 404

@app.errorhandler(405)
def _method_not_allowed(e):
    return jsonify(ok=False, error="method_not_allowed"), 405

@app.errorhandler(502)
def _bad_gateway(e):
    return jsonify(ok=False, error="bad_gateway", detail=getattr(e, "description", "")), 502

@app.errorhandler(500)
def _server_error(e):
    return jsonify(ok=False, error="server_error"), 500

# ------------------------------------------------------------------------------
# Basic routes
# ------------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def root():
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>yocto</title>"
        "<style>body{background:#0b0b0b;color:#eee;font-family:system-ui;margin:40px}</style>"
        "<h1>yocto API</h1>"
        "<p>Alive. Try <code>/fly/run</code> or <code>/hotels/run</code>.</p>"
    )

@app.route("/favicon.ico")
def favicon():
    # Quiet the browser. You can serve a real icon later.
    return Response(status=204)

@app.route("/health")
def health():
    return jsonify(ok=True, status="healthy")

# ------------------------------------------------------------------------------
# Flights
# ------------------------------------------------------------------------------

@app.route("/fly/run", methods=["GET"])
def fly_run():
    """
    Expects: departure, arrival, date (YYYY-MM-DD), class (first|main)
    """
    dep = (request.args.get("departure") or "").strip().upper()
    arr = (request.args.get("arrival") or "").strip().upper()
    travel_date = (request.args.get("date") or "").strip()
    cabin = (request.args.get("class") or "first").strip().lower()

    if not dep or not arr:
        abort(400, description="Missing 'departure' or 'arrival'")

    # Optional: forward to a real upstream if configured
    if FLY_PROXY_URL:
        return _proxy_get(FLY_PROXY_URL)

    # Stub success response so your UI shows results immediately
    return jsonify({
        "ok": True,
        "type": "flight",
        "query": {"departure": dep, "arrival": arr, "date": travel_date, "class": cabin},
        "results": [
            {
                "carrier": "YO",
                "flight": "YO123",
                "depart": f"{travel_date}T08:00:00",
                "arrive": f"{travel_date}T10:05:00",
                "cabin": cabin,
                "price": 199 if cabin == "main" else 499,
            }
        ],
    })

# ------------------------------------------------------------------------------
# Hotels
# ------------------------------------------------------------------------------

@app.route("/hotels/run", methods=["GET"])
def hotels_run():
    """
    Expects: city, checkin (YYYY-MM-DD), checkout (YYYY-MM-DD), rooms, guests
    """
    city = (request.args.get("city") or "").strip().upper()
    checkin = (request.args.get("checkin") or str(date.today())).strip()
    checkout = (request.args.get("checkout") or "").strip()
    rooms = _int_arg("rooms", default=1, min_value=1)
    guests = _int_arg("guests", default=1, min_value=1)

    if not city:
        abort(400, description="Missing 'city'")

    # Optional: forward to a real upstream if configured
    if HOTELS_PROXY_URL:
        return _proxy_get(HOTELS_PROXY_URL)

    # Stub success response
    return jsonify({
        "ok": True,
        "type": "hotel",
        "query": {"city": city, "checkin": checkin, "checkout": checkout, "rooms": rooms, "guests": guests},
        "results": [
            {
                "name": f"Yocto {city} Central",
                "checkin": checkin,
                "checkout": checkout or "",
                "rooms": rooms,
                "guests": guests,
                "rate": 239,
                "currency": "USD",
            }
        ],
    })

# ------------------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting yocto API on %s:%s (REQUIRE_AUTH=%s)", HOST, PORT, REQUIRE_AUTH)
    app.run(host=HOST, port=PORT)
