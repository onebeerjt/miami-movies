"""Probe v2: headed Chromium under xvfb + playwright-stealth.

Run: xvfb-run -a venv/bin/python scrapers/pw_probe.py
"""
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TARGETS = {
    "amc": ["https://www.amctheatres.com/movie-theatres/miami/amc-sunset-place-24"],
    "silverspot": ["https://www.silverspot.net/"],
    "cinepolis": ["https://www.cinepolisusa.com/"],
    "gables": ["https://gablescinema.com/"],
}

CHALLENGE_MARKERS = ["Attention Required", "cf-challenge", "_Incapsula_",
                     "incapsula", "Checking your browser", "Just a moment",
                     "Verify you are human", "cf_clearance"]


def make_page(pw):
    use_local = bool(os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY"))
    args = ["--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"]
    if use_local:
        args += ["--proxy-server=http://127.0.0.1:8899", "--ignore-certificate-errors"]
    browser = pw.chromium.launch(headless=False, args=args)
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
    )
    page = ctx.new_page()
    Stealth().apply_stealth_sync(page)
    return browser, page


def probe_one(page, tid, url):
    info = {"url": url}
    try:
        # commit returns as soon as the response arrives; then poll for content
        page.goto(url, wait_until="commit", timeout=60000)
        deadline = time.time() + 60
        html = ""
        while time.time() < deadline:
            time.sleep(3)
            try:
                html = page.content()
            except Exception:
                continue
            if len(html) > 8000 and page.title():
                break
        info["title"] = page.title()
        info["len"] = len(html)
        info["challenge"] = any(k in html for k in CHALLENGE_MARKERS)
        # save a snippet for inspection
        snip = html[:3000].replace("\n", " ")
        info["snippet"] = snip[:600]
        times = page.evaluate(
            """() => [...document.querySelectorAll('a, button')]
                .filter(e => /\\d{1,2}:\\d{2}\\s*[apAP][mM]/.test(e.textContent))
                .slice(0, 8)
                .map(e => ({cls: (e.className||'').toString().slice(0,60),
                           txt: e.textContent.trim().slice(0,50),
                           href: (e.getAttribute('href')||'').slice(0,100)}))""")
        info["time_buttons"] = times
    except Exception as e:
        info["error"] = str(e)[:300]
    return info


def main():
    results = {}
    with sync_playwright() as pw:
        browser, page = make_page(pw)
        for tid, urls in TARGETS.items():
            for url in urls:
                print(f"Probing {tid}: {url}", flush=True)
                info = probe_one(page, tid, url)
                results.setdefault(tid, []).append(info)
                print(f"  title={info.get('title')!r} challenge={info.get('challenge')} "
                      f"len={info.get('len')} time_buttons={len(info.get('time_buttons', []))} "
                      f"err={(info.get('error') or '')[:80]}", flush=True)
                time.sleep(3)
        browser.close()
    out = Path(__file__).parent / "pw_probe_results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
