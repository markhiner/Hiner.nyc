#!/usr/bin/env python3
from __future__ import annotations

import os, subprocess, html, json, re
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, request, Response, abort

# ==== CONFIG (env) ====
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
REPO_DIR    = os.environ.get("REPO_DIR")
BASIC_USER  = os.environ.get("BASIC_AUTH_USER")
BASIC_PASS  = os.environ.get("BASIC_AUTH_PASS")
SITE_BASE   = os.environ.get("SITE_BASE", "https://hiner.nyc")

# Hard-wired query params
BRANDS_PARAM = "84,7,41,118,256,26,136,289,2,3"
HOTEL_CLASS  = "4,5"
SORT_BY      = "8"

if not (SERPAPI_KEY and REPO_DIR and BASIC_USER and BASIC_PASS):
    raise SystemExit("Missing env vars: SERPAPI_KEY, REPO_DIR, BASIC_AUTH_USER, BASIC_AUTH_PASS are required")

RESULTS_FILE = os.path.join(REPO_DIR, "yocto", "results", "index.html")
LOGO_DIR     = os.path.join(REPO_DIR, "yocto", "logos")
LOGO_URLBASE = "/yocto/logos"

app = Flask(__name__)

# ==== BASIC AUTH ====
def _ok_auth(a) -> bool:
    return bool(a and a.username == BASIC_USER and a.password == BASIC_PASS)

@app.before_request
def _auth():
    a = request.authorization
    if not _ok_auth(a):
        return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="yocto"'})

# ==== SERPAPI ====
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
        "brands": BRANDS_PARAM,
        "hotel_class": HOTEL_CLASS,
        "sort_by": SORT_BY,
        "adults": "2",
        "api_key": SERPAPI_KEY,
    }
    r = requests.get(url, params=params, timeout=45)
    r.raise_for_status()
    return r.json()

# ==== UTIL ====
def esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def titlecase_city(s: str) -> str:
    # Title Case, but respect some all-caps tokens
    tokens = re.split(r"(\s|-)", s.strip().lower())
    out = []
    for t in tokens:
        if t.strip() in ("dc","nyc","la","usa"): out.append(t.upper())
        elif t in (" ","-"): out.append(t)
        else: out.append(t.capitalize())
    return "".join(out)

def format_dates(ci: date, co: date) -> str:
    # If years differ, full weekday + year on checkout, no year on checkin.
    if ci.year != co.year:
        a = ci.strftime("%A, %b %-d")
        b = co.strftime("%A, %b %-d, %Y")
        return f"{a} - {b}"
    # otherwise: Eee, Mmm Dd - Eee, Mmm Dd (no year)
    # Use locale-independent narrow weekday? We'll stick to 3-letter English
    return f"{ci.strftime('%a, %b %-d')} - {co.strftime('%a, %b %-d')}"

def extract_price(p: Dict[str, Any]) -> Optional[str]:
    v = (p.get("rate_per_night") or {}).get("lowest")
    if v in (None, "", "None"): return None
    try: return f"${int(float(v))}"
    except: return f"${v}"

def get_class_rating(p: Dict[str, Any]) -> int:
    v = p.get("hotel_class")
    try:
        n = int(round(float(v)))
        return max(0, min(5, n))
    except:
        return 0

# ==== LOGOS ====
LOGO_URLBASE = "/yocto/logos"  # served by GitHub Pages
FALLBACK_LOGO = "fallback.png"

def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"&", " and ", s)
    return re.sub(r"[^a-z0-9]+", "", s)

BRAND_LOGOS = {
    # Hilton
    "conrad":                "conrad.png",
    "embassysuites":         "embassy_suites.png",
    # Hyatt
    "grandhyatt":            "grand_hyatt.png",
    "hyattregency":          "hyatt_regency.png",
    "parkhyatt":             "park_hyatt.png",
    "thompson":              "thompson.png",
    # Marriott
    "jwmarriott":            "jw_marriott.png",
    "renaissance":           "renaissance.png",
    "residenceinn":          "residence_inn.png",
    "stregis":               "st_regis.png",
    "ritzcarlton":           "ritz_carlton.png",
    "westin":                "westin.png",
    "edition":               "edition.png",
    # IHG
    "intercontinental":      "intercontinental.png",
    "kimpton":               "kimpton.png",
    # MOHG
    "mandarinoriental":      "mandarin_oriental.png",
    # Four Seasons
    "fourseasons":           "four_seasons.png",
    # Hilton luxury standalone
    "waldorfastoria":        "waldorf_astoria.png",
    # W Hotels
    "whotels":               "w_hotels.png",
}

ALIAS = {
    "st.regis": "stregis",
    "saintregis": "stregis",
    "ritz-carlton": "ritzcarlton",
    "ritz": "ritzcarlton",
    "residenceinnbymarriott": "residenceinn",
    "residenceinnmarriott": "residenceinn",
    "four seasons": "fourseasons",
    "inter-continental": "intercontinental",
}

def _alias_or_self(tok: str) -> str:
    return ALIAS.get(tok, tok)

def logo_for_property(p: Dict[str, Any]) -> str:
    """
    Priority:
      1) Names starting with 'W ' => W Hotels (avoid Westin)
      2) brand/chain/type/subtype direct/substring matches
      3) hotel name fuzzy substring
      4) fallback.png
    """
    name = str(p.get("name") or "")
    if name.strip().lower().startswith("w "):
        return f"{LOGO_URLBASE}/{BRAND_LOGOS['whotels']}"

    candidates = [c for c in (p.get("brand"), p.get("chain"), p.get("type"), p.get("subtype")) if c] + [name]

    for cand in candidates:
        tok = _alias_or_self(_norm(str(cand)))
        if tok in BRAND_LOGOS:
            return f"{LOGO_URLBASE}/{BRAND_LOGOS[tok]}"
        for key, fname in BRAND_LOGOS.items():
            if key in tok:
                return f"{LOGO_URLBASE}/{fname}"
        for raw, alias_key in ALIAS.items():
            if raw in tok and alias_key in BRAND_LOGOS:
                return f"{LOGO_URLBASE}/{BRAND_LOGOS[alias_key]}"

    return f"{LOGO_URLBASE}/{FALLBACK_LOGO}"


# ==== AMENITIES (FILTER + ICONS + LABELS) ====
# minimal, angular icons (black strokes; filled where appropriate)
AMENITY_SVGS = {
    "Olly OK":       "<svg class='amen' viewBox='0 0 24 24'><path d='M7 11a2 2 0 110-4 2 2 0 010 4zm10 0a2 2 0 110-4 2 2 0 010 4zM4 15c2-2 4-3 8-3s6 1 8 3l-2 4H6l-2-4z' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Spa":           "<svg class='amen' viewBox='0 0 24 24'><path d='M12 3c-3 3-4 6-4 9s1 6 4 9c3-3 4-6 4-9s-1-6-4-9z' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Restaurant":    "<svg class='amen' viewBox='0 0 24 24'><path d='M7 2h2v10a2 2 0 11-4 0V2h2zm8 0h2v7h2v13h-2V11h-2V2z' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "In-Room Dining":"<svg class='amen' viewBox='0 0 24 24'><path d='M12 5c3 0 6 2 7 5h3v2H2V10h3c1-3 4-5 7-5zM3 18h18' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Bar":           "<svg class='amen' viewBox='0 0 24 24'><path d='M3 3h18l-6 8v7H9v-7L3 3z' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Pool":          "<svg class='amen' viewBox='0 0 24 24'><path d='M3 18c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Hot tub":       "<svg class='amen' viewBox='0 0 24 24'><circle cx='12' cy='12' r='5' fill='none' stroke='#000' stroke-width='1.5'/><path d='M3 18c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Beach":         "<svg class='amen' viewBox='0 0 24 24'><path d='M3 18h18M5 18c2-6 8-6 10 0' fill='none' stroke='#000' stroke-width='1.5'/><path d='M12 6c3 0 5 2 5 4' fill='none' stroke='#000' stroke-width='1.5'/></svg>",
    "Casino":        "<svg class='amen' viewBox='0 0 24 24'><rect x='4' y='4' width='16' height='16' rx='3' ry='3' fill='none' stroke='#000' stroke-width='1.5'/><circle cx='9' cy='9' r='1.5'/><circle cx='15' cy='9' r='1.5'/><circle cx='9' cy='15' r='1.5'/><circle cx='15' cy='15' r='1.5'/></svg>",
}

def pick_amenities(raw: Any) -> List[str]:
    """Return ordered list of labels to show."""
    labels: List[str] = []
    if not isinstance(raw, list): return labels
    seen = set()
    def add(label: str):
        if label not in seen:
            labels.append(label); seen.add(label)

    for a in raw:
        s = str(a).lower()
        if "pet" in s or "dog" in s or "cat" in s: add("Olly OK")
        if "spa" in s and "tub" not in s: add("Spa")
        if "restaurant" in s or "dining" in s: add("Restaurant")
        if "room service" in s: add("In-Room Dining")
        if "bar" in s or "lounge" in s: add("Bar")
        if "pool" in s: add("Pool")
        if "hot tub" in s or "whirlpool" in s or "jacuzzi" in s: add("Hot tub")
        if "beach" in s: add("Beach")
        if "casino" in s: add("Casino")

    # Keep a sane max
    return labels[:8]

# ==== STARS ====
STAR_SVG = """<svg class="star" viewBox="0 0 24 24" aria-hidden="true">
  <path d="M12 2l3.09 6.26L22 9.27l-5 4.86L18.18 22 12 18.7 5.82 22 7 14.13l-5-4.86 6.91-1.01z"
        fill="{fill}" stroke="#000" stroke-width="1.2"/>
</svg>"""

def stars_html(n: int) -> str:
    n = max(0, min(5, int(n)))
    parts = []
    for i in range(5):
        fill = "#FFD54A" if i < n else "none"
        parts.append(STAR_SVG.format(fill=fill))
    return "".join(parts)

# ==== RENDER ====
LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS  = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
GOOGLE_FONTS = (
    # Sansation for the header (as requested)
    '<link href="https://fonts.googleapis.com/css2?family=Sansation:wght@400;700&display=swap" rel="stylesheet">'
)

def pick_images(p: Dict[str, Any]) -> List[str]:
    imgs = p.get("images") or []
    out = []
    if isinstance(imgs, list):
        for im in imgs:
            u = im.get("original_image") or im.get("thumbnail") or im.get("image")
            if u: out.append(u)
    return out

def render_html(q: str, ci_s: str, co_s: str, data: Dict[str, Any]) -> str:
    ci = parse_date(ci_s); co = parse_date(co_s)
    city_title = titlecase_city(q)
    subtitle = format_dates(ci, co)

    props = data.get("properties") or []

    cards = []
    for idx, p in enumerate(props):
        name = esc(p.get("name") or "")
        gps  = p.get("gps_coordinates") or {}
        lat  = gps.get("latitude"); lon = gps.get("longitude")
        latlon_ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        price = esc(extract_price(p) or "—")
        rating_class = get_class_rating(p)
        stars = stars_html(rating_class)

        # Images
        logo_url = esc(logo_for_property(p))
        photos = pick_images(p)
        # 3x3 grid: first tile is logo, next up to 8 from photos
        thumb_urls = [logo_url] + [esc(u) for u in photos[:8]]

        # hero (use first hotel photo if present)
        hero_url = esc(photos[0] if photos else "")

        # Amenities (filtered + relabeled)
        amen_labels = pick_amenities(p.get("amenities") or [])
        amen_html = "".join(f"<span class='am'>{AMENITY_SVGS[l]}<span>{esc(l)}</span></span>" for l in amen_labels)

        # Links
        link = esc(p.get("link") or "#")

        # map container id
        map_id = f"map-{idx}"

        # thumbs grid
        tiles = []
        for j, u in enumerate(thumb_urls):
            if j == 0:
                tiles.append(f"<div class='tile logo'><img src='{u}' alt='brand logo'></div>")
            else:
                tiles.append(f"<button class='tile' data-hero='hero-{idx}' data-src='{u}'><img src='{u}' alt=''></button>")
        while len(tiles) < 9:
            tiles.append("<div class='tile empty'></div>")
        grid_html = "".join(tiles[:9])

        hero_html = f"<img id='hero-{idx}' class='hero' src='{hero_url}' alt=''>" if hero_url else ""

        card = f"""
<article class="card">
  <header class="hd">
    <a href="{link}" target="_blank" rel="noopener" class="hn">{name}</a>
    <div class="meta">
      <div class="stars">{stars}</div>
      <div class="price">{price}</div>
    </div>
  </header>

  {hero_html}

  <div class="media">
    <div class="thumb-grid" id="thumbs-{idx}">
      {grid_html}
    </div>
    <div class="map-wrap">
      {"<div id='%s' class='map'></div>" % map_id if latlon_ok else ""}
    </div>
  </div>

  <div class="amen-row">{amen_html}</div>
</article>
"""
        cards.append(card)

    body_cards = "\n".join(cards) if cards else "<p class='empty'>No results.</p>"

    # Map payload
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
<title>{esc(city_title)} Hotels — {esc(subtitle)}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
{GOOGLE_FONTS}
<style>
:root{{
  --bg:#0b0b0c; --text:#0b0b0c; --muted:#4b5563; --line:#e5e7eb;
  --card:#ffffff; --accent:#111;
  --tile: 86px; --gap:8px;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:#111;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #eee;padding:12px 16px;z-index:5}}
.header h1{{margin:0;font-family:'Sansation',sans-serif;font-weight:700;letter-spacing:.2px}}
.header .sub{{margin-top:4px;color:#555;font-family:'Sansation',sans-serif}}

.wrap{{max-width:980px;margin:0 auto;padding:16px}}
.card{{background:var(--card);color:#111;border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:14px 0;box-shadow:0 10px 30px rgba(0,0,0,.08)}}
.hd{{display:flex;align-items:flex-start;justify-content:space-between;padding:14px 14px 8px 14px;gap:10px}}
.hn{{color:#111;text-decoration:none;font-weight:700;font-size:18px}}
.meta{{display:flex;gap:12px;align-items:center}}
.stars{{display:flex;gap:2px}}
.star{{width:18px;height:18px;display:block}}
.price{{color:#111;font-weight:600}}
.hero{{display:block;width:100%;height:260px;object-fit:cover}}

.media{{display:grid;grid-template-columns:auto auto;gap:12px;padding:12px 14px}}
.thumb-grid{{--size: calc(var(--tile)*3 + var(--gap)*2); width:var(--size)}}
.thumb-grid{{display:grid;grid-template-columns:repeat(3,var(--tile));grid-auto-rows:var(--tile);gap:var(--gap)}}
.tile{{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:8px;background:#f6f7f9;padding:0}}
.tile img{{display:block;width:100%;height:100%;object-fit:cover}}
.tile.empty{{background:#fafafa}}
.tile.logo{{background:#fff;display:flex;align-items:center;justify-content:center}}
.tile.logo img{{object-fit:contain;padding:12%}}
.map-wrap{{width:calc(var(--tile)*3 + var(--gap)*2)}}
.map{{width:100%;height:calc(var(--tile)*3 + var(--gap)*2);border:1px solid var(--line);border-radius:8px;overflow:hidden}}

.amen-row{{display:flex;flex-wrap:wrap;gap:10px;padding:0 14px 14px 14px}}
.amen{{width:18px;height:18px}}
.am{{display:inline-flex;align-items:center;gap:6px;background:#f6f7f9;border:1px solid var(--line);color:#111;padding:6px 8px;border-radius:999px;font-size:12px}}

.empty{{color:#666;background:#fff;padding:20px;border-radius:12px;border:1px solid #eee}}

@media (max-width: 740px){{
  .media{{grid-template-columns:1fr}}
  .thumb-grid, .map-wrap{{width:100%}}
  .thumb-grid{{--tile: calc((100% - 2*var(--gap))/3)}}
  .map{{height: calc((var(--tile)*3 + var(--gap)*2))}}
}}
.leaflet-container .leaflet-tile{{filter:grayscale(.05) brightness(.98)}}
</style>
</head>
<body>
<div class="header">
  <h1>{esc(city_title)} Hotels</h1>
  <div class="sub">{esc(subtitle)}</div>
</div>

<div class="wrap">
{body_cards}
<div style="text-align:center;color:#555;font-size:12px;margin:18px 0;">
  Published to <a href="{SITE_BASE}/yocto/results/" style="color:#111">{SITE_BASE}/yocto/results/</a>
</div>
</div>

<script src="{LEAFLET_JS}"></script>
<script>
// thumbnail -> hero swap
document.querySelectorAll('.tile[data-src]').forEach(btn => {{
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
</html>
"""

# ==== IO / GIT ====
def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def try_git_commit_push() -> Optional[str]:
    try:
        subprocess.run(["git","add","yocto/results/index.html"], cwd=REPO_DIR, check=True)
        subprocess.run(["git","commit","-m", f"yocto results {datetime.now().isoformat(timespec='seconds')}"],
                       cwd=REPO_DIR, check=False)
        subprocess.run(["git","push","origin","HEAD"], cwd=REPO_DIR, check=True)
        return None
    except subprocess.CalledProcessError as e:
        return e.stderr or e.stdout or "git error"

# ==== ROUTES ====
@app.get("/health")
def health():
    return {"status":"ok"}

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
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False)
