#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import subprocess
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime

import requests

# ---------- Local folder target ----------
DEFAULT_FOLDER = Path.home() / "Desktop" / "Hotels"
DEFAULT_OUT = DEFAULT_FOLDER / "hotels.html"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SerpAPI Google Hotels ??? HTML card gallery")
    p.add_argument(
        "--api-key",
        default=os.getenv("SERPAPI_KEY", "973f3e5072af5b98a1bda79c09464841026303b79680c37d20d97f6540e53c72"),
        help="SerpAPI key (or set SERPAPI_KEY env var)",
    )
    p.add_argument("--city", default="park hyatt", help="City name to search")
    p.add_argument("--check-in", 
default="2025-08-15", help="YYYY-15-DD")
    p.add_argument("--check-out", 
default="2025-08-16", help="YYYY-MM-DD")
    p.add_argument("--sort-by", default="3", help="SerpAPI sort_by code (e.g., 3=Price, 8=Relevance, etc.)")
    p.add_argument("--hotel-class", default="4,5", help="Hotel star classes (comma-separated)")
    p.add_argument(
        "--brands",
        default="84,7,41,118,256,26,136,289,2,3",
        help="Comma-separated brand IDs (optional filter)",
    )
    p.add_argument("--min-rating", type=float, default=0.0, help="Minimum guest rating to include")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Output HTML file path")
    p.add_argument("--open-browser", action="store_true", help="Open the HTML in the default browser")
    p.add_argument("--serve", action="store_true", help="Start a local HTTP server for the output")
    return p.parse_args()


def fetch_hotels(
    city: str,
    check_in: str,
    check_out: str,
    api_key: str,
    sort_by: str,
    hotel_class: str,
    brands: str
) -> Dict[str, Any]:
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_hotels",
        "q": city,
        "gl": "us",
        "check_in_date": check_in,
        "check_out_date": check_out,
        "sort_by": sort_by,
        "hotel_class": hotel_class,
        "api_key": api_key,
        "brands": brands,
    }
    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        sys.stderr.write(f"[HTTP] {e}\nBody: {getattr(e, 'response', None) and e.response.text}\n")
        sys.exit(1)
    except requests.RequestException as e:
        sys.stderr.write(f"[Network] {e}\n")
        sys.exit(1)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[JSON] {e}\n")
        sys.exit(1)

# ---------- Icons (inline SVG) ----------
AMENITY_ICONS: Dict[str, Tuple[str, str]] = {
    "pool": ('Pool', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M2 17c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1 2-1 4-1v2c-2 0-2 1-4 1s-2-1-4-1-2 1-4 1-2-1-4-1v-2zM8 6a3 3 0 016 0v5h-2V6a1 1 0 10-2 0v5H8V6z"/>
</svg>
"""),
    "hot tub": ('Hot tub', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M3 10h18v6a3 3 0 01-3 3H6a3 3 0 01-3-3v-6zm4-3c0-1.1.9-2 2-2s2 .9 2 2v1H7V7zM15 7c0-1.1.9-2 2-2s2 .9 2 2v1h-4V7z"/>
</svg>
"""),
    "pet": ('Pet friendly', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M12 13c-2.8 0-8 1.4-8 4.2S9.2 20 12 20s8-.6 8-2.8S14.8 13 12 13zM6.5 9A1.5 2 0 108 9a1.5 2 0 00-1.5-2zM10.5 7A1.5 2 0 1012 7a1.5 2 0 00-1.5-2zM13.5 7A1.5 2 0 1015 7a1.5 2 0 00-1.5-2zM17.5 9A1.5 2 0 1019 9a1.5 2 0 00-1.5-2z"/>
</svg>
"""),
    "spa": ('Spa', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M12 3C9 6 8 9 8 12s1 6 4 9c3-3 4-6 4-9s-1-6-4-9zm0 6a3 3 0 110 6 3 3 0 010-6z"/>
</svg>
"""),
    "restaurant": ('Restaurant', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M7 2h2v10a2 2 0 11-4 0V2h2zm8 0h2v7h2v13h-2V11h-2V2z"/>
</svg>
"""),
    "room service": ('Room service', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M12 5a7 7 0 00-7 7h14a7 7 0 00-7-7zm-9 9v2h18v-2H3z"/>
</svg>
"""),
    "beach": ('Beach access', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M2 18c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1 2-1 4-1v2c-2 0-2 1-4 1s-2-1-4-1-2 1-4 1-2-1-4-1v-2zM12 4l3 5H9l3-5z"/>
</svg>
"""),
    "bar": ('Bar', """
<svg viewBox="0 0 24 24" class="amenity" aria-hidden="true">
  <path d="M3 3h18l-6 8v7h-6v-7L3 3z"/>
</svg>
"""),
}

def extract_deal_percent(deal_text: str) -> Optional[str]:
    if not deal_text:
        return None
    m = re.search(r"(\d+)", deal_text.replace(",", ""))
    return f"{m.group(1)}% below normal" if m else None

def norm_price(v: Any) -> Optional[str]:
    return str(v) if v is not None else None

def pick_images(images_block: Any) -> Tuple[Optional[str], List[str], List[str]]:
    thumbs: List[str] = []
    fulls: List[str] = []
    if isinstance(images_block, list):
        for img in images_block:
            if not isinstance(img, dict):
                continue
            t = img.get("thumbnail")
            f = img.get("original_image")
            if t:
                thumbs.append(t)
            if f:
                fulls.append(f)
    hero = fulls[0] if fulls else (thumbs[0] if thumbs else None)
    return hero, thumbs, fulls

def amenity_svgs(amenities: Any) -> str:
    if not isinstance(amenities, list):
        return ""
    text = [str(a).lower() for a in amenities]
    chosen: List[str] = []

    def add(key: str):
        label, svg = AMENITY_ICONS.get(key, (None, None))  # type: ignore
        if svg:
            chosen.append(f"<span class='amenity-wrap' title='{label}'>{svg}</span>")

    if any("pool" in a for a in text): add("pool")
    if any(("hot tub" in a) or ("whirlpool" in a) or ("jacuzzi" in a) for a in text): add("hot tub")
    if any("pet" in a for a in text): add("pet")
    if any("spa" in a for a in text): add("spa")
    if any(("restaurant" in a) or ("dining" in a) for a in text): add("restaurant")
    if any("room service" in a for a in text): add("room service")
    if any("beach" in a for a in text): add("beach")
    if any(("bar" in a) or ("lounge" in a) for a in text): add("bar")
    return "".join(chosen)

def parse_class_to_int(hotel_class: Any) -> int:
    m = re.search(r"(\d+)", str(hotel_class or ""))
    n = int(m.group(1)) if m else 0
    return max(0, min(5, n))

def star_icons(class_int: int) -> str:
    stars: List[str] = []
    for i in range(5):
        if i < class_int:
            stars.append("""
<svg viewBox="0 0 24 24" class="star star-filled" aria-hidden="true">
  <path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 18l-6.2 3.3 1.2-6.8-5-4.9 6.9-1z"/>
</svg>
""")
        else:
            stars.append("""
<svg viewBox="0 0 24 24" class="star star-outline" aria-hidden="true">
  <path d="M12 3.8l2.3 4.7 5.2.8-3.8 3.7.9 5.2L12 16.9 7.4 18.2l.9-5.2L4.6 9.3l5.2-.8L12 3.8z" fill="none" stroke="currentColor" stroke-width="1.6"/>
</svg>
""")
    return f"<div class='stars' title='{class_int}-star hotel'>{''.join(stars)}</div>"

def build_deal_badge(deal: Optional[str], deal_desc: Optional[str]) -> str:
    if not (deal or deal_desc):
        return ""
    desc = (deal_desc or "").strip()
    amount = extract_deal_percent(deal or desc)
    if not amount:
        return ""
    kind = desc.lower().strip()
    color_class = "deal-green" if kind == "deal" else ("deal-yellow" if kind == "great deal" else "deal-green")
    text = f"{desc} ??? {amount}"
    return f"<div class='deal-badge {color_class}'>{text}</div>"

LEAF_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAF_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

FAVICON_DATA_URL = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Cpath fill='%23f5c518' d='M32 6l8.3 16.8 18.5 2.7-13.4 9.6L49.4 57 32 49.4 15.4 57l3.2-18.5L5.2 25.5l18.5-2.7L32 6z'/%3E%3C/svg%3E"
)

CSS = r"""
:root {
  --bg:#0b0b0c; --card:#ffffff; --muted:#5b6168; --text:#0b0b0c;
  --accent:#0b65d8; --dealGreen:#00c853; --dealYellow:#fbc02d;
  --outline:#dfe3e6; --shadow:rgba(0,0,0,.12); --star:#f5c518;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:#e8eaed;font-family:"Poppins","Inter",-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
.header{position:sticky;top:0;z-index:5;background:linear-gradient(180deg,rgba(11,11,12,.95),rgba(11,11,12,.6));backdrop-filter:blur(8px);padding:12px 16px;border-bottom:1px solid #222}
.header h1{margin:0;font-size:18px;font-weight:600;letter-spacing:.2px;color:#fff;font-family:"Playfair Display",serif}
.header .sub{font-size:12px;color:#9aa0a6;margin-top:2px}
.wrap{max-width:860px;margin:0 auto;padding:12px}

.card{ background:var(--card); color:var(--text); border:1px solid var(--outline);
  border-radius:16px; overflow:hidden; margin:12px 0 18px; box-shadow:0 10px 30px var(--shadow); transition:transform .2s, box-shadow .2s; cursor:pointer }
.card:hover{ transform:translateY(-4px); box-shadow:0 14px 40px var(--shadow) }

.hero-wrap{ position:relative; background:#111; }
.hero{ width:100%; height:260px; object-fit:cover; display:block; }
.price-badge{
  position:absolute; top:10px; left:10px; background:rgba(0,0,0,.75); color:#fff;
  font-weight:700; font-size:16px; padding:6px 10px; border-radius:10px; border:1px solid rgba(255,255,255,.2)
}
.deal-badge{
  position:absolute; top:10px; right:10px; font-weight:700; font-size:13px;
  padding:6px 10px; border-radius:10px; border:1px solid transparent;
  background:rgba(0,0,0,.6); color:#fff;
}
.deal-green{ border-color:var(--dealGreen); color:var(--dealGreen) }
.deal-yellow{ border-color:var(--dealYellow); color:var(--dealYellow) }

.map{ position:absolute; bottom:12px; right:12px; width:160px; height:110px;
  border:1px solid #d7dbe0; border-radius:10px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,.25) }

.content{ padding:14px 14px 16px; }
.title{ font-size:20px; margin:2px 0 6px; line-height:1.25; color:var(--text); font-family:"Playfair Display",serif }
.title a{ color:inherit; text-decoration:none }
.title a:active{ opacity:.6 }

.desc{ color:var(--muted); font-size:14px; line-height:1.45; margin:6px 0 8px }

.meta-row{ display:flex; gap:14px; align-items:center; margin:8px 0 10px; flex-wrap:wrap }
.stars{ display:flex; gap:2px }
.star{ width:18px; height:18px; color:#c7ccd1 }
.star-filled{ fill:var(--star) }
.star-outline{ fill:none; color:#9aa0a6 }

.rating-badge{ display:inline-flex; align-items:center; gap:6px;
  border:1px solid var(--outline); border-radius:10px; padding:4px 8px;
  font-size:13px; color:var(--text); background:#fff }
.rating-box{ background:#111; color:#fff; font-weight:700; padding:2px 6px; border-radius:6px; font-size:13px }

.amenities{ display:flex; flex-wrap:wrap; gap:12px; margin:6px 0 10px }
.amenity-wrap{ display:inline-flex }
.amenity{ width:24px; height:24px; fill:#4b5563; opacity:.95 }

.thumbs{ display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; -webkit-overflow-scrolling:touch }
.thumb{ display:block; width:120px; height:80px; object-fit:cover; background:#111; border-radius:10px; border:1px solid #dfe3e6 }
.thumb-btn{ appearance:none; border:0; padding:0; background:transparent; cursor:pointer }
.thumb-btn:focus{ outline:2px solid #6aa0ff; outline-offset:2px }
.active-thumb{ outline:2px solid var(--accent) }

.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .4s ease;z-index:50;}
.modal-overlay.show{opacity:1;pointer-events:all;}
.modal{background:var(--card);color:var(--text);border-radius:20px;max-width:600px;width:90%;max-height:80%;overflow-y:auto;position:relative;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,.4);transform:translateY(40px);transition:transform .4s ease;}
.modal-overlay.show .modal{transform:translateY(0);}
.modal-close{position:absolute;top:12px;right:16px;font-size:28px;background:none;border:none;color:var(--text);cursor:pointer;}
.modal-body{font-size:15px;line-height:1.5;color:var(--text);}
.modal-body ul{padding-left:20px;}
.modal-title{margin:0 0 12px;font-size:24px;font-family:"Playfair Display",serif;}
.modal-json{font-family:monospace;background:#f5f5f7;padding:12px;border-radius:10px;overflow-x:auto;}

@media (max-width:480px){
  .hero{ height:220px }
  .map{ width:140px; height:100px }
}
"""

def build_html(city: str, check_in: str, check_out: str, properties: List[Dict[str, Any]]) -> str:
    # City: only first letter uppercase, leave the rest as-is (preserves acronyms)
    city_disp = city.strip()
    city_disp = (city_disp[:1].upper() + city_disp[1:]) if city_disp else "City"
    try:
        date_disp = datetime.strptime(check_in, "%Y-%m-%d").strftime("%m/%d/%y")
    except Exception:
        date_disp = check_in

    maps_payload: List[Dict[str, Any]] = []
    cards: List[str] = []

    for idx, p in enumerate(properties or []):
        name = p.get("name") or "Unnamed Hotel"
        desc = p.get("description") or ""
        price = norm_price((p.get("rate_per_night") or {}).get("lowest"))

        hero, thumbs, fulls = pick_images(p.get("images"))
        thumb_btns: List[str] = []
        for i, t in enumerate(thumbs[:8]):
            full = fulls[i] if i < len(fulls) and fulls[i] else t
            if not t:
                continue
            thumb_btns.append(
                f'<button class="thumb-btn" data-card="{idx}" data-full="{full}" data-thumb-idx="{i}">'
                f'  <img src="{t}" class="thumb" loading="lazy" alt="Thumbnail {i+1}">'
                f'</button>'
            )
        thumbs_html = f"<div class='thumbs'>{''.join(thumb_btns)}</div>" if thumb_btns else ""

        amen_html = amenity_svgs(p.get("amenities"))
        class_int = parse_class_to_int(p.get("hotel_class"))
        stars_html = star_icons(class_int)

        rating = p.get("overall_rating")
        rating_html = (
            f"<span class='rating-badge'><span>Guest Rating</span><span class='rating-box'>{rating}</span></span>"
            if rating else ""
        )

        gps = p.get("gps_coordinates") or {}
        lat = gps.get("latitude")
        lng = gps.get("longitude")
        map_id = f"map_{idx}"
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            maps_payload.append({"id": map_id, "name": name, "lat": lat, "lng": lng})

        hotel_link = p.get("link")
        title_link = f'<a href="{hotel_link}" target="_blank" rel="noopener">{name}</a>' if hotel_link else name

        deal_badge = build_deal_badge(p.get("deal"), p.get("deal_description"))

        cards.append(f"""
<section class="card" id="card_{idx}">
  <div class="hero-wrap">
    {"<img src='" + hero + "' class='hero' alt='Hotel image' id='hero_" + str(idx) + "'>" if hero else ""}
    {"<div class='price-badge'>" + price + "</div>" if price else ""}
    {deal_badge}
    <div id="{map_id}" class="map"></div>
  </div>
  <div class="content">
    <h2 class="title">{title_link}</h2>
    {"<p class='desc'>" + desc + "</p>" if desc else ""}
    <div class="meta-row">
      {stars_html}
      {rating_html}
    </div>
    <div class="amenities">{amen_html}</div>
    {thumbs_html}
  </div>
</section>
""")

    maps_json = json.dumps(maps_payload)
    details_json = json.dumps(properties)
    js = f"""
document.addEventListener('DOMContentLoaded', () => {{
  const hotels = {maps_json};
  const details = {details_json};
  hotels.forEach(h => {{
    const el = document.getElementById(h.id);
    if (!el) return;
    const map = L.map(el, {{ zoomControl: false, attributionControl: false, dragging: true, tap: true }}).setView([h.lat, h.lng], 14);
    L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 18 }}).addTo(map);
    const icon = L.icon({{
      iconUrl: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="%23ff3b30"><path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5c-1.4 0-2.5-1.1-2.5-2.5S10.6 6.5 12 6.5s2.5 1.1 2.5 2.5S13.4 11.5 12 11.5z"/></svg>',
      iconSize: [28, 28], iconAnchor: [14, 28]
    }});
    L.marker([h.lat, h.lng], {{ icon: icon }}).addTo(map);
    setTimeout(() => map.invalidateSize(), 200);
  }});

<<<<<<< ours
  // thumbnail ??? hero swap (no new tab)
=======
  const modal = document.getElementById('modal-overlay');
  const modalBody = modal.querySelector('.modal-body');
  const close = () => modal.classList.remove('show');
  modal.querySelector('.modal-close').addEventListener('click', close);
  modal.addEventListener('click', e => {{ if (e.target === modal) close(); }});

  const escapeHtml = str => str.replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}}[c]));
  const buildDetails = d => {{
    let html = `<h2 class="modal-title">${{d.name || ''}}</h2>`;
    if (d.check_in_time) html += `<p><strong>Check-in:</strong> ${{d.check_in_time}}</p>`;
    if (d.check_out_time) html += `<p><strong>Check-out:</strong> ${{d.check_out_time}}</p>`;
    const nearby = d.nearby_attractions || d.nearby_places;
    if (Array.isArray(nearby) && nearby.length) {{
      html += '<h3>Nearby Attractions</h3><ul>';
      nearby.forEach(n => {{ const name = n.name || n; html += `<li>${{name}}</li>`; }});
      html += '</ul>';
    }}
    html += `<pre class="modal-json">${{escapeHtml(JSON.stringify(d, null, 2))}}</pre>`;
    return html;
  }};

  document.querySelectorAll('.card').forEach((card, idx) => {{
    card.addEventListener('click', e => {{
      if (e.target.closest('a') || e.target.closest('.thumb-btn')) return;
      const d = details[idx] || {{}};
      modalBody.innerHTML = buildDetails(d);
      modal.classList.add('show');
    }});
  }});

  // thumbnail → hero swap (no new tab)
>>>>>>> theirs
  document.querySelectorAll('.thumb-btn').forEach(btn => {{
    btn.addEventListener('click', e => {{
      e.stopPropagation();
      const cardIdx = btn.dataset.card;
      const full = btn.dataset.full;
      const hero = document.getElementById('hero_' + cardIdx);
      if (hero && full) {{
        hero.src = full;
      }}
      const card = document.getElementById('card_' + cardIdx);
      if (card) {{
        card.querySelectorAll('.thumb-btn').forEach(b => b.classList.remove('active-thumb'));
        btn.classList.add('active-thumb');
      }}
    }});
  }});
}});
"""

    head = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{city_disp} Hotels ??? {date_disp}</title>
<link rel="icon" href="{FAVICON_DATA_URL}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{LEAF_CSS}" />
<style>{CSS}</style>
</head><body>
<div class="header"><h1>{city_disp} Hotels ??? {date_disp}</h1><div class="sub">{check_in} ??? {check_out}</div></div>
<div class="wrap">
"""
    modal_html = """
<div id="modal-overlay" class="modal-overlay">
  <div class="modal">
    <button class="modal-close" aria-label="Close">&times;</button>
    <div class="modal-body"></div>
  </div>
</div>
"""

    tail = f"""
</div>
{modal_html}
<script src="{LEAF_JS}"></script>
<script>{js}</script>
</body></html>
"""
    return head + "".join(cards) + tail

def ensure_local_folder(path: Path) -> Path:
    folder = path.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        sys.stderr.write(f"Could not create local folder {folder}: {e}\n")
        sys.exit(1)
    return path

def start_http_server(out_path: Path) -> None:
    os.chdir(str(out_path.parent))
    subprocess.run(["python3", "-m", "http.server", "8000"])

def main() -> None:
    args = parse_args()

    out_path = Path(args.out)
    out_path = ensure_local_folder(out_path)

    data = fetch_hotels(
        city=args.city,
        check_in=args.check_in,
        check_out=args.check_out,
        api_key=args.api_key,
        sort_by=args.sort_by,
        hotel_class=args.hotel_class,
        brands=args.brands
    )
    props = data.get("properties") or []

    def rating_ok(p: Dict[str, Any]) -> bool:
        try:
            return float(p.get("overall_rating") or 0) >= args.min_rating
        except Exception:
            return False

    props = [p for p in props if rating_ok(p)]

    html = build_html(args.city, args.check_in, args.check_out, props)
    out_path.write_text(html, encoding="utf-8")

    print(f"Wrote {out_path.resolve()} with {len(props)} hotel(s).")

    if args.open_browser:
        try:
            import webbrowser
            webbrowser.open(out_path.as_uri())
        except Exception as e:
            print(f"Could not open browser: {e}", file=sys.stderr)

    if args.serve:
        start_http_server(out_path)

if __name__ == "__main__":
    main()
