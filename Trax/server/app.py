import os
import json
import time
from pathlib import Path
import requests
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Boot
# -------------------------------------------------------------------
load_dotenv()

OPENSKY_CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID", "").strip()
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "").strip()
INSECURE_SSL = os.getenv("OPENSKY_INSECURE_SSL", "0") == "1"

ALLOWED_PIN = os.getenv("TRAX_ALLOWED_PIN", "4242").strip()
AIRLINES_DIR = Path(os.getenv("TRAX_STATIC_AIRLINES_DIR", "../site/assets/airlines")).resolve()

if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
    raise RuntimeError("Missing OpenSky credentials in environment (OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET).")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

SESSION = requests.Session()
SESSION.auth = (OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET)
if INSECURE_SSL:
    SESSION.verify = False

# -------------------------------------------------------------------
# Airlines data (normalized)
# -------------------------------------------------------------------
_AIRLINES = None
_AIRLINES_BY_ICAO = {}
_AIRLINES_BY_IATA = {}
_LAST_AIRLINES_MTIME = 0

def _normalize_airlines_payload(payload):
    """
    Accept any of:
      1) {"airlines": [ {...}, {...} ]}
      2) [ {...}, {...} ]
      3) {"DAL": {...}, "AA": {...}}  # dict keyed by code
    Return a dict: {"airlines": [records...]} with ICAO/IATA uppercased.
    """
    def clean(rec):
        r = dict(rec or {})
        if "icao" in r and r["icao"]:
            r["icao"] = str(r["icao"]).strip().upper()
        if "iata" in r and r["iata"]:
            r["iata"] = str(r["iata"]).strip().upper()
        # tolerate alternate color key names
        if "primary_color" not in r and "color" in r and r["color"]:
            r["primary_color"] = r["color"]
        return r

    if isinstance(payload, dict) and isinstance(payload.get("airlines"), list):
        return {"airlines": [clean(x) for x in payload["airlines"]]}

    if isinstance(payload, list):
        return {"airlines": [clean(x) for x in payload]}

    if isinstance(payload, dict):
        return {"airlines": [clean(v) for v in payload.values()]}

    return {"airlines": []}

def _load_airlines():
    """Load and index airlines from airlines.json (any shape; normalize)."""
    global _AIRLINES, _AIRLINES_BY_ICAO, _AIRLINES_BY_IATA, _LAST_AIRLINES_MTIME

    _AIRLINES_BY_ICAO = {}
    _AIRLINES_BY_IATA = {}

    p = AIRLINES_DIR / "airlines.json"
    if not p.exists():
        _AIRLINES = {"airlines": []}
        _LAST_AIRLINES_MTIME = 0
        app.logger.warning("airlines.json not found at %s", p)
        return

    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    _AIRLINES = _normalize_airlines_payload(raw)

    for a in _AIRLINES.get("airlines", []):
        icao = (a.get("icao") or "").strip().upper()
        iata = (a.get("iata") or "").strip().upper()
        if icao:
            _AIRLINES_BY_ICAO[icao] = a
        if iata:
            _AIRLINES_BY_IATA[iata] = a

    _LAST_AIRLINES_MTIME = p.stat().st_mtime
    app.logger.info("Loaded %d airlines from %s", len(_AIRLINES["airlines"]), p)

def _reload_airlines_if_changed():
    """Hot-reload airlines if the file mtime changes."""
    global _LAST_AIRLINES_MTIME
    p = AIRLINES_DIR / "airlines.json"
    try:
        m = p.stat().st_mtime
        if m != _LAST_AIRLINES_MTIME:
            _load_airlines()
    except FileNotFoundError:
        pass

def _airline_for_callsign(callsign: str):
    """
    Resolve airline by callsign prefix.
    OpenSky 'callsign' often begins with ICAO (3 letters). Sometimes IATA (2).
    Try ICAO first, then IATA.
    """
    if not callsign:
        return None
    cs = callsign.strip().upper()

    # ICAO: 3 letters
    if len(cs) >= 3:
        icao = cs[:3]
        if icao in _AIRLINES_BY_ICAO:
            return _AIRLINES_BY_ICAO[icao]

    # IATA: 2 letters
    if len(cs) >= 2:
        iata = cs[:2]
        if iata in _AIRLINES_BY_IATA:
            return _AIRLINES_BY_IATA[iata]

    return None

# Initial load
_load_airlines()

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "ts": int(time.time())})

@app.route("/api/airlines.json")
def airlines_json():
    _reload_airlines_if_changed()
    return jsonify(_AIRLINES or {"airlines": []})

@app.route("/api/airline/icon/<code>")
def airline_icon(code):
    """
    Serve small 1:1 icon by ICAO/IATA code (PNG).
    Filenames expected under {AIRLINES_DIR}/icons/<CODE>.png
    """
    code = (code or "").upper().strip()
    icons_dir = AIRLINES_DIR / "icons"
    if not icons_dir.exists():
        abort(404)
    candidate = icons_dir / f"{code}.png"
    if candidate.exists():
        return send_from_directory(icons_dir, candidate.name, mimetype="image/png", max_age=3600)
    abort(404)

@app.route("/api/airline/logo/<code>")
def airline_logo(code):
    """
    Serve rectangular banner logo by ICAO/IATA code (PNG).
    Filenames expected under {AIRLINES_DIR}/logos/<CODE>.png
    """
    code = (code or "").upper().strip()
    logos_dir = AIRLINES_DIR / "logos"
    if not logos_dir.exists():
        abort(404)
    candidate = logos_dir / f"{code}.png"
    if candidate.exists():
        return send_from_directory(logos_dir, candidate.name, mimetype="image/png", max_age=3600)
    abort(404)

@app.route("/api/states")
def states():
    """
    Proxy to OpenSky `states/all`.
    Optional query:
      - bbox=minLat,minLon,maxLat,maxLon  (mapped to lamin,lomin,lamax,lomax)
    Enrich results with airline info + asset URLs + primary color.
    """
    # Gate with PIN header
    pin = request.headers.get("X-TRAX-PIN", "").strip()
    if pin != ALLOWED_PIN:
        return jsonify({"error": "Forbidden"}), 403

    base = "https://opensky-network.org/api/states/all"
    params = {}

    bbox = request.args.get("bbox")
    if bbox:
        try:
            minLat, minLon, maxLat, maxLon = map(float, bbox.split(","))
            params["lamin"] = minLat
            params["lomin"] = minLon
            params["lamax"] = maxLat
            params["lomax"] = maxLon
        except Exception:
            return jsonify({"error": "Invalid bbox"}), 400

    try:
        r = SESSION.get(base, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return jsonify({"error": "OpenSky request failed", "detail": str(e)}), 502

    _reload_airlines_if_changed()

    states = data.get("states") or []
    enriched = []

    # OpenSky states array indices (documented):
    # 0: icao24
    # 1: callsign
    # 2: origin_country
    # 5: longitude
    # 6: latitude
    # 9: baro_altitude
    # 10: on_ground
    # 13: geo_altitude
    # 14: squawk
    for s in states:
        try:
            callsign = (s[1] or "").strip()
            lon = s[5]
            lat = s[6]
        except Exception:
            continue

        if lat is None or lon is None:
            continue

        al = _airline_for_callsign(callsign)
        code_for_assets = None
        primary_color = None
        airline_name = None
        iata = None
        icao = None

        if al:
            iata = (al.get("iata") or "").upper() or None
            icao = (al.get("icao") or "").upper() or None
            airline_name = al.get("name") or None
            primary_color = (al.get("primary_color") or "#666666").strip()
            # prefer ICAO for filenames; fallback to IATA
            code_for_assets = icao or iata

        enriched.append({
            "icao24": s[0],
            "callsign": callsign,
            "lat": lat,
            "lon": lon,
            "baro_altitude": s[9],
            "on_ground": s[10],
            "geo_altitude": s[13],
            "squawk": s[14],
            "airline": {
                "name": airline_name,
                "iata": iata,
                "icao": icao,
                "primary_color": primary_color,
                "icon_url": f"/api/airline/icon/{code_for_assets}" if code_for_assets else None,
                "logo_url": f"/api/airline/logo/{code_for_assets}" if code_for_assets else None
            }
        })

    return jsonify({
        "time": data.get("time"),
        "count": len(enriched),
        "states": enriched
    })

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
if __name__ == "__main__":
    # Bind to all interfaces so ngrok can reach it
    app.run(host="0.0.0.0", port=5055, debug=False)