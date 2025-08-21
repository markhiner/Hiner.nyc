#!/usr/bin/env python3
from __future__ import annotations

import os, re, html, json, subprocess
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, request, Response, abort

# ===== ENV =====
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
REPO_DIR    = os.environ.get("REPO_DIR")
BASIC_USER  = os.environ.get("BASIC_AUTH_USER")
BASIC_PASS  = os.environ.get("BASIC_AUTH_PASS")
SITE_BASE   = os.environ.get("SITE_BASE", "https://hiner.nyc")

# Hard-wired hotel filters
BRANDS_PARAM = "84,7,41,118,256,26,136,289,2,3"
HOTEL_CLASS  = "4,5"
SORT_BY      = "8"

if not (SERPAPI_KEY and REPO_DIR and BASIC_USER and BASIC_PASS):
    raise SystemExit("Missing env vars: SERPAPI_KEY, REPO_DIR, BASIC_AUTH_USER, BASIC_AUTH_PASS are required")

RESULTS_HOTELS  = os.path.join(REPO_DIR, "yocto", "results", "index.html")
RESULTS_FLIGHTS = os.path.join(REPO_DIR, "yocto", "fly", "results", "index.html")

LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS  = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

app = Flask(__name__)

# ===== BASIC AUTH =====
@app.before_request
def _auth():
    a = request.authorization
    if not (a and a.username == BASIC_USER and a.password == BASIC_PASS):
        return Response('Auth required', 401, {'WWW-Authenticate': 'Basic realm="yocto"'})

# ===== UTIL =====
def esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def titlecase_city(s: str) -> str:
    tokens = re.split(r"(\s|-)", s.strip().lower())
    out: List[str] = []
    for t in tokens:
        if t.strip() in ("dc","nyc","la","usa"):
            out.append(t.upper())
        elif t in (" ","-"):
            out.append(t)
        else:
            out.append(t.capitalize())
    return "".join(out)

def format_dates(ci: date, co: date) -> str:
    if ci.year != co.year:
        return f"{ci.strftime('%A, %b %-d')} - {co.strftime('%A, %b %-d, %Y')}"
    return f"{ci.strftime('%a, %b %-d')} - {co.strftime('%a, %b %-d')}"

def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def git_add_commit_push(paths: List[str]) -> Optional[str]:
    try:
        subprocess.run(["git","add",*paths], cwd=REPO_DIR, check=True)
        subprocess.run(["git","commit","-m", f"yocto results {datetime.now().isoformat(timespec='seconds')}"],
                       cwd=REPO_DIR, check=False)
        subprocess.run(["git","push","origin","HEAD"], cwd=REPO_DIR, check=True)
        return None
    except subprocess.CalledProcessError as e:
        return e.stderr or e.stdout or "git error"

# =========================
# HOTELS
# =========================
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

def extract_price_hotel(p: Dict[str, Any]) -> Optional[str]:
    v = (p.get("rate_per_night") or {}).get("lowest")
    if v in (None, "", "None"): return None
    try:
        return f"${int(round(float(v)))}"
    except Exception:
        return f"${v}"

def get_class_rating(p: Dict[str, Any]) -> int:
    cand = p.get("hotel_class") or p.get("stars") or p.get("classification") or ""
    if isinstance(cand, (int, float)):
        n = float(cand)
    else:
        m = re.search(r"(\d(?:\.\d)?)", str(cand))
        n = float(m.group(1)) if m else 0.0
    return max(0, min(5, int(round(n))))

def pick_images(p: Dict[str, Any]) -> List[str]:
    imgs = p.get("images") or []
    out: List[str] = []
    if isinstance(imgs, list):
        for im in imgs:
            u = im.get("original_image") or im.get("thumbnail") or im.get("image")
            if u: out.append(u)
    return out

def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"&", " and ", s)
    return re.sub(r"[^a-z0-9]+", "", s)

BRAND_LOGOS = {
    "conrad": "conrad.png",
    "embassysuites": "embassy_suites.png",
    "grandhyatt": "grand_hyatt.png",
    "hyattregency": "hyatt_regency.png",
    "parkhyatt": "park_hyatt.png",
    "thompson": "thompson.png",
    "jwmarriott": "jw_marriott.png",
    "renaissance": "renaissance.png",
    "residenceinn": "residence_inn.png",
    "stregis": "st_regis.png",
    "ritzcarlton": "ritz_carlton.png",
    "westin": "westin.png",
    "edition": "edition.png",
    "intercontinental": "intercontinental.png",
    "kimpton": "kimpton.png",
    "mandarinoriental": "mandarin_oriental.png",
    "fourseasons": "four_seasons.png",
    "waldorfastoria": "waldorf_astoria.png",
    "whotels": "w_hotels.png",
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
def _alias(tok: str) -> str: return ALIAS.get(tok, tok)

def logo_for_property(p: Dict[str, Any]) -> str:
    name = str(p.get("name") or "")
    if name.strip().lower().startswith("w "):
        return f"{SITE_BASE}/yocto/logos/{BRAND_LOGOS['whotels']}"
    candidates = [c for c in (p.get("brand"), p.get("chain"), p.get("type"), p.get("subtype")) if c] + [name]
    for cand in candidates:
        tok = _alias(_norm(str(cand)))
        if tok in BRAND_LOGOS:
            return f"{SITE_BASE}/yocto/logos/{BRAND_LOGOS[tok]}"
        for key, fname in BRAND_LOGOS.items():
            if key in tok:
                return f"{SITE_BASE}/yocto/logos/{fname}"
        for raw, alias_key in ALIAS.items():
            if raw in tok and alias_key in BRAND_LOGOS:
                return f"{SITE_BASE}/yocto/logos/{BRAND_LOGOS[alias_key]}"
    return f"{SITE_BASE}/yocto/logos/fallback_logo.png"

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

STAR_SVG = """<svg class="star" viewBox="0 0 24 24" aria-hidden="true">
  <path d="M12 2l3.09 6.26L22 9.27l-5 4.86L18.18 22 12 18.7 5.82 22 7 14.13l-5-4.86 6.91-1.01z"
        fill="{fill}" stroke="#000" stroke-width="1.2"/>
</svg>"""

def stars_html(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        n = 0
    n = max(0, min(5, n))
    return "".join(STAR_SVG.format(fill="#FFD54A" if i < n else "none") for i in range(5))

def pick_amenities(raw: Any) -> List[str]:
    labs: List[str] = []
    if not isinstance(raw, list): return labs
    seen = set()
    def add(x):
        if x not in seen:
            labs.append(x); seen.add(x)
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
    return labs[:8]

def extract_discount(p: Dict[str, Any]) -> Optional[str]:
    for k in ("price_x_percent_lower_than_usual", "price_drop_percent", "percent_lower_than_usual", "discount_percent"):
        v = p.get(k)
        if v is None: continue
        m = re.search(r"(\d{1,3})", str(v))
        if m: return f"{m.group(1)}% lower"
    for k in ("deal", "deal_description", "price_highlight", "savings_text"):
        s = str(p.get(k) or "")
        m = re.search(r"(\d{1,3})\s*%.*lower", s, re.I)
        if m: return f"{m.group(1)}% lower"
    return None

# ===== Hotels HTML (unchanged visuals) =====
def render_hotels_html(q: str, ci_s: str, co_s: str, data: Dict[str, Any]) -> str:
    ci = parse_date(ci_s); co = parse_date(co_s)
    city_title = titlecase_city(q)
    subtitle = format_dates(ci, co)
    props = data.get("properties") or []

    cards = []
    for idx, p in enumerate(props):
        name  = esc(p.get("name") or "")
        link  = esc(p.get("link") or "#")
        gps   = p.get("gps_coordinates") or {}
        lat   = gps.get("latitude"); lon = gps.get("longitude")
        latok = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        price = esc(extract_price_hotel(p) or "—")
        stars = stars_html(get_class_rating(p))
        photos = pick_images(p)
        hero_url = esc(photos[0] if photos else "")
        logo_url = esc(logo_for_property(p))
        thumbs = [logo_url] + [esc(u) for u in photos[:8]]

        tiles = []
        for j, u in enumerate(thumbs[:9]):
            if j == 0:
                tiles.append(f"<div class='tile logo'><img src='{u}' alt='brand logo'></div>")
            else:
                tiles.append(f"<button class='tile' data-hero='hero-{idx}' data-src='{u}'><img src='{u}' alt=''></button>")
        while len(tiles) < 9: tiles.append("<div class='tile empty'></div>")
        grid_html = "".join(tiles[:9])

        amen_labels = pick_amenities(p.get("amenities") or [])
        amen_html = "".join(f"<span class='am'>{AMENITY_SVGS[l]}<span>{esc(l)}</span></span>" for l in amen_labels)

        discount_text = extract_discount(p)
        banner_html = f"<div class='deal-banner'><span>{esc(discount_text)}</span></div>" if discount_text else ""

        hero_block = ""
        if hero_url:
            hero_block = f"""
<div class="hero-wrap">
  {banner_html}
  <img id="hero-{idx}" class="hero" src="{hero_url}" alt="">
  <div class="price-badge">{price}</div>
</div>"""

        map_id = f"map-{idx}"
        map_html = f"<div id='{map_id}' class='map'></div>" if latok else ""

        card = f"""
<article class="card">
  <header class="hd">
    <a href="{link}" target="_blank" rel="noopener" class="hn">{name}</a>
    <div class="meta"><div class="stars">{stars}</div></div>
  </header>

  {hero_block}

  <div class="media">
    <div class="thumb-grid" id="thumbs-{idx}">{grid_html}</div>
    <div class="map-wrap">{map_html}</div>
  </div>

  <div class="amen-row">{amen_html}</div>
</article>
"""
        cards.append(card)

    body_cards = "\n".join(cards) if cards else "<p class='empty'>No results.</p>"

    maps = []
    for idx, p in enumerate(props):
        gps = p.get("gps_coordinates") or {}
        lat = gps.get("latitude"); lon = gps.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            maps.append({"id": f"map-{idx}", "lat": lat, "lon": lon, "name": esc(p.get("name") or f"Hotel {idx+1}")})
    maps_json = json.dumps(maps)

    GOOGLE_FONTS = '<link href="https://fonts.googleapis.com/css2?family=Sansation:wght@400;600;700&display=swap" rel="stylesheet">'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(city_title)} Hotels — {esc(subtitle)}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
{GOOGLE_FONTS}
<style>
:root{{ --bg:#0b0b0c; --line:#e5e7eb; --tile: 86px; --gap:8px; }}
*{{box-sizing:border-box}}
body{{margin:0;background:#0b0b0c;color:#111;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #eee;padding:12px 16px;z-index:5}}
.header h1{{margin:0;font-family:'Sansation',sans-serif;font-weight:700;letter-spacing:.2px}}
.header .sub{{margin-top:4px;color:#555;font-family:'Sansation',sans-serif}}

.wrap{{max-width:980px;margin:0 auto;padding:16px}}
.card{{background:#fff;color:#111;border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:14px 0;box-shadow:0 10px 30px rgba(0,0,0,.08)}}
.hd{{display:flex;align-items:flex-start;justify-content:space-between;padding:14px 14px 8px 14px;gap:10px}}
.hn{{color:#111;text-decoration:none;font-weight:700;font-size:18px}}
.meta{{display:flex;gap:12px;align-items:center}}
.stars{{display:flex;gap:2px}}
.star{{width:18px;height:18px;display:block}}
.hero-wrap{{position:relative;background:#0d0f12}}
.hero{{display:block;width:100%;height:260px;object-fit:cover}}
.price-badge{{ position:absolute;right:12px;bottom:12px;background:rgba(11,101,216,.9);color:#fff;font-family:'Sansation',sans-serif;font-weight:600;padding:8px 12px;border-radius:10px;font-size:16px }}
.deal-banner{{ position:absolute;left:0;right:0;top:0;height:28px;background:#FFD54A;color:#111;display:flex;align-items:center;justify-content:flex-end;font-family:'Sansation',sans-serif;font-weight:600;font-size:13px;padding:0 10px }}

.media{{display:grid;grid-template-columns:auto auto;gap:12px;padding:12px 14px}}
.thumb-grid{{ --size: calc(var(--tile)*3 + var(--gap)*2); width: var(--size) }}
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

@media (max-width: 740px){{ .media{{grid-template-columns:1fr}} .thumb-grid, .map-wrap{{width:100%}} .thumb-grid{{ --tile: calc((100% - 2*var(--gap))/3) }} .map{{height: calc((var(--tile)*3 + var(--gap)*2))}} }}
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
document.querySelectorAll('.tile[data-src]').forEach(btn => {{
  btn.addEventListener('click', (e) => {{
    e.preventDefault();
    const heroId = btn.getAttribute('data-hero');
    const src = btn.getAttribute('data-src');
    const hero = document.getElementById(heroId);
    if (hero && src) hero.src = src;
  }});
}});
const entries = {maps_json};
entries.forEach((it) => {{
  const el = document.getElementById(it.id);
  if (!el) return;
  const m = L.map(it.id, {{ zoomControl: false, attributionControl: false }}).setView([it.lat, it.lon], 14);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19 }}).addTo(m);
  L.marker([it.lat, it.lon]).addTo(m).bindPopup(it.name);
}});
</script>
</body>
</html>"""

# =========================
# FLIGHTS (new layout with plate + big codes + plane art)
# =========================
def serpapi_flights(dep_ids: str, arr_ids: str, date_str: str, class_code: str) -> Dict[str, Any]:
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_flights",
        "gl": "us",
        "hl": "en",
        "currency": "USD",
        "type": "2",  # one-way
        "departure_id": dep_ids,
        "arrival_id": arr_ids,
        "outbound_date": date_str,
        "travel_class": class_code,  # 1=econ, 2=prem, 3=bus, 4=first
        "api_key": SERPAPI_KEY,
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def mm_to_hhmm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h}:{m:02d}"

def map_airport_field(s: str) -> str:
    t = (s or "").strip().lower()
    if not t: return ""
    if t == "home": return "GSO,RDU"
    if t == "nyc":  return "LGA,JFK,EWR"
    if t == "mia":  return "MIA,FLL"
    if re.fullmatch(r"[a-z]{3}(?:,[a-z]{3})*", t):
        return ",".join(code.upper() for code in t.split(","))
    return t.upper()

def class_to_code(s: str) -> str:
    t = (s or "").strip().lower()
    if t in ("first","f"): return "4"
    if t in ("business","j","c"): return "3"
    if t in ("premium","prem","pe"): return "2"
    return "1"

# STRICT 24h hh:mm only
def to_24h(s: Optional[str]) -> str:
    if not s: return ""
    t = " ".join(str(s).strip().split())
    m = re.search(r'(\d{1,2})(?::(\d{2}))\s*([APap][Mm])', t)
    if m:
        h = int(m.group(1)); mnt = int(m.group(2))
        ampm = m.group(3).lower()
        if ampm == "pm" and h != 12: h += 12
        if ampm == "am" and h == 12: h = 0
        return f"{h:02d}:{mnt:02d}"
    m = re.search(r'\b(\d{1,2})\s*([APap][Mm])\b', t)
    if m:
        h = int(m.group(1)); mnt = 0
        ampm = m.group(2).lower()
        if ampm == "pm" and h != 12: h += 12
        if ampm == "am" and h == 12: h = 0
        return f"{h:02d}:{mnt:02d}"
    m = re.search(r'\b(\d{1,2}):(\d{2})\b', t)
    if m:
        h = int(m.group(1)); mnt = int(m.group(2))
        if 0 <= h < 24: return f"{h:02d}:{mnt:02d}"
    return ""

# Pretty aircraft names (conventional)
def aircraft_pretty(name: Optional[str]) -> str:
    s = (name or "").lower()
    if not s: return ""
    # Airbus
    if "a321" in s:
        return "A321neo" if "neo" in s else "A321"
    if "a220-300" in s or ("a220" in s and "300" in s): return "A220-300"
    if "a220-100" in s or ("a220" in s and "100" in s): return "A220-100"
    for a in ("319","320","330","350"):
        if f"a{a}" in s: return f"A{a}"
    # Boeing
    if "767-400" in s or ("767" in s and "400" in s): return "B767-400"
    if "767-300" in s or ("767" in s and "300" in s): return "B767-300"
    if "757-300" in s or ("757" in s and "300" in s): return "B757-300"
    if "757-200" in s or ("757" in s and "200" in s): return "B757-200"
    if "787-10"  in s or ("787" in s and "10" in s):  return "B787-10"
    if "787-9"   in s or ("787" in s and "9" in s):   return "B787-9"
    if "787-8"   in s or ("787" in s and "8" in s):   return "B787-8"
    if "737" in s:
        if "900" in s or "max 9" in s: return "B737-900"
        if "800" in s or "max 8" in s: return "B737-800"
        if "700" in s:                 return "B737-700"
        return "B737"
    # CRJ / Embraer
    if "crj" in s:
        if "900" in s: return "CRJ 900"
        if "700" in s: return "CRJ 700"
        if "200" in s: return "CRJ 200"
        return "CRJ"
    m = re.search(r"(e|erj)[\s-]?(\d{3})", s)
    if m: return f"E{m.group(2)}"
    # fallback: strip vendor words & upcase
    s2 = re.sub(r"(boeing|airbus|embraer|bombardier|canadair|\bseries\b)", "", s)
    s2 = re.sub(r"[^a-z0-9\- ]", "", s2).strip().upper()
    return s2 or (name or "")

# Airline → big horizontal plane art (top layer)
AIRLINE_PLANE = {
    "american": "aa_plane.png",
    "delta":    "dl_plane.png",
    "united":   "ua_plane.png",
}
def plane_strip_url(name: Optional[str]) -> Optional[str]:
    s = (name or "").lower()
    if "american" in s: return f"{SITE_BASE}/yocto/logos/{AIRLINE_PLANE['american']}"
    if "delta"    in s: return f"{SITE_BASE}/yocto/logos/{AIRLINE_PLANE['delta']}"
    if "united"   in s: return f"{SITE_BASE}/yocto/logos/{AIRLINE_PLANE['united']}"
    return None

# Airline name → IATA (for DL123, UA45, etc.)
AIRLINE_IATA = {
    "american": "AA",
    "delta": "DL",
    "united": "UA",
    "jetblue": "B6",
    "spirit": "NK",
    "frontier": "F9",
    "alaska": "AS",
}
def airline_code(name: str) -> str:
    s = (name or "").lower()
    for k,v in AIRLINE_IATA.items():
        if k in s: return v
    return (name[:2] or "").upper()

def flights_from_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for bucket in ("best_flights", "other_flights"):
        for it in data.get(bucket) or []:
            segs = it.get("flights") or []
            if not segs: continue
            first, last = segs[0], segs[-1]
            dep_code = (first.get("departure_airport") or {}).get("id") or ""
            arr_code = (last.get("arrival_airport") or {}).get("id") or ""
            dep_time = to_24h((first.get("departure_airport") or {}).get("time"))
            arr_time = to_24h((last.get("arrival_airport") or {}).get("time"))
            airline  = first.get("airline") or ""
            total    = it.get("total_duration")
            lays = []
            for l in it.get("layovers") or []:
                lay_min = 0
                try: lay_min = int(l.get("duration") or 0)
                except: pass
                lays.append({
                    "id": l.get("id") or l.get("name") or "",
                    "dur": mm_to_hhmm(lay_min) if lay_min else None
                })
            legs = []
            for seg in segs:
                legs.append({
                    "dep": (seg.get("departure_airport") or {}).get("id") or "",
                    "arr": (seg.get("arrival_airport") or {}).get("id") or "",
                    "dep_time": to_24h((seg.get("departure_airport") or {}).get("time")),
                    "arr_time": to_24h((seg.get("arrival_airport") or {}).get("time")),
                    "plane": aircraft_pretty(seg.get("airplane")),
                    "num": seg.get("flight_number") or "",
                    "carrier": seg.get("airline") or "",
                })
            out.append({
                "price": it.get("price"),
                "dep_code": dep_code, "arr_code": arr_code,
                "dep_time": dep_time, "arr_time": arr_time,
                "airline": airline,
                "layovers": lays,
                "legs": legs,
                "total": mm_to_hhmm(total) if isinstance(total, int) else None,
            })
    return out

def render_flights_html(dep_disp: str, arr_disp: str, date_str: str, data: Dict[str, Any], class_disp: str = "first") -> str:
    items = flights_from_json(data)
    title = f"{esc(dep_disp.upper())} → {esc(arr_disp.upper())}"
    try:
        subtitle = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a, %b %-d")
    except ValueError:
        subtitle = esc(date_str)

    cards = []
    for f in items:
        # Header bits
        price = f.get("price")
        price_txt = f"${int(price):,}" if isinstance(price, int) else (f"${price}" if price else "—")
        big_codes = f"{esc(f['dep_code'])} ► {esc(f['arr_code'])}"
        cls_txt   = "First Class" if (class_disp or '').lower().startswith("f") else "Main"

        # Build leg table rows
        leg_rows = []
        for lg in f.get("legs") or []:
            code = airline_code(lg.get("carrier",""))
            flno = f"{code}{str(lg['num']).strip()}"
            row = f"""
            <div class="legline">
              <div class="cell t">{esc(lg['dep_time'])}</div>
              <div class="cell t">{esc(lg['arr_time'])}</div>
              <div class="cell code">{esc(lg['dep'])}</div>
              <div class="cell code">{esc(lg['arr'])}</div>
              <div class="cell cls">{esc(cls_txt)}</div>
              <div class="cell plane">{esc(lg['plane'])}</div>
            </div>
            """
            leg_rows.append(row)
        legs_html = "\n".join(leg_rows)

        # Layover line(s)
        lay_html = ""
        for l in f.get("layovers") or []:
            if l.get("dur") and l.get("id"):
                lay_html += f"<div class='lay'>Connect in {esc(str(l['id']))} <span>{esc(l['dur'])}</span></div>"

        # Plane art (top layer)
        plane_url = plane_strip_url(f.get("airline"))
        plane_html = f"<img class='plane' src='{esc(plane_url)}' alt=''>" if plane_url else ""

        card = f"""
<article class="fc">
  <div class="plate"></div>
  <div class="codes">{big_codes}</div>
  <div class="pane">
    <div class="grid">
      {legs_html}
      {lay_html}
    </div>
    <div class="price">{esc(price_txt)}</div>
  </div>
  {plane_html}
</article>
"""
        cards.append(card)

    body = "\n".join(cards) if cards else "<p class='empty'>No flights found.</p>"

    # NOTE: fonts served locally from /yocto/fonts/
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title} — {subtitle}</title>
<style>
@font-face {{
  font-family: 'AntonCustom';
  src:
    url('{SITE_BASE}/yocto/fonts/Anton.woff2') format('woff2'),
    url('{SITE_BASE}/yocto/fonts/Anton.ttf') format('truetype'),
    url('{SITE_BASE}/yocto/fonts/Anton.otf') format('opentype'),
    url('{SITE_BASE}/yocto/fonts/Anton.rtf') format('truetype'); /* harmless if not a font */
  font-weight: 700 900;
  font-style: normal;
  font-display: swap;
}}
@font-face {{
  font-family: 'AcuminCond';
  src:
    url('{SITE_BASE}/yocto/fonts/acumin-pro-condensed.woff2') format('woff2'),
    url('{SITE_BASE}/yocto/fonts/acumin-pro-condensed.otf') format('opentype');
  font-weight: 300 900;
  font-style: normal;
  font-display: swap;
}}

:root{{ --blue:#2b2f8f; --off:#F5F2ED; --ink:#000; }}
*{{box-sizing:border-box}}
body{{margin:0;background:#93c5fd; /* sky */ color:var(--ink); font-family:'AcuminCond', system-ui, -apple-system, Arial, sans-serif}}
.header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #eee;padding:10px 16px;z-index:5}}
.header h1{{margin:0 0 2px 0;font-family:'AcuminCond';font-weight:800;letter-spacing:.5px}}
.header .sub{{color:#333}}

.wrap{{max-width:980px;margin:0 auto;padding:20px 16px 60px}}

.fc{{
  position:relative;
  height: 360px;
  border-radius:28px;
  overflow:hidden;
  margin:24px 0;
}}
.fc .plate{{
  position:absolute; inset:0;
  background: url('{SITE_BASE}/yocto/logos/card_bg.png') center/cover no-repeat;
}}
.fc .codes{{
  position:absolute; left:28px; right:28px; top:12px;
  font-family:'AntonCustom', Impact, sans-serif;
  font-weight:900; letter-spacing:2px; color:#fff; /* set to #fff for high contrast on blue plate */
  font-size: clamp(44px, 10vw, 84px);
  line-height: .9;
  text-shadow: 0 2px 0 rgba(0,0,0,.25);
  display:flex; align-items:flex-start; gap:16px;
}}
.fc .pane{{
  position:absolute; left:28px; right:28px; bottom:22px;
  background: rgba(255,255,255,.96);
  border-radius:14px;
  padding:12px 14px 60px 14px; /* extra bottom room for price label */
  border:1px solid rgba(0,0,0,.06);
}}
.fc .grid{{ display:block }}
.fc .legline{{
  display:grid; grid-template-columns:60px 60px 56px 56px 1fr 110px;
  column-gap:20px; align-items:center;
  padding:8px 2px; border-bottom:1px solid rgba(0,0,0,.08);
  font-family:'AcuminCond'; font-weight:700; font-size:17px;
}}
.fc .legline:last-of-type{{ border-bottom:none }}
.fc .cell.t{{ font-variant-numeric: tabular-nums; }}
.fc .cell.code{{ letter-spacing:.5px }}
.fc .cell.cls{{ text-align:left }}
.fc .cell.plane{{ text-align:right }}

.fc .lay{{
  margin-top:8px;
  font-family:'AcuminCond'; font-weight:800;
}}
.fc .lay span{{ color:#d00; margin-left:6px }}

.fc .price{{
  position:absolute; left:14px; bottom:10px;
  font-family:'AntonCustom'; font-size:38px; color:#fff;
  text-shadow: 0 2px 0 rgba(0,0,0,.35);
}}

.fc .plane{{
  position:absolute; right:0; left:0; top:18px; height:180px;
  object-fit:contain; object-position:right center; z-index:5;
  pointer-events:none; user-select:none;
}}

@media (max-width:720px){{
  .fc{{ height: 380px }}
  .fc .legline{{ grid-template-columns:52px 52px 52px 52px 1fr 92px; column-gap:12px; font-size:16px }}
}}
</style>
</head>
<body>
<div class="header">
  <h1>{esc(dep_disp.upper())} → {esc(arr_disp.upper())}</h1>
  <div class="sub">{esc(subtitle)}</div>
</div>
<div class="wrap">
{body}
<div style="text-align:center;color:#222;font-size:12px;margin:18px 0;">
  Published to <a href="{SITE_BASE}/yocto/fly/results/" style="color:#111">{SITE_BASE}/yocto/fly/results/</a>
</div>
</div>
</body>
</html>"""

# =========================
# ROUTES
# =========================
@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/run")
def run_hotels():
    where = (request.args.get("where") or request.args.get("q") or "").strip()
    when  = (request.args.get("when") or request.args.get("check_in_date") or "").strip()
    nights_str = (request.args.get("nights") or "1").strip()
    if not where or not when: abort(400, "Missing 'where' or 'when'")
    try:
        nights = max(1, int(nights_str))
        ci = parse_date(when); co = ci + timedelta(days=nights)
    except Exception:
        abort(400, "Invalid 'when' (YYYY-MM-DD) or 'nights'")
    ci_s, co_s = ci.isoformat(), co.isoformat()
    data = serpapi_hotels(where, ci_s, co_s)
    html_out = render_hotels_html(where, ci_s, co_s, data)
    write_file(RESULTS_HOTELS, html_out)
    _ = git_add_commit_push(["yocto/results/index.html"])
    return Response(html_out, mimetype="text/html")

@app.get("/fly/run")
def run_flights():
    dep_disp = (request.args.get("departure") or "").strip()
    arr_disp = (request.args.get("arrival") or "").strip()
    date_str = (request.args.get("date") or "").strip()
    cls      = (request.args.get("class") or "first").strip()
    if not dep_disp or not arr_disp or not date_str:
        abort(400, "Missing 'departure', 'arrival', or 'date'")
    dep_ids = map_airport_field(dep_disp)
    arr_ids = map_airport_field(arr_disp)
    class_code = class_to_code(cls)
    data = serpapi_flights(dep_ids, arr_ids, date_str, class_code)
    html_out = render_flights_html(dep_disp, arr_disp, date_str, data, cls)
    write_file(RESULTS_FLIGHTS, html_out)
    _ = git_add_commit_push(["yocto/fly/results/index.html"])
    return Response(html_out, mimetype="text/html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False)
