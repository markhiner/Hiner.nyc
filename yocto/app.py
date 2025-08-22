def render_flights_html(dep_disp: str, arr_disp: str, date_str: str, data: Dict[str, Any], class_disp: str = "first") -> str:
    items = flights_from_json(data)
    title = f"{esc(dep_disp.upper())} → {esc(arr_disp.upper())}"
    try:
        subtitle = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a, %b %-d")
    except ValueError:
        subtitle = esc(date_str)

    cards = []
    for f in items:
        price = f.get("price")
        price_txt = f"${int(price):,}" if isinstance(price, int) else (f"${price}" if price else "—")
        big_codes = f"{esc(f['dep_code'])} ► {esc(f['arr_code'])}"
        cls_txt   = "First Class" if (class_disp or '').lower().startswith("f") else "Main"

        # leg rows
        leg_rows = []
        for lg in f.get("legs") or []:
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

        # layovers
        lay_html = ""
        for l in f.get("layovers") or []:
            if l.get("dur") and l.get("id"):
                lay_html += f"<div class='lay'>Connect in {esc(str(l['id']))} <span>{esc(l['dur'])}</span></div>"

        # plane art
        plane_url = plane_strip_url(f.get("airline"))
        plane_html = f"<img class='plane' src='{esc(plane_url)}' alt=''>" if plane_url else ""

        card = f"""
<article class="fc">
  <div class="plate" aria-hidden="true"></div>
  <div class="codes" aria-hidden="true">{big_codes}</div>
  <div class="pane">
    <div class="grid">
      {legs_html}
      {lay_html}
    </div>
  </div>
  <div class="price" aria-hidden="true">{esc(price_txt)}</div>
  {plane_html}
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
<style>
@font-face {{
  font-family: 'AntonCustom';
  src:
    url('{SITE_BASE}/yocto/fonts/Anton.woff2') format('woff2'),
    url('{SITE_BASE}/yocto/fonts/Anton.ttf') format('truetype'),
    url('{SITE_BASE}/yocto/fonts/Anton.otf') format('opentype');
  font-weight: 800 900; font-style: normal; font-display: swap;
}}
@font-face {{
  font-family: 'AcuminCond';
  src:
    url('{SITE_BASE}/yocto/fonts/acumin-pro-condensed.woff2') format('woff2'),
    url('{SITE_BASE}/yocto/fonts/acumin-pro-condensed.otf') format('opentype');
  font-weight: 300 900; font-style: normal; font-display: swap;
}}

html{{-webkit-text-size-adjust:100%}}
:root{{ --blue:#27308D; --sky:#93c5fd; --off:#F6F3EE; --ink:#000; }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--sky);color:var(--ink);font-family:'AcuminCond', system-ui, -apple-system, Arial, sans-serif}}

.header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #eee;
  padding:12px calc(16px + env(safe-area-inset-right)) 12px calc(16px + env(safe-area-inset-left));z-index:5}}
.header h1{{margin:0 0 2px 0;font-family:'AcuminCond';font-weight:800;letter-spacing:.5px}}
.header .sub{{color:#333}}

.wrap{{max-width:980px;margin:0 auto;
  padding:20px calc(16px + env(safe-area-inset-right)) 60px calc(16px + env(safe-area-inset-left))}}

.fc{{
  position:relative;
  border-radius:28px; overflow:hidden; margin:22px 0;
  /* tuned for iPhone 16 Pro Max width ~430px */
  height: clamp(360px, 72vw, 480px);
}}

.fc .plate{{
  position:absolute; inset:0;
  background: url('{SITE_BASE}/yocto/logos/card_bg.png') center/cover no-repeat;
  z-index:1; pointer-events:none;
}}

.fc .codes{{
  position:absolute; left:24px; right:24px; top:16px; z-index:2;
  font-family:'AntonCustom', Impact, sans-serif;
  font-weight:900; letter-spacing:2px; color:#fff;
  /* oversized and responsive */
  font-size: clamp(44px, 16vw, 92px);
  line-height:.9;
  display:flex; gap:14px; align-items:flex-start;
  pointer-events:none; user-select:none;
  text-shadow: 0 2px 0 rgba(0,0,0,.25);
}}

.fc .plane{{
  position:absolute; left:0; right:0; top:64px; z-index:4;
  height: clamp(150px, 38vw, 220px);
  object-fit:contain; object-position:right center;
  pointer-events:none; user-select:none;
}}

.fc .pane{{
  position:absolute; left:22px; right:22px;
  bottom: calc(28px + env(safe-area-inset-bottom));
  background: rgba(255,255,255,.96);
  border-radius:18px; padding:12px 14px;
  border:1px solid rgba(0,0,0,.06);
  z-index:3; /* below plane so plane clips the big codes + pane */
  backdrop-filter: saturate(120%) blur(1.5px);
}}

.fc .grid{{ display:block }}
/* grid: dep time | arr time | dep code | arr code | class | aircraft */
.fc .legline{{
  display:grid;
  grid-template-columns:64px 64px 56px 56px 1fr minmax(110px, 160px);
  column-gap:16px; align-items:center;
  padding:8px 2px; border-bottom:1px solid rgba(0,0,0,.08);
  font-family:'AcuminCond'; font-weight:700; font-size:17px;
  white-space:nowrap;
}}
.fc .legline:last-of-type{{border-bottom:none}}
.fc .cell.t{{font-variant-numeric:tabular-nums}}
.fc .cell.code{{letter-spacing:.5px}}
.fc .cell.cls{{text-align:left}}
.fc .cell.plane{{text-align:right; overflow:visible}}

.fc .lay{{
  margin-top:8px; font-family:'AcuminCond'; font-weight:800;
}}
.fc .lay span{{ color:#d00; margin-left:6px }}

.fc .price{{
  position:absolute; left:28px;
  bottom: calc(18px + env(safe-area-inset-bottom));
  z-index:6;
  font-family:'AntonCustom'; font-size: clamp(32px, 7vw, 44px);
  color:#fff; text-shadow: 0 2px 0 rgba(0,0,0,.35);
  pointer-events:none; user-select:none;
}}

@media (max-width:430px){{
  .fc .plane{{ top:70px }}
  .fc .pane{{ border-radius:16px }}
  .fc .legline{{ column-gap:12px; font-size:16px }}
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
