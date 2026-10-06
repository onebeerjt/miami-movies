"""Playwright scrapers for the Cloudflare-blocked chains.

Covers: AMC Sunset Place 24, Silverspot Downtown Miami, Cinépolis Coconut Grove.

How it behaves by environment:
- On this dev VM the egress proxy IP is flagged by Cloudflare's bot-fight
  mode: every one of these sites serves "Attention Required" even to a
  headed Chromium with stealth evasions. The scraper detects that and
  returns [] with a documented reason (graceful degradation).
- On a clean IP (e.g. the GitHub Actions weekly cron) the challenge may
  pass; the scraper then extracts showtimes with generic DOM heuristics
  (time-like buttons grouped under the nearest movie heading). Those
  per-site parsers are best-effort and UNVERIFIED — they were written
  without a passing page load to test against.

Usage:
    python playwright_scrape.py [--headless] [--theater amc|silverspot|cinepolis|all]

Env:
    PW_HEADLESS=1   run headless (default when no display; CI)
    https_proxy     when set, traffic goes via scrapers/pw_proxy.py forwarder
                    on 127.0.0.1:8899 (started automatically if needed)
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
VENV_PY = Path.home() / "workspace" / "movie-tickets" / "venv" / "bin" / "python"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

CHALLENGE_MARKERS = ["Attention Required", "cf-challenge", "_Incapsula_",
                     "Checking your browser", "Just a moment",
                     "Verify you are human"]

SITES = {
    "amc": {
        "name": "AMC Sunset Place 24",
        "theater_id": "amc-sunset",
        "urls": ["https://www.amctheatres.com/movie-theatres/miami/amc-sunset-place-24"],
        "detail": ("Cloudflare bot-fight 'Attention Required' on amctheatres.com; "
                   "api.amctheatres.com/v2 requires vendor authentication."),
    },
    "silverspot": {
        "name": "Silverspot Cinema Downtown Miami",
        "theater_id": "silverspot-downtown",
        "urls": ["https://www.silverspot.net/"],
        "detail": "Cloudflare bot-fight 'Attention Required' on silverspot.net.",
    },
    "cinepolis": {
        "name": "Cinépolis Coconut Grove",
        "theater_id": "cinepolis-coconut-grove",
        "urls": ["https://www.cinepolisusa.com/"],
        "detail": "Cloudflare bot-fight 'Attention Required' on cinepolisusa.com.",
    },
}


def forwarder_up(port=8899):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def ensure_forwarder():
    """Start the auth-injecting forward proxy if the VM proxy env is set."""
    if not (os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")):
        return False
    if forwarder_up():
        return True
    try:
        subprocess.Popen(
            [sys.executable, str(HERE / "pw_proxy.py"), "8899"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            if forwarder_up():
                return True
            time.sleep(0.5)
    except Exception as e:
        print(f"  forwarder failed to start: {e}", flush=True)
    return False


def make_browser(pw, headless):
    from playwright_stealth import Stealth
    via_fw = ensure_forwarder()
    args = ["--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"]
    if via_fw:
        args += ["--proxy-server=http://127.0.0.1:8899",
                 "--ignore-certificate-errors"]
    browser = pw.chromium.launch(headless=headless, args=args)
    ctx = browser.new_context(
        user_agent=UA, viewport={"width": 1366, "height": 900},
        locale="en-US", timezone_id="America/New_York")
    page = ctx.new_page()
    Stealth().apply_stealth_sync(page)
    return browser, page


def challenged(page):
    try:
        html = page.content()
    except Exception:
        return True
    if page.title().startswith("Attention Required"):
        return True
    return any(m in html for m in CHALLENGE_MARKERS)


def generic_extract(page):
    """Heuristic: time-like buttons/links grouped under nearest heading.

    Returns [(movie_title, time_text, href)]. Works without site-specific
    selectors; only used when the Cloudflare challenge actually passes.
    """
    return page.evaluate(
        """() => {
            const out = [];
            const btns = [...document.querySelectorAll('a, button')]
                .filter(e => /\\b\\d{1,2}:\\d{2}\\s*[apAP][mM]\\b/.test(e.textContent)
                             && e.textContent.trim().length < 30);
            for (const b of btns) {
                const t = b.textContent.trim().match(/\\b\\d{1,2}:\\d{2}\\s*[apAP][mM]\\b/)[0];
                // nearest preceding heading = movie title
                let title = '';
                let el = b;
                for (let i = 0; i < 12 && el; i++) {
                    el = el.previousElementSibling || el.parentElement;
                    if (!el) break;
                    const h = el.querySelector ? el.querySelector('h1,h2,h3,h4') : null;
                    if (h && h.textContent.trim().length > 2) { title = h.textContent.trim(); break; }
                    if (/^H[1-4]$/.test(el.tagName) && el.textContent.trim().length > 2) {
                        title = el.textContent.trim(); break;
                    }
                }
                out.push({title: title.slice(0, 80), time: t,
                          href: (b.getAttribute('href') || '').slice(0, 200)});
            }
            return out;
        }""")


def normalize_time(t):
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP])M", t.strip().upper())
    if not m:
        return t.strip()
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3)
    if ap == "P" and h != 12:
        h += 12
    if ap == "A" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


def scrape_site(page, key):
    """Attempt one theater. Returns (listings, blocked_detail_or_None)."""
    site = SITES[key]
    listings = []
    for url in site["urls"]:
        print(f"  Playwright: {site['name']} -> {url}", flush=True)
        try:
            page.goto(url, wait_until="commit", timeout=60000)
        except Exception as e:
            print(f"    nav failed: {str(e)[:100]}", flush=True)
            continue
        # let challenge JS settle / page render
        time.sleep(8)
        if challenged(page):
            print(f"    BLOCKED: Cloudflare challenge page "
                  f"(title={page.title()!r})", flush=True)
            continue
        print(f"    page loaded: {page.title()!r}", flush=True)
        time.sleep(4)  # extra render time for SPA showtime grids
        try:
            rows = generic_extract(page)
        except Exception as e:
            print(f"    extract failed: {e}", flush=True)
            continue
        print(f"    extracted {len(rows)} time buttons", flush=True)
        today = date.today().isoformat()
        by_movie = {}
        for r in rows:
            if not r["title"]:
                continue
            href = r["href"]
            url_full = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")
            by_movie.setdefault(r["title"], []).append({
                "time": normalize_time(r["time"]),
                "format": "Standard", "ticket_url": url_full})
        for title, times in by_movie.items():
            times.sort(key=lambda x: x["time"])
            listings.append({
                "theater": site["name"], "theater_id": site["theater_id"],
                "movie": title, "date": today, "times": times,
                "format": "Standard", "ticket_url": times[0]["ticket_url"],
                "source": "playwright"})
        if listings:
            break
        time.sleep(3)
    if listings:
        return listings, None
    return [], site["detail"]


def scrape_all_pw(headless=True, only=None):
    """Returns (listings, blocked_dict). Never raises."""
    from playwright.sync_api import sync_playwright
    listings, blocked = [], {}
    keys = [only] if only else list(SITES)
    with sync_playwright() as pw:
        browser, page = make_browser(pw, headless)
        try:
            for key in keys:
                try:
                    st, detail = scrape_site(page, key)
                    listings.extend(st)
                    if detail:
                        s = SITES[key]
                        blocked[s["theater_id"]] = {
                            "name": s["name"], "blocked": True,
                            "detail": detail}
                    time.sleep(3)
                except Exception as e:
                    s = SITES[key]
                    blocked[s["theater_id"]] = {
                        "name": s["name"], "blocked": True,
                        "detail": f"{s['detail']} (error: {e})"}
        finally:
            browser.close()
    return listings, blocked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true",
                    default=bool(os.environ.get("PW_HEADLESS") or not os.environ.get("DISPLAY")))
    ap.add_argument("--theater", default="all",
                    choices=["all", "amc", "silverspot", "cinepolis"])
    args = ap.parse_args()
    only = None if args.theater == "all" else args.theater
    listings, blocked = scrape_all_pw(headless=args.headless, only=only)
    print(json.dumps({"listings": len(listings), "blocked": blocked}, indent=1))
    if listings:
        print(json.dumps(listings[:2], indent=1)[:1500])


if __name__ == "__main__":
    main()
