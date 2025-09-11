import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from flask import Flask, request, jsonify, send_from_directory, abort, redirect
from flask_cors import CORS
from dotenv import load_dotenv

# Boot / Env

load_dotenv()

OPENSKY_CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID", "").strip()
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "").strip()
INSECURE_SSL = os.getenv("OPENSKY_INSECURE_SSL", "0") == "1"

ALLOWED_PIN = os.getenv("TRAX_ALLOWED_PIN", "4242").strip()

# Project layout
SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parent
SITE_DIR = REPO_ROOT / "site"
TRAX_DIR = SITE_DIR / "trax"
AIRLINES_DIR = Path(os.getenv("TRAX_STATIC_AIRLINES_DIR", str(SITE_DIR / 
"assets" / "airlines"))).resolve()

if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
    raise RuntimeError("Missing OpenSky credentials in environment.")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

SESSION = requests.Session()
SESSION.auth = (OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET)
if INSECURE_SSL:
    SESSION.verify = False

# Airlines data (normalized, hot-reloaded)

_AIRLINES: Dict[str, Any] = {"airlines": []}
_AIRLINES_BY_ICAO: Dict[str, Dict[str, Any]] = {}
_AIRLINES_BY_IATA: Dict[str, Dict[str, Any]] = {}
_LAST_AIRLINES_MTIME: float = 0.0


def _normalize_airlines_payload(payload: Any) -> Dict[str, List[Dict[str, 
Any]]]:
    def clean(rec):
        r = dict(rec or {})
        if "icao" in r and r["icao"]:
            r["icao"] = str(r["icao"]).strip().upper()
        if "iata" in r and r["iata"]:
            r["iata"] = str(r["iata"]).strip().upper()
        if "primary_color" not in r and r.get("color"):
            r["primary_color"] = r["color"]
        return r

    if isinstance(payload, dict) and isinstance(payload.get("airlines"), 
list):
        return {"airlines": [clean(x) for x in payload["airlines"]]}

    if isinstance(payload, list):
        return {"airlines": [clean(x) for x in payload]}

    if isinstance(payload, dict):
        return {"airlines": [clean(v) for v in payload.values()]}

    return {"airlines": []}


def _index_airlines():
    global _AIRLINES_BY_ICAO, _AIRLINES_BY_IATA
    _AIRLINES_BY_ICAO = {}
    _AIRLINES_BY_IATA = {}
    for a in _AIRLINES.get("airlines", []):
        icao = (a.get("icao") or "").strip().upper()
        iata = (a.get("iata") or "").strip().upper()
        if icao:
            _AIRLINES_BY_ICAO[icao] = a
        if iata:
            _AIRLINES_BY_IATA[iata] = a


def _load_airlines():
    global _AIRLINES, _LAST_AIRLINES_MTIME
    p = AIRLINES_DIR / "airlines.json"
    if not p.exists():
        _AIRLINES = {"airlines": []}
        _LAST_AIRLINES_MTIME = 0
        app.logger.warning("airlines.json not found at %s", p)
        _index_airlines()
        return

    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    _AIRLINES = _normalize_airlines_payload(raw)
    _LAST_AIRLINES_MTIME = p.stat().st_mtime
    _index_airlines()
    app.logger.info("Loaded %d airlines from %s", 
len(_AIRLINES["airlines"]), p)


def _reload_airlines_if_changed():
    global _LAST_AIRLINES_MTIME
    p = AIRLINES_DIR / "airlines.json"
    try:
        m = p.stat().st_mtime
        if m != _LAST_AIRLINES_MTIME:
            _load_airlines()
    except FileNotFoundError:
        pass


def _airline_for_callsign(callsign: str) -> Optional[Dict[str, Any]]:
    if not callsign:
        return None
    cs = callsign.strip().upper()
    if len(cs) >= 3 and cs[:3] in _AIRLINES_BY_ICAO:
        return _AIRLINES_BY_ICAO[cs[:3]]
    if len(cs) >= 2 and cs[:2] in _AIRLINES_BY_IATA:
        return _AIRLINES_BY_IATA[cs[:2]]
    return None


# Initial load
_load_airlines()

# API routes

@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "ts": int(time.time())})


@app.route("/api/airlines.json")
def airlines_json():
    _reload_airlines_if_changed()
    return jsonify(_AIRLINES or {"airlines": []})


def _find_airline_record(code_or_name: str) -> Optional[Dict[str, Any]]:
    if not code_or_name:
        return None
    c = code_or_name.strip().upper()
    if c in _AIRLINES_BY_ICAO:
        return _AIRLINES_BY_ICAO[c]
    if c in _AIRLINES_BY_IATA:
        return _AIRLINES_BY_IATA[c]
    n = code_or_name.strip().lower()
    for a in _AIRLINES.get("airlines", []):
        if (a.get("name") or "").strip().lower() == n:
            return a
    return None


def _send_airline_asset(subdir: str, code_or_name: str):
    _reload_airlines_if_changed()
    a = _find_airline_record(code_or_name)

    candidates: List[str] = []
    if a:
        icao = (a.get("icao") or "").upper()
        iata = (a.get("iata") or "").upper()
        for base in filter(None, [icao, iata]):
            for ext in (".png", ".svg", ".jpg", ".jpeg", ".webp"):
                candidates.append(f"{base}{ext}")

    literal = (code_or_name or "").strip()
    if literal:
        base = literal.rsplit(".", 1)[0]
        for ext in (".png", ".svg", ".jpg", ".jpeg", ".webp"):
            candidates.append(f"{base.upper()}{ext}")

    root = AIRLINES_DIR / subdir
    for fname in candidates:
        p = root / fname
        if p.exists():
            ext = p.suffix.lower()
            mime = {
                ".png": "image/png",
                ".svg": "image/svg+xml",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(ext, "application/octet-stream")
            return send_from_directory(root, p.name, mimetype=mime, 
max_age=3600)
    abort(404)


@app.route("/api/airline/icon/<code_or_name>")
def airline_icon(code_or_name):
    return _send_airline_asset("icons", code_or_name)


@app.route("/api/airline/logo/<code_or_name>")
def airline_logo(code_or_name):
    return _send_airline_asset("logos", code_or_name)


@app.route("/api/states")
def states():
    pin = request.headers.get("X-TRAX-PIN", "").strip()
    if pin != ALLOWED_PIN:
        return jsonify({"error": "Forbidden"}), 403

    base = "https://opensky-network.org/api/states/all"
    params: Dict[str, Any] = {}

    bbox = request.args.get("bbox")
    if bbox:
        try:
            minLat, minLon, maxLat, maxLon = map(float, bbox.split(","))
            params.update({"lamin": minLat, "lomin": minLon, "lamax": 
maxLat, "lomax": maxLon})
        except Exception:
            return jsonify({"error": "Invalid bbox"}), 400

    try:
        r = SESSION.get(base, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return jsonify({"error": "OpenSky request failed", "detail": 
str(e)}), 502

    _reload_airlines_if_changed()

    states_in = data.get("states") or []
    enriched = []
    for s in states_in:
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
                "icon_url": f"/api/airline/icon/{code_for_assets}" if 
code_for_assets else None,
                "logo_url": f"/api/airline/logo/{code_for_assets}" if 
code_for_assets else None
            }
        })

    return jsonify({
        "time": data.get("time"),
        "count": len(enriched),
        "states": enriched
    })


# Static site: /trax and /assets

@app.route("/")
def root():
    return redirect("/trax/", code=302)


@app.route("/trax/")
@app.route("/trax/<path:path>")
def trax(path: str = "index.html"):
    target = (TRAX_DIR / path).resolve()
    base = TRAX_DIR.resolve()
    if base not in target.parents and target != base:
        abort(404)
    if target.is_dir():
        target = target / "index.html"
    if not target.exists():
        abort(404)
    return send_from_directory(base, str(target.relative_to(base)), 
max_age=60)


@app.route("/assets/<path:filename>")
def site_assets(filename: str):
    base = (SITE_DIR / "assets").resolve()
    target = (base / filename).resolve()
    if base not in target.parents and target != base:
        abort(404)
    if not target.exists():
        abort(404)
    return send_from_directory(base, str(target.relative_to(base)), 
max_age=3600)


# Main

if __name__ == "__main__":
    port = int(os.getenv("TRAX_PORT", "5055"))
    app.run(host="0.0.0.0", port=port, debug=False)
