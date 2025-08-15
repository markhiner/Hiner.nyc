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
    # Protect every route
    auth = request.authorization
    if not check_auth(auth):
        return require_auth()

# ---------- Utilities ----------
def to_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()

def serpapi_hotels(q: str, check_in: str, check_out: str) -> Dict[str, Any]:
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_hotels",
        "q": q,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "currency": "USD",
        "adults": "2",
        "gl": "us",
        "hl": "en",
        "api_key": SERPAPI_KEY,
    }
    r = requests.get(url, params=params, timeout=40)
    r.raise_for_status()
    return r.json()

def safe(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def render_html(q: str, ci: str, co: str, data: Dict[str, Any]) -> str:
    props = (data.get("properties") or [])[:50]
    rows = []
    for p in props:
        name = safe(p.get("name"))
        rating = safe(p.get("overall_rating"))
        klass = safe(p.get("hotel_class"))
        price = safe((p.get("rate_per_night") or {}).get("lowest"))
        desc  = safe(p.get("description"))
        link  = safe(p.get("link"))
        thumb = ""
        imgs = p.get("images") or []
        if imgs:
            thumb = f'<img src="{safe(imgs[0].get("thumbnail"))}" alt="" style="width:120px;height:auto;border-radius:10px;border:1px solid #2a2a2a;">'
        rows.append(f"""
        <tr>
          <td style="vertical-align:top;padding:12px 10px;">{thumb}</td>
          <td style="vertical-align:top;padding:12px 10px;">
            <div style="font-weight:600">{name}</div>
            <div style="opacity:.8;font-size:14px;margin:4px 0">{desc}</div>
            <div style="font-size:14px">Rating: {rating or '—'} · Class: {klass or '—'} · From: {price or '—'}</div>
            <div style="margin-top:6px"><a href="{link}" target="_blank" rel="noopener">View</a></div>
          </td>
        </tr>
        """)

    table = "\n".join(rows) or "<tr><td>No results.</td></tr>"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hotels · {safe(q)} · {ci} → {co}</title>
<style>
  body{{margin:0;background:#0b0b0b;color:#eee;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
  .wrap{{max-width:960px;margin:32px auto;padding:0 16px}}
  .card{{background:#161616;border:1px solid #2a2a2a;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.35);padding:18px}}
  a{{color:#7cb1ff;text-decoration:none}}
  table{{width:100%;border-collapse:collapse}}
  tr+tr td{{border-top:1px solid #2a2a2a}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1 style="margin:6px 0 14px 0;font-size:22px">Hotels for <span style="opacity:.9">{safe(q)}</span></h1>
    <div style="opacity:.8;margin-bottom:10px">Dates: {ci} → {co} · Generated {safe(now)}</div>
    <table>{table}</table>
    <div style="opacity:.7;margin-top:14px;font-size:13px">
      Published to <a href="{safe(SITE_BASE)}/yocto/results/" rel="noopener">{safe(SITE_BASE)}/yocto/results/</a>
    </div>
  </div>
</div>
</body></html>"""

def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def git(*args):
    return subprocess.run(["git", *args], cwd=REPO_DIR, check=True, capture_output=True, text=True)

def try_git_commit_push() -> Optional[str]:
    try:
        subprocess.run(["git","add","yocto/results/index.html"], cwd=REPO_DIR, check=True)
        # Commit may fail if no changes; allow that.
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

@app.get("/run")
def run():
    where = (request.args.get("where") or request.args.get("q") or "").strip()
    when  = (request.args.get("when")  or request.args.get("check_in_date") or "").strip()
    nights_str = (request.args.get("nights") or "1").strip()

    if not where or not when:
        abort(400, "Missing 'where' or 'when'")
    try:
        nights = max(1, int(nights_str))
        ci = to_date(when)
        co = ci + timedelta(days=nights)
    except Exception:
        abort(400, "Invalid 'when' (YYYY-MM-DD) or 'nights'")

    ci_s, co_s = ci.isoformat(), co.isoformat()
    data = serpapi_hotels(where, ci_s, co_s)
    html_out = render_html(where, ci_s, co_s, data)

    # Write results into the GitHub Pages repo & push
    write_file(RESULTS_FILE, html_out)
    _ = try_git_commit_push()

    return Response(html_out, mimetype="text/html")

if __name__ == "__main__":
    # Bind to 127.0.0.1; expose via tunnel
    app.run(host="127.0.0.1", port=5000, debug=False)
