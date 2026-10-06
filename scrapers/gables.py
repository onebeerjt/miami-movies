"""Scraper for Coral Gables Art Cinema (gablescinema.com).

Approach: the WordPress events page is server-rendered and lists every
film with dated showtimes (span.cust-date / span.cust-time). Film pages
have a fuller "Show Times" section (div.date-container) — fetched for
films showing "More Times". Ticket links point at AgileTix (which is
bot-blocked itself, but the URLs are still valid for users to tap).

No auth, no JS rendering needed. Polite: 1s between requests.
"""
import html as html_lib
import re
import time
import urllib.request
from datetime import date

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
EVENTS_URL = "https://gablescinema.com/events/"
THEATER = "Coral Gables Art Cinema"
THEATER_ID = "gables-cinema"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def parse_gables_date(s, today=None):
    """'tue. oct, 6' -> '2026-10-06'. Infers year; validates weekday."""
    today = today or date.today()
    m = re.match(r"(?:mon|tue|wed|thu|fri|sat|sun)\.\s*([a-z]{3}),\s*(\d{1,2})",
                 s.strip().lower())
    if not m:
        return None
    mon, day = MONTHS[m.group(1)], int(m.group(2))
    year = today.year
    if (mon, day) < (today.month, today.day):
        year += 1
    try:
        d = date(year, mon, day)
    except ValueError:
        return None
    # sanity: weekday name should match
    wd = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][d.weekday()]
    if wd != s.strip().lower()[:3]:
        return None
    return d.isoformat()


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


def parse_film_page(html, today):
    """Full 'Show Times' section from a film page. Returns [(date_iso, time, url)]."""
    out = []
    for m in re.finditer(
            r'<div class="date-container[^"]*">.*?<h4>(.*?)</h4>(.*?)'
            r'(?=<div class="date-container|$)', html, re.S):
        d_iso = parse_gables_date(re.sub(r"<[^>]+>", "", m.group(1)), today)
        if not d_iso:
            continue
        for tm in re.finditer(
                r'<div class="time-main">\s*<a href="([^"]+)"[^>]*>\s*<span>(.*?)</span>',
                m.group(2), re.S):
            url, t = tm.groups()
            url = url.replace("&amp;", "&")
            out.append((d_iso, normalize_time(t), url))
    return out


def scrape():
    """Returns normalized showtime dicts."""
    today = date.today()
    html = fetch(EVENTS_URL)
    films = []
    # split on feed-show card boundaries (cards contain nested divs,
    # so slice between consecutive card starts instead of regex-matching)
    # Only "feed-show working" cards are the real dated listings; plain
    # "feed-show" divs are a separate undated feed elsewhere on the page.
    starts = [m.start() for m in re.finditer(r'<div class="feed-show working"', html)]
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(html)
        card = html[start:end]
        tm = re.search(r'<h2><a href="([^"]+)">([^<]+)</a></h2>', card)
        if not tm:
            continue
        film_url, title = tm.groups()
        title = html_lib.unescape(title).strip()
        cat_m = re.search(r'<span class="program-cat"[^>]*>([^<]+)</span>', card)
        category = cat_m.group(1).strip() if cat_m else ""
        rt_m = re.search(r'<h2 class="timer">([^<]*)</h2>', card)
        runtime = rt_m.group(1).strip() if rt_m else ""
        # preview showtimes on the card
        preview = []
        more = False
        for li in re.finditer(r"<li>(.*?)</li>", card, re.S):
            li_h = li.group(1)
            if "more-times" in li_h:
                more = True
                continue
            dm = re.search(r'<span class="cust-date">([^<]+)</span>', li_h)
            tm2 = re.search(r'<span class="cust-time">\s*<a href="([^"]+)"[^>]*>([^<]+)</a>',
                            li_h, re.S)
            if dm and tm2:
                d_iso = parse_gables_date(dm.group(1), today)
                if d_iso:
                    preview.append((d_iso, normalize_time(tm2.group(2)),
                                    tm2.group(1).replace("&amp;", "&")))
        films.append({"title": title, "url": film_url,
                      "category": category, "runtime": runtime,
                      "preview": preview, "more": more})
        print(f"  Gables: {title} ({category}) — "
              f"{len(preview)} preview times{' +more' if more else ''}", flush=True)

    showtimes = []
    for f in films:
        # full schedule from the film page (has more dates than the card)
        try:
            fhtml = fetch(f["url"])
            full = parse_film_page(fhtml, today)
            time.sleep(1)
        except Exception as e:
            print(f"  Gables film page failed {f['title']}: {e}", flush=True)
            full = []
        sched = full or f["preview"]
        # group by date
        by_date = {}
        for d_iso, t, url in sched:
            by_date.setdefault(d_iso, []).append(
                {"time": t, "format": f["category"] or "Standard",
                 "ticket_url": url})
        for d_iso, times in sorted(by_date.items()):
            times.sort(key=lambda x: x["time"])
            showtimes.append({
                "theater": THEATER, "theater_id": THEATER_ID,
                "movie": f["title"], "date": d_iso,
                "times": times, "format": times[0]["format"],
                "ticket_url": times[0]["ticket_url"],
                "source": "gablescinema.com",
            })
    return showtimes


if __name__ == "__main__":
    import json
    st = scrape()
    print(json.dumps(st[:3], indent=1))
    print(f"TOTAL {len(st)} listings")
