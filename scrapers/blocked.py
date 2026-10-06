"""Blocked theaters: documented scraping attempts (Oct 6, 2026).

These four theaters cannot be scraped with simple HTTP requests:

1. AMC Sunset Place 24 (amctheatres.com)
   - Website: Cloudflare "Attention Required" bot challenge (HTTP 403) for
     all paths, including /api/*, even with full browser headers.
   - Internal API api.amctheatres.com/v2/* responds but requires vendor
     authentication ("The request requires vendor authentication").
   - Verdict: needs a real browser session (Playwright + stealth) or the
     commercial partner API. Out of scope for a curl-based weekly cron.

2. Silverspot Cinema Downtown Miami (silverspot.net)
   - Website: Cloudflare bot challenge (HTTP 403) on all paths.
   - No alternate ticketing subdomain found (tickets.silverspot.net NXDOMAIN).
   - Verdict: same as AMC — needs browser automation.

3. Cinépolis Coconut Grove (cinepolisusa.com)
   - Website: Cloudflare bot challenge (HTTP 403) on all paths.
   - Verdict: same as above.

4. Coral Gables Art Cinema (gablescinema.com)
   - The WordPress site itself IS scrapable and lists current films, but
     real showtime booking runs on AgileTix (prod3.agileticketing.net),
     which is behind Incapsula/Imperva bot protection (empty 212-byte
     challenge page for all requests).
   - The WP REST API exposes a stale "resource" post type (2023 data).
   - Film pages DO list screening times per movie but without reliable
     dates in the markup.
   - Verdict: partially scrapable for "now showing" titles only; real
     dated showtimes blocked.

Each function below attempts a lightweight fetch and returns [] with a
documented reason, so the orchestrator degrades gracefully and the app
can fall back to deep links for these theaters.
"""
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

BLOCKED = {
    "amc-sunset": ("AMC Sunset Place 24",
                   "Cloudflare bot challenge on amctheatres.com; vendor auth required on api.amctheatres.com"),
    "silverspot-downtown": ("Silverspot Cinema Downtown Miami",
                            "Cloudflare bot challenge on silverspot.net"),
    "cinepolis-coconut-grove": ("Cinépolis Coconut Grove",
                                "Cloudflare bot challenge on cinepolisusa.com"),
    "gables-cinema": ("Coral Gables Art Cinema",
                      "Ticketing on Incapsula-blocked AgileTix; site lists films but not dated showtimes"),
}


def _probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read(600)
        return r.status, b"Attention Required" in body or b"_Incapsula_" in body


def check_all():
    """Re-probe each blocked theater; returns {theater_id: {blocked, detail}}."""
    probes = {
        "amc-sunset": "https://www.amctheatres.com/movie-theatres/miami/amc-sunset-place-24",
        "silverspot-downtown": "https://www.silverspot.net/",
        "cinepolis-coconut-grove": "https://www.cinepolisusa.com/",
        "gables-cinema": "https://prod3.agileticketing.net/websales/pages/list.aspx?epguid=6ec0e98b-d23e-4240-acce-5ffa059e6887",
    }
    results = {}
    for tid, url in probes.items():
        name, reason = BLOCKED[tid]
        try:
            status, challenged = _probe(url)
            results[tid] = {"name": name, "blocked": challenged or status == 403,
                            "detail": reason, "probe_status": status}
        except Exception as e:
            results[tid] = {"name": name, "blocked": True,
                            "detail": f"{reason} (probe error: {e})",
                            "probe_status": None}
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(check_all(), indent=1))
