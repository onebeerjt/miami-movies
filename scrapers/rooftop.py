"""Scraper for Rooftop Cinema Club - Miami Beach.

Approach: server-rendered HTML on the /us/miami-beach page.
Screening cards carry title, date, time, venue, and detail links.
No auth, no JS rendering needed.
"""
import re
import time
import urllib.request
from datetime import date

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://rooftopcinemaclub.com"
PAGE = BASE + "/us/miami-beach"
THEATER = "Rooftop Cinema Club Miami"
THEATER_ID = "rooftop-miami"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def parse_date(s):
    # "Tue, Oct 6" -> ISO date (assume current/next year as needed)
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", s)
    if not m:
        return None
    mon, day = MONTHS[m.group(1)], int(m.group(2))
    today = date.today()
    year = today.year
    try:
        d = date(year, mon, day)
    except ValueError:
        return None
    if d < today - timedelta(days=2):
        # likely next year
        try:
            d = date(year + 1, mon, day)
        except ValueError:
            return None
    return d.isoformat()


def normalize_time(t):
    t = t.strip()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", t, re.I)
    if not m:
        return t
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


from datetime import timedelta


def scrape():
    html = fetch(PAGE)
    out = []
    uuids = re.findall(r'data-checkout-screening="([a-f0-9-]+)"', html)
    seen = set()
    for u in uuids:
        if u in seen:
            continue
        seen.add(u)
        idx = html.find(u)
        back = html[max(0, idx - 3000):idx]
        fwd = html[idx:idx + 1200]
        titles = re.findall(r"<h[2-4][^>]*>([^<]{3,100})</h[2-4]>", back)
        title = titles[-1].strip() if titles else None
        # date/time appear BEFORE the checkout button in the card
        back_text = re.sub(r"<[^>]+>", "|", back)
        dates_found = re.findall(
            r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2})",
            back_text)
        times_found = re.findall(r"(\d{1,2}:\d{2}\s*(?:AM|PM))", back_text, re.I)
        date_m = dates_found[-1] if dates_found else None
        time_m = times_found[-1] if times_found else None
        link_m = re.search(r'href="(/us/miami-beach[^"]*screenings/[^"]+)"', fwd)
        venue_m = re.search(r"(South Beach, Miami)", back_text)
        if not title:
            continue
        day_iso = parse_date(date_m[1]) if date_m else None
        t_norm = normalize_time(time_m) if time_m else None
        out.append({
            "theater": THEATER,
            "theater_id": THEATER_ID,
            "movie": title,
            "date": day_iso,
            "times": [{
                "time": t_norm,
                "format": "Outdoor",
                "ticket_url": BASE + link_m.group(1) if link_m else PAGE,
            }],
            "format": "Outdoor",
            "ticket_url": BASE + link_m.group(1) if link_m else PAGE,
            "venue_note": venue_m.group(1).strip() if venue_m else None,
        })
        time.sleep(0.2)
    print(f"  Rooftop: {len(out)} screenings", flush=True)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scrape(), indent=1)[:2000])
