"""Scraper for CMX Cinemas - Brickell City Centre.

Approach: server-rendered HTML. The theater page embeds full showtime
listings; a ?date=YYYY-MM-DD query param selects the day.
No auth, no JS rendering needed.
"""
import re
import time
import urllib.request
from datetime import date, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://www.cmxcinemas.com/cmx-brickell-city-centre-dine-in"
THEATER = "CMX Brickell City Centre"
THEATER_ID = "cmx-brickell"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def parse_day(html, day_iso):
    """Parse one day's showtime grid. Returns list of showtime dicts."""
    out = []
    grid_start = html.find("cin-showtimes-grid")
    if grid_start == -1:
        return out
    grid = html[grid_start:]
    # Split into movie cards
    cards = re.split(r'<div class="cin-movie-card', grid)[1:]
    for card in cards:
        title_m = re.search(r"<h3[^>]*>([^<]+)</h3>", card)
        if not title_m:
            continue
        title = title_m.group(1).strip()
        # Format groups: each has a format label then time buttons
        # Find all format sections within this card (up to next card)
        fmt_blocks = re.findall(
            r'<div class="text-body-accent-text[^"]*"[^>]*>(.*?)</div>(.*?)(?=<div class="text-body-accent-text|$)',
            card, re.S)
        if not fmt_blocks:
            # No explicit format groups; treat whole card as one group
            fmt_blocks = [("", card)]
        for fmt_html, btn_html in fmt_blocks:
            fmt = re.sub(r"<[^>]+>", "", fmt_html).strip()
            fmt = re.sub(r"\s+", " ", fmt) or "Standard"
            times = []
            for bm in re.finditer(
                    r'<a[^>]*class="cin-showtimes-button[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                    btn_html, re.S):
                url, inner = bm.groups()
                t = re.sub(r"<[^>]+>", "", inner).strip()
                t = re.sub(r"\s+", " ", t)
                # time looks like "2:00p" or "12:05p"
                tm = re.search(r"(\d{1,2}:\d{2}\s*[ap])", t, re.I)
                if tm:
                    times.append({"time": normalize_time(tm.group(1)),
                                  "format": fmt, "ticket_url": url})
            if times:
                out.append({"theater": THEATER, "theater_id": THEATER_ID,
                            "movie": title, "date": day_iso,
                            "times": times, "format": fmt,
                            "ticket_url": times[0]["ticket_url"]})
    return out


def normalize_time(t):
    t = t.strip().lower().replace(" ", "")
    m = re.match(r"(\d{1,2}):(\d{2})([ap])", t)
    if not m:
        return t
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3)
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


def scrape(days=7):
    """Scrape today + next `days-1` days. Polite: 1s between requests."""
    all_showtimes = []
    today = date.today()
    for i in range(days):
        d = today + timedelta(days=i)
        day_iso = d.isoformat()
        try:
            html = fetch(f"{BASE}?date={day_iso}")
            day_st = parse_day(html, day_iso)
            all_showtimes.extend(day_st)
            print(f"  CMX {day_iso}: {len(day_st)} listings", flush=True)
        except Exception as e:
            print(f"  CMX {day_iso}: ERROR {e}", flush=True)
        time.sleep(1)
    return all_showtimes


if __name__ == "__main__":
    import json
    print(json.dumps(scrape(2), indent=1)[:2000])
