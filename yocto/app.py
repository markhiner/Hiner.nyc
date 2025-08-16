#!/usr/bin/env python3
from __future__ import annotations

import os, subprocess, html, json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, request, Response, abort

# ---------- Configuration via environment ----------
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")          # REQUIRED
REPO_DIR     = os.environ.get("REPO_DIR")            # REQUIRED: local path to your hiner.nyc repo
BASIC_USER   = os.environ.get("BASIC_AUTH_USER")     # REQUIRED
BASIC_PASS   = os.environ.get("BASIC_AUTH_PASS")     # REQUIRED
SITE_BASE    = os.environ.get("SITE_BASE", "https://hiner.nyc")  # optional

# Hard-wired query params (as asked)
BRANDS_PARAM = "84,7,41,118,256,26,136,289,2,3"
HOTEL_CLASS  = "4,5"
SORT_BY      = "8"

if not (SERPAPI_KEY and REPO_DIR and BASIC_USER and BASIC_PASS):
    raise SystemExit("Missing env vars: SERPAPI_KEY, REPO_DIR, BASIC_AUTH_USER, BASIC_AUTH_PASS are required")

RESULTS_FILE = os.path.join(REPO_DIR, "yocto", "results", "index.html")

app = Flask(__name__)

# ---------- Basic Auth ----------
def check_auth(auth) -> bool:
    return bool(auth and auth.username == BASIC_USER and auth.password == BASIC_PASS)

def require_auth():
    return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="yocto"'})

@app.before_request
def enforce_auth():
    auth = request.authorization
    if not check_auth(auth):
        return require_auth()

# ---------- SerpAPI ----------
def serpapi_hotels(q: str, check_in: str, check_out: str) -> Dict[str, Any]:
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_hotels",
        "q": q,
        "gl": "us",
        "hl": "en",
        "currency": "USD",
        "check_in_date": check_in,
        "check_out_date": check_out,
        "brands": BRANDS_PARAM,      # hard-wired
        "hotel_class": HOTEL_CLASS,  # hard-wired
        "sort_by": SORT_BY,          # hard-wired
        "adults": "2",
        "api_key": SERPAPI_KEY,
    }
    r = requests.get(url, params=params, timeout=45)
    r.raise_for_status()
    return r.json()

# ---------- HTML Rendering ----------
LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS  = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

AMENITY_ICONS = {
    "wifi": ('Wi-Fi', "<svg viewBox='0 0 24 24' class='amen'><path d='M12 18a2 2 0 11-.001 3.999A2 2 0 0112 18zm-8.485-5.657l1.414 1.414A9 9 0 0112 12a9 9 0 016.364 2.757l1.414-1.414A11 11 0 0012 10a11 11 0 00-8.485 2.343zM3.515 8.343l1.414 1.414A13 13 0 0112 6a13 13 0 019.071 3.757l1.414-1.414A15 15 0 0012 4a15 15 0 00-8.485 4.343z'/></svg>"),
    "pool": ('Pool', "<svg viewBox='0 0 24 24' class='amen'><path d='M2 18c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1v2c-2 0-2-1-4-1s-2 1-4 1-2-1-4-1-2 1-4 1v-2zM8 6a4 4 0 118 0v10h-2V6a2 2 0 10-4 0v10H8V6z'/></svg>"),
    "parking": ('Parking', "<svg viewBox='0 0 24 24' class='amen'><path d='M6 3h7a5 5 0 010 10H9v8H6V3zm3 3v4h4a2 2 0 100-4H9z'/></svg>"),
    "gym": ('Gym', "<svg viewBox='0 0 24 24' class='amen'><path d='M3 10h3v4H3v-4zm15 0h3v4h-3v-4zM8 9h8v6H8V9z'/></svg>"),
    "spa": ('Spa', "<svg viewBox='0 0 24 24' class='amen'><path d='M12 3C9 6 8 9 8 12s1 6 4 9c3-3 4-6 4-9s-1-6-4-9zm0 6a3 3 0 110 6 3 3 0 010-6z'/></svg>"),
    "bar": ('Bar', "<svg viewBox='0 0 24 24' class='amen'><path d='M3 3h18l-6 8v7h-6v-7L3 3z'/></svg>"),
    "restaurant": ('Restaurant', "<svg viewBox='0 0 24 24' class='amen'><path d='M7 2h2v10a2 2 0 11-4 0V2h2zm8 0h2v7h2v13h-2V11h-2V2z'/></svg>"),
    "room service": ('Room service', "<svg viewBox='0 0 24 24' class='amen'><path d='M12 5c3 0 6 2.2 7 5h3v2H2V10h3c1-2.8 4-5 7-5zm-9 9h18v2H3v-2z'/></svg>"),
    "pet": ('Pet-friendly', "<svg viewBox='0 0 24 24' class='amen'><path d='M7 11a2 2 0 11.001-3.999A2 2 0 017 11zm10 0a2 2 0 11.001-3.999A2 2 0 0117 11zM4 15c2-2 4-3 8-3s6 1 8 3l-2 4H6l-2-4z'/></svg>"),
}

def norm_amenity_name(s: str) -> str:
    t = s.strip().lower()
    if "wifi" in t or "wi-fi" in t: return "wifi"
    if "pool" in t: return "pool"
    if "parking" in t: return "parking"
    if "gym" in t or "fitness" in t: return "gym"
    if "spa" in t: return "spa"
    if "bar" in t: return "bar"
    if "restaurant" in t or "dining" in t: return "restaurant"
    if "room service" in t: return "room service"
    if "pet" in t or "dog" in t or "cat" in t: return "pet"
    return ""

def esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def extract_price(p: Dict[str, Any]) -> Optional[str]:
    v = (p.get("rate_per_night") or {}).get("lowest")
    return f"${v}" if v not in (None, "", "None") else None

def extract_deal(p: Dict[str, Any]) -> Optional[str]:
    desc = p.get("deal") or p.get("deal_description")
    if not desc: return None
    return str(desc)

def pick_images(p: Dict[str, Any]) -> (str, List[str]):
    imgs = p.get("images") or []
    if not isinstance(imgs, list): return ("", [])
    urls = []
    for im in imgs:
        u = im.get("original_image") or im.get("thumbnail") or im.get("image")
        if u: urls.append(u)
    if not urls: return ("", [])
    return (urls[0], urls[:8])

def render_html(q: str, ci: str, co: str, data: Dict[str, Any]) -> str:
    props = data.get("properties") or []
    city_disp = esc(q)
    date_disp = f"{ci} → {co}"
    cards = []

    for idx, p in enumerate(props):
        name = esc(p.get("name"))
        desc = esc(p.get("description") or "")
        rating = esc(p.get("overall_rating") or "—")
        klass = esc(p.get("hotel_class") or "—")
        price = esc(extract_price(p) or "—")
        link  = esc(p.get("link") or "#")
        lat = (p.get("gps_coordinates") or {}).get("latitude")
        lon = (p.get("gps_coordinates") or {}).get("longitude")
        latlon_ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float))

        hero, thumbs = pick_images(p)
        hero_html = f"<img src='{esc(hero)}' alt='' class='hero'>" if hero else ""

        # amenity icons (subset)
        amen_list = p.get("amenities") or []
        chosen = []
        if isinstance(amen_list, list):
            seen = set()
            for a in amen_list:
                key = norm_amenity_name(str(a))
                if key and key not in seen and key in AMENITY_ICONS:
                    seen.add(key)
                    label, svg = AMENITY_ICONS[key]
                    chosen.append(f"<span class='amen-wrap' title='{esc(label)}'>{svg}<span>{esc(label)}</span></span>")
        amen_html = "".join(chosen[:8])

        deal = extract_deal(p)
        deal_html = f"<div class='deal'>{esc(deal)}</div>" if deal else ""

        tbtns = []
        for u in thumbs:
            tbtns.append(f"<button class='thumb' data-hero='hero-{idx}' data-src='{esc(u)}'><img src='{esc(u)}' alt=''></button>")
        thumbs_html = "".join(tbtns)

        map_div = f"<div id='map-{idx}' class='map'></div>" if latlon_ok else ""

        card = f"""
        <article class="card">
          <div class="hero-wrap">
            {hero_html}
            {deal_html}
          </div>
          <div class="body">
            <header class="title">
              <a href="{link}" target="_blank" rel="noopener">{name}</a>
              <div class="meta">Class {klass} · Rating {rating} · From {price}</div>
            </header>
            <p class="desc">{desc}</p>
            <div class="thumbs" id="thumbs-{idx}">{thumbs_html}</div>
            <div class="amenities">{amen_html}</div>
            {map_div}
          </div>
        </article>
        """.replace("class='hero'", f"id='hero-{idx}' class='hero'")
        cards.append(card)

    body_cards = "\n".join(cards) if cards else "<p class='empty'>No results.</p>"

    # Map init payload
    map_entries = []
    for idx, p in enumerate(props):
        gps = p.get("gps_coordinates") or {}
        lat = gps.get("latitude"); lon = gps.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            nm = esc(p.get("name") or f"Hotel {idx+1}")
            map_entries.append({"id": f"map-{idx}", "lat": lat, "lon": lon, "name": nm})
    maps_json = json.dumps(map_entries)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Hotels — {city_disp} — {date_disp}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
html{{-webkit-text-size-adjust:100%}}
:root{{--bg:#0b0b0c;--card:#111316;--text:#e8eaed;--muted:#9aa0a6;--line:#232629;--accent:#82aaff;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:980px;margin:0 auto;padding:16px}}
.header{{position:sticky;top:0;background:rgba(11,11,12,.8);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:10px 16px;z-index:5}}
.header h1{{margin:0;font-size:18px;font-weight:600}}
.header .sub{{font-size:12px;color:var(--muted)}}
.card{{border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:14px 0;background:var(--card);box-shadow:0 10px 30px rgba(0,0,0,.25)}}
.hero-wrap{{position:relative;background:#0d0f12}}
.hero{{display:block;width:100%;height:260px;object-fit:cover}}
.deal{{position:absolute;bottom:10px;left:10px;background:#0b65d8;color:white;padding:6px 10px;border-radius:10px;font-size:12px}}
.body{{padding:14px}}
.title{{display:flex;flex-direction:column;gap:6px}}
.title a{{color:#fff;text-decoration:none;font-weight:600;font-size:18px}}
.meta{{color:var(--muted);font-size:13px}}
.desc{{margin:10px 0 6px 0;color:#cfd3d7;font-size:14px;line-height:1.35}}
.thumbs{{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}}
.thumb{{border:0;background:none;padding:0;cursor:pointer;border-radius:10px;overflow:hidden;border:1px solid var(--line)}}
.thumb img{{display:block;width:88px;height:64px;object-fit:cover}}
.amenities{{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0 12px 0}}
.amen{{width:18px;height:18px;fill:#aab2bd;vertical-align:-3px;margin-right:6px}}
.amen-wrap{{display:inline-flex;align-items:center;gap:6px;color:#cbd2d8;background:#0f1216;border:1px solid var(--line);padding:6px 8px;border-radius:999px;font-size:12px}}
.map{{height:180px;border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:10px}}
.empty{{color:var(--muted)}}
.footer{{color:#b9c1c7;font-size:12px;margin:18px 0;text-align:center}}
.leaflet-tile{{filter:grayscale(.1) brightness(.9)}}
</style>
</head>
<body>
<div class="header"><h1>Hotels — {city_disp}</h1><div class="sub">{date_disp}</div></div>
<div class="wrap">
{body_cards}
<div class="footer">Published to <a href="{SITE_BASE}/yocto/results/" style="color:#82aaff">{SITE_BASE}/yocto/results/</a></div>
</div>
<script src="{LEAFLET_JS}"></script>
<script>
// thumbnail -> hero swapper
document.querySelectorAll('.thumb').forEach(btn => {{
  btn.addEventListener('click', e => {{
    e.preventDefault();
    const heroId = btn.getAttribute('data-hero');
    const src = btn.getAttribute('data-src');
    const hero = document.getElementById(heroId);
    if (hero && src) hero.src = src;
  }});
}});
// maps
const entries = {maps_json};
entries.forEach(it => {{
  const el = document.getElementById(it.id);
  if (!el) return;
  const m = L.map(it.id, {{ zoomControl: false, attributionControl: false }}).setView([it.lat, it.lon], 14);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19 }}).addTo(m);
  L.marker([it.lat, it.lon]).addTo(m).bindPopup(it.name);
}});
</script>
</body>
</html>"""

# ---------- IO / Git ----------
def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def git(*args):
    return subprocess.run(["git", *args], cwd=REPO_DIR, check=True, capture_output=True, text=True)

def try_git_commit_push() -> Optional[str]:
    try:
        subprocess.run(["git","add","yocto/results/index.html"], cwd=REPO_DIR, check=True)
        subprocess.run(["git","commit","-m", f"yocto results {datetime.now().isoformat(timespec='seconds')}"],
                       cwd=REPO_DIR, check=False)
        out = git("push","origin","HEAD").stdout
        return out
    except subprocess.CalledProcessError as e:
        return f"git error: {e.stderr or e.stdout}"

# ---------- Routes ----------
@app.get("/health")
def health():
    return {"status":"ok"}

def parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()

@app.get("/run")
def run():
    where = (request.args.get("where") or request.args.get("q") or "").strip()
    when  = (request.args.get("when")  or request.args.get("check_in_date") or "").strip()
    nights_str = (request.args.get("nights") or "1").strip()

    if not where or not when:
        abort(400, "Missing 'where' or 'when'")
    try:
        nights = max(1, int(nights_str))
        ci = parse_date(when)
        co = ci + timedelta(days=nights)
    except Exception:
        abort(400, "Invalid 'when' (YYYY-MM-DD) or 'nights'")

    ci_s, co_s = ci.isoformat(), co.isoformat()
    data = serpapi_hotels(where, ci_s, co_s)
    html_out = render_html(where, ci_s, co_s, data)

    write_file(RESULTS_FILE, html_out)
    _ = try_git_commit_push()

    return Response(html_out, mimetype="text/html")

if __name__ == "__main__":
    # pin to IPv4 loopback; allow PORT override
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False)
