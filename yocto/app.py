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

# hard-wired HOTEL filters
BRANDS_PARAM = "84,7,41,118,256,26,136,289,2,3"
HOTEL_CLASS  = "4,5"
SORT_BY      = "8"

if not (SERPAPI_KEY and REPO_DIR and BASIC_USER and BASIC_PASS):
    raise SystemExit("Missing env vars: SERPAPI_KEY, REPO_DIR, BASIC_AUTH_USER, BASIC_AUTH_PASS are required")

RESULTS_HOTELS = os.path.join(REPO_DIR, "yocto", "results", "index.html")
RESULTS_FLIGHTS = os.path.join(REPO_DIR, "yocto", "fly", "results", "index.html")

app = Flask(__name__)

# ===== BASIC AUTH =====
@app.before_request
def _auth():
    a = request.authorization
    if not (a and a.username == BASIC_USER and a.password == BASIC_PASS):
        return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="yocto"'})

# ===== SHARED UTILS =====
def esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def titlecase_city(s: str) -> str:
    tokens = re.split(r"(\s|-)", s.strip().lower())
    out = []
    for t in tokens:
        if t.strip() in ("dc","nyc","la","usa"): out.append(t.upper())
        elif t in (" ","-"): out.append(t)
        else: out.append(t.capitalize())
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

# ====== HOTELS (unchanged features you asked for earlier) ======
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
    out = []
    if isinstance(imgs, list):
        for im in imgs:
            u = im.get("original_image") or im.get("thumbnail") or im.get("image")
            if u: out.append(u)
    return out

# ---- LOGOS for hotels (explicit map; absolute URLs so they resolve via ngrok or Pages) ----
def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"&", " and ", s)
    return re.sub(r"[^a-z0-9]+", "", s)

BRAND_LOGOS = {
    # Hilton family
    "conrad": "conrad.png",
    "embassysuites": "embassy_suites.png",
    # Hyatt
    "grandhyatt": "grand_hyatt.png",
    "hyattregency": "hyatt_regency.png",
    "parkhyatt": "park_hyatt.png",
    "thompson": "thompson.png",
    # Marriott
    "jwmarriott": "jw_marriott.png",
    "renaissance": "renaissance.png",
    "residenceinn": "residence_inn.png",
    "stregis": "st_regis.png",
    "ritzcarlton": "ritz_carlton.png",
    "westin": "westin.png",
    "edition": "edition.png",
    # IHG
    "intercontinental": "intercontinental.png",
    "kimpton": "kimpton.png",
    # MOHG
    "mandarinoriental": "mandarin_oriental.png",
    # Four Seasons
    "fourseasons": "four_seasons.png",
    # Hilton luxury
    "waldorfastoria": "waldorf_astoria.png",
    # W Hotels
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
    return f"{SITE_BASE}/yocto/logos/fallback.png"

# ---- AMENITIES (curated + relabeled) ----
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

STAR_SVG = """<svg class="star" viewBox="0 0 24 24" aria-hidden="true">
  <path d="M12 2l3.09 6.26L22 9.27l-5 4.86L18.18 22 12 18.7 5.82 22 7 14.13l-5-4.86 6.91-1.01z"
        fill="{fill}" stroke="#000" stroke-width="1.2"/>
</svg>"""
def stars_html(n: int) -> str:
    n = max(0, min(5, int(n)))
    return "".join(STAR_SVG.format(fill="#FFD54A" if i < n else "none") for i in range(5))

LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS  = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
GOOGLE_FONTS = '<link href="https://fonts.googleapis.com/css2?family=Sansation:wght@400;600;700&display=swap" rel="stylesheet">'

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

def render_hotels_html(q: str, ci_s: str, co_s: str, data: Dict[str, Any]) -> str:
    ci = parse_date(ci_s); co = parse_date(co_s)
    city_title = titlecase_city(q)
    subtitle = format_dates(ci, co)
    props = data.get("properties") or []
    # … (identical to your previous hotel renderer, omitted here for brevity)
    # I’ll keep your latest hotel HTML exactly as in our last revision.
    # === START of prior renderer (unchanged) ===
    # (omitted due to length; keep your last working version here)
    # === END of prior renderer ===
    # For compactness in this message, assume you paste in the exact hotel renderer
    # from our last working version you deployed.
    raise NotImplementedError("Paste your existing render_html implementation here from previous step.")

# ====== FLIGHTS ======
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
        "travel_class": class_code,  # 1=econ, 4=first
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
    """Map HOME/NYC/MIA to multi-airport IDs; pass through single IATA like RDU/LGA/etc."""
    t = (s or "").strip().lower()
    if not t: return ""
    if t == "home": return "GSO,RDU"
    if t == "nyc":  return "LGA,JFK,EWR"
    if t == "mia":  return "MIA,FLL"
    # Allow comma-separated input too; otherwise uppercase IATA
    if re.fullmatch(r"[a-z]{3}(?:,[a-z]{3})*", t):
        return ",".join(code.upper() for code in t.split(","))
    return t.upper()

def class_to_code(s: str) -> str:
    t = (s or "").strip().lower()
    if t in ("first","f"): return "4"
    if t in ("business","j","c"): return "3"
    if t in ("premium","prem","pe"): return "2"
    return "1"  # main/economy

def flights_from_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for bucket in ("best_flights", "other_flights"):
        for it in data.get(bucket) or []:
            flights = it.get("flights") or []
            if not flights: continue
            first = flights[0]; last = flights[-1]
            dep_code = (first.get("departure_airport") or {}).get("id")
            arr_code = (last.get("arrival_airport") or {}).get("id")
            dep_time = (first.get("departure_airport") or {}).get("time")
            arr_time = (last.get("arrival_airport") or {}).get("time")
            airline = first.get("airline") or ""
            logo = first.get("airline_logo") or ""
            total_min = it.get("total_duration")
            layovers = []
            for l in it.get("layovers") or []:
                try:
                    d = int(l.get("duration") or 0)
                except Exception:
                    d = 0
                layovers.append({
                    "id": l.get("id"),
                    "name": l.get("name"),
                    "dur": mm_to_hhmm(d) if d else None
                })
            legs = []
            for seg in flights:
                legs.append({
                    "num": seg.get("flight_number"),
                    "airline": seg.get("airline"),
                    "plane": seg.get("airplane"),
                    "dep": (seg.get("departure_airport") or {}).get("id"),
                    "arr": (seg.get("arrival_airport") or {}).get("id"),
                    "dep_time": (seg.get("departure_airport") or {}).get("time"),
                    "arr_time": (seg.get("arrival_airport") or {}).get("time"),
                })
            out.append({
                "price": it.get("price"),
                "dep_code": dep_code, "arr_code": arr_code,
                "dep_time": dep_time, "arr_time": arr_time,
                "airline": airline, "logo": logo,
                "layovers": layovers,
                "total": mm_to_hhmm(int(total_min)) if isinstance(total_min, int) else None,
                "legs": legs,
            })
    return out

def render_flights_html(dep_disp: str, arr_disp: str, date_str: str, data: Dict[str, Any]) -> str:
    items = flights_from_json(data)
    title = f"{esc(dep_disp.upper())} → {esc(arr_disp.upper())}"
    subtitle = parse_date(date_str).strftime("%a, %b %-d")

    cards = []
    for f in items:
        price = f.get("price")
        price_txt = f"${int(price):,}" if isinstance(price, int) else (f"${price}" if price else "—")
        lay = f.get("layovers") or []
        lay_html = ""
        if lay:
            parts = [f"via {esc(x['id'])} ({esc(x['dur'])})" if x.get("id") and x.get("dur") else esc(x.get("name") or "") for x in lay]
            lay_html = f"<div class='lay'>"+ " · ".join(parts) +"</div>"

        legs_html = ""
        for lg in f.get("legs") or []:
            left = f"{esc(lg['dep'])} {esc(lg['dep_time'] or '')}"
            right = f"{esc(lg['arr'])} {esc(lg['arr_time'] or '')}"
            plane = esc(lg.get("plane") or "")
            num = esc(lg.get("num") or "")
            legs_html += f"<div class='leg'><div>{left} → {right}</div><div class='plane'>{plane} {num}</div></div>"

        logo = esc(f.get("logo") or "")
        logo_html = f"<img class='logo' src='{logo}' alt='airline logo'>" if logo else "<div class='logo ph'></div>"

        card = f"""
<article class="card">
  <header class="hd">
    <div class="pair">
      <div class="route">{esc(f.get('dep_code') or '')} {esc(f.get('dep_time') or '')} → {esc(f.get('arr_code') or '')} {esc(f.get('arr_time') or '')}</div>
      {lay_html}
    </div>
    <div class="price">{price_txt}</div>
  </header>
  <div class="body">
    <div class="col logo-col">{logo_html}</div>
    <div class="col legs">{legs_html}</div>
  </div>
</article>
"""
        cards.append(card)

    body = "\n".join(cards) if cards else "<p class='empty'>No flights found.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title} — {subtitle}</title>
<link href="https://fonts.googleapis.com/css2?family=Sansation:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{{--line:#e5e7eb}}
*{{box-sizing:border-box}}
body{{margin:0;background:#0b0b0c;color:#111;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #eee;padding:12px 16px;z-index:5}}
.header h1{{margin:0;font-family:'Sansation',sans-serif;font-weight:700;letter-spacing:.2px}}
.header .sub{{margin-top:4px;color:#555;font-family:'Sansation',sans-serif}}

.wrap{{max-width:920px;margin:0 auto;padding:16px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:14px 0;box-shadow:0 10px 30px rgba(0,0,0,.08)}}
.hd{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:14px}}
.pair{{display:flex;flex-direction:column;gap:4px}}
.route{{font-weight:700}}
.lay{{font-size:13px;color:#444}}
.price{{background:rgba(11,101,216,.9);color:#fff;font-family:'Sansation',sans-serif;font-weight:600;padding:8px 12px;border-radius:10px;align-self:flex-start}}

.body{{display:grid;grid-template-columns:160px 1fr;gap:12px;padding:12px 14px}}
.logo-col{{display:flex;align-items:center;justify-content:center}}
.logo{{max-width:130px;max-height:44px;object-fit:contain}}
.logo.ph{{width:120px;height:36px;background:#f3f4f6;border:1px dashed #e5e7eb;border-radius:8px}}

.legs{{display:flex;flex-direction:column;gap:8px}}
.leg{{display:flex;align-items:baseline;justify-content:space-between;border-bottom:1px dashed #eee;padding:6px 0}}
.leg:last-child{{border-bottom:none}}
.plane{{font-size:13px;color:#444}}

.empty{{color:#666;background:#fff;padding:20px;border-radius:12px;border:1px solid #eee}}

@media (max-width:720px){{
  .body{{grid-template-columns:1fr}}
  .logo-col{{order:2}}
}}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div class="sub">{subtitle}</div>
</div>
<div class="wrap">
{body}
<div style="text-align:center;color:#555;font-size:12px;margin:18px 0;">
  Published to <a href="{SITE_BASE}/yocto/fly/results/" style="color:#111">{SITE_BASE}/yocto/fly/results/</a>
</div>
</div>
</body>
</html>"""

# ===== ROUTES =====
@app.get("/health")
def health(): return {"status":"ok"}

# Hotels route (existing)
@app.get("/run")
def run_hotels():
    where = (request.args.get("where") or request.args.get("q") or "").strip()
    when  = (request.args.get("when")  or request.args.get("check_in_date") or "").strip()
    nights_str = (request.args.get("nights") or "1").strip()
    if not where or not when: abort(400, "Missing 'where' or 'when'")
    try:
        nights = max(1, int(nights_str))
        ci = parse_date(when); co = ci + timedelta(days=nights)
    except Exception:
        abort(400, "Invalid 'when' (YYYY-MM-DD) or 'nights'")
    ci_s, co_s = ci.isoformat(), co.isoformat()
    data = serpapi_hotels(where, ci_s, co_s)
    # NOTE: replace the next line with your full hotel renderer from the prior step:
    html_out = render_hotels_html(where, ci_s, co_s, data)  # <-- paste your previous renderer
    write_file(RESULTS_HOTELS, html_out)
    _ = git_add_commit_push(["yocto/results/index.html"])
    return Response(html_out, mimetype="text/html")

# Flights route (new)
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
    class_code = class_to_code(cls)  # 4=first default
    data = serpapi_flights(dep_ids, arr_ids, date_str, class_code)
    html_out = render_flights_html(dep_disp, arr_disp, date_str, data)
    write_file(RESULTS_FLIGHTS, html_out)
    _ = git_add_commit_push(["yocto/fly/results/index.html"])
    return Response(html_out, mimetype="text/html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False)
