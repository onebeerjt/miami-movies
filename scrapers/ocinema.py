"""Scraper for O Cinema (o-cinema.org).

Approach: crawl event pages from the homepage. Each /events/<slug> page
has the title (h1), venue/date/time blocks, and ticket links.
No auth, no JS rendering needed. Polite crawling with delays.
"""
import re
import time
import urllib.request
from datetime import date

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://www.o-cinema.org"
THEATER = "O Cinema"
THEATER_ID = "o-cinema"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def parse_event(html, url):
    import html as htmlmod
    h1 = re.search(r"<h1[^>]*>([^<]{3,120})</h1>", html)
    title = htmlmod.unescape(h1.group(1).strip()) if h1 else None
    if not title:
        return None
    # Only parse the dedicated Showtimes section (not Related Events).
    # Strip tags first so date|time patterns are contiguous.
    s_idx = html.find(">Showtimes<")
    r_idx = html.find(">Related Events<")
    raw_section = html[s_idx:r_idx] if s_idx != -1 and r_idx != -1 else html
    section = re.sub(r"<[^>]+>", "|", raw_section)
    section = re.sub(r"\|+", "|", section)
    # Venue for this event
    venue_m = re.search(r'item_details-location[^>]*>([^<]{2,60})</div>', html)
    venue = htmlmod.unescape(venue_m.group(1).strip()) if venue_m else "O Cinema"
    blocks = []
    for m in re.finditer(
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\|'
            r'(\d{1,2}:\d{2}\s*(?:am|pm))',
            section, re.I):
        _dow, mon, day, t = m.groups()
        blocks.append((venue, mon, day, t))
    if not blocks:
        return None  # no parseable showtimes; don't fall back to page-wide times
    # group by date
    by_date = {}
    for venue, mon, day, t in blocks:
        try:
            d = date(2026, MONTHS[mon[:3].title()], int(day))
        except (ValueError, KeyError):
            continue
        # roll year if clearly past
        if d < date.today() - timedelta(days=60):
            try:
                d = date(2027, MONTHS[mon[:3].title()], int(day))
            except (ValueError, KeyError):
                continue
        key = (d.isoformat(), venue)
        by_date.setdefault(key, []).append(normalize_time(t))
    out = []
    for (day_iso, venue), times in by_date.items():
        uniq = sorted(set(times))
        out.append({
            "theater": f"O Cinema — {venue}" if venue != "O Cinema" else THEATER,
            "theater_id": THEATER_ID,
            "movie": title,
            "date": day_iso,
            "times": [{"time": t, "format": "Standard", "ticket_url": url}
                      for t in uniq],
            "format": "Standard",
            "ticket_url": url,
        })
    return out


def normalize_time(t):
    t = t.strip()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", t, re.I)
    if not m:
        return t
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3).lower()
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


from datetime import timedelta


def scrape(max_events=25):
    html = fetch(BASE + "/")
    slugs = sorted(set(re.findall(r'href="(/events/[a-z0-9-]+)"', html)))
    print(f"  O Cinema: {len(slugs)} event links found", flush=True)
    out = []
    for slug in slugs[:max_events]:
        url = BASE + slug
        try:
            page = fetch(url)
            ev = parse_event(page, url)
            if ev:
                out.extend(ev)
        except Exception as e:
            print(f"  O Cinema {slug}: ERROR {e}", flush=True)
        time.sleep(1)
    print(f"  O Cinema: {len(out)} dated listings", flush=True)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scrape(3), indent=1)[:2500])
