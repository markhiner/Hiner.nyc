# server/app.py
import os, time, logging, traceback
from flask import Flask, request, jsonify, Response, make_response
from flask_cors import CORS
import requests

# ----------------- config -----------------
OPENSKY_API_ROOT = "https://opensky-network.org/api"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
TIMEOUT = 20

CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID")
CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("opensky-proxy")

_token_cache = {"token": None, "exp": 0}

# ----------------- helpers -----------------
def json_error(status, **payload):
    resp = make_response(jsonify(payload), status)
    resp.headers["Content-Type"] = "application/json"
    return resp

@app.errorhandler(Exception)
def on_unhandled(e):
    logger.exception("Unhandled error")
    return json_error(500,
        error="proxy_internal_error",
        detail=str(e),
        traceback="".join(traceback.format_exc()).splitlines()[-5:],
    )

def relay(r: requests.Response):
    """Return upstream response, but guarantee JSON on non-JSON/empty bodies."""
    try:
        ct = r.headers.get("Content-Type", "")
    except Exception:
        ct = ""
    body = getattr(r, "content", b"") or b""
    if not body or ("text/html" in ct.lower()):
        safe = {
            "status": r.status_code,
            "content_type": ct or "unknown",
            "note": "Wrapped non-JSON from upstream",
            "text": body.decode(errors="replace")[:1200]
        }
        return json_error(r.status_code, **safe)
    return Response(body, status=r.status_code, content_type=ct or "application/json")

def fetch_token():
    """Client-credentials token fetch; cache it. If creds missing, raise cleanly."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET not set")
    # NOTE: endpoint/params per OpenSky OAuth docs; adjust if your doc differs
    url = f"{OPENSKY_API_ROOT}/v2/authenticate"
    data = {"grant_type": "client_credentials"}
    r = requests.post(url, data=data, auth=(CLIENT_ID, CLIENT_SECRET), timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"token_fetch_failed {r.status_code}: {r.text[:300]}")
    j = r.json()
    _token_cache["token"] = j.get("access_token")
    _token_cache["exp"]   = int(time.time()) + int(j.get("expires_in", 3600)) - 60
    if not _token_cache["token"]:
        raise RuntimeError("token_missing_in_response")
    logger.info("Fetched OpenSky token OK")
    return _token_cache["token"]

def get_token():
    if _token_cache["token"] and time.time() < _token_cache["exp"]:
        return _token_cache["token"]
    return fetch_token()

def proxied_get(path, params, use_auth=False):
    """GET wrapper. For /states/all we default to NO auth to avoid token issues."""
    url = f"{OPENSKY_API_ROOT}{path}"
    headers = {}
    if use_auth:
        headers = {"Authorization": f"Bearer {get_token()}"}
    logger.info("UPSTREAM GET %s params=%s auth=%s", path, params, use_auth)
    try:
        r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        # simple retry on 401 if we used auth
        if use_auth and r.status_code == 401:
            logger.warning("401 from upstream, refreshing token")
            fetch_token()
            headers = {"Authorization": f"Bearer {_token_cache['token']}"}
            r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        return r
    except requests.RequestException as e:
        logger.exception("Network error to upstream")
        return make_response(jsonify({
            "status": 599,
            "error": "network",
            "detail": str(e)
        }), 599)

# ----------------- routes -----------------
@app.route("/api/ping")
def ping():
    return jsonify(ok=True, ts=int(time.time()))

@app.route("/api/states")
def states():
    # No auth by default for states (public endpoint; rate-limited)
    allowed = {"lamin","lomin","lamax","lomax","time","icao24","extended"}
    params = {k: v for k, v in request.args.items() if k in allowed}
    r = proxied_get("/states/all", params, use_auth=False)
    # If proxied_get returned a Flask response (on network exception), just return it
    if isinstance(r, Response):
        return r
    return relay(r)

@app.route("/api/flights/arrival")
def flights_arrival():
    allowed = {"airport","begin","end"}
    params = {k: v for k, v in request.args.items() if k in allowed}
    r = proxied_get("/flights/arrival", params, use_auth=True)
    if isinstance(r, Response):
        return r
    return relay(r)

@app.route("/api/flights/departure")
def flights_departure():
    allowed = {"airport","begin","end"}
    params = {k: v for k, v in request.args.items() if k in allowed}
    r = proxied_get("/flights/departure", params, use_auth=True)
    if isinstance(r, Response):
        return r
    return relay(r)

@app.route("/api/flights/all")
def flights_all():
    allowed = {"begin","end"}
    params = {k: v for k, v in request.args.items() if k in allowed}
    r = proxied_get("/flights/all", params, use_auth=True)
    if isinstance(r, Response):
        return r
    return relay(r)

@app.route("/api/tracks")
def tracks():
    allowed = {"icao24","time"}
    params = {k: v for k, v in request.args.items() if k in allowed}
    r = proxied_get("/tracks", params, use_auth=True)
    if isinstance(r, Response):
        return r
    return relay(r)

@app.route("/")
def root():
    return Response('OK: try /api/ping, /api/states?lamin=..., UI runs on port 8000.', mimetype="text/plain")

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)